/* Bounded JSON reader. Validates the entire response and only accepts a
 * root follow_up object. No substring matches in quoted/nested data. */
#include "voice_turn_client.h"
#include <string.h>
#include <stdlib.h>
#include <ctype.h>

typedef struct { const char *p; unsigned depth; } reader_t;
static void ws(reader_t *r){while(*r->p==' '||*r->p=='\r'||*r->p=='\n'||*r->p=='\t')r->p++;}
static bool string(reader_t *r,char *out,size_t cap){
 if(*r->p++!='"')return false;
 size_t used=0;
 while(*r->p && *r->p!='"'){
  unsigned char c=(unsigned char)*r->p++;
  if(c<32)return false;
  if(c=='\\'){
   c=(unsigned char)*r->p++;
   if(c=='u'){for(unsigned i=0;i<4;i++)if(!isxdigit((unsigned char)*r->p++))return false;c='?';}
   else if(!strchr("\"\\/bfnrt",c)||!c)return false;
   /* Escaped keys/IDs are valid JSON but never protocol matches. */
   c='?';
  }
  if(out){if(used+1>=cap)return false;out[used++]=(char)c;}
 }
 if(*r->p!='"')return false;
 r->p++;
 if(out)out[used]='\0';
 return true;
}
static bool value(reader_t *r);
static bool container(reader_t *r,bool object){
 if(++r->depth>8)return false;
 r->p++;ws(r);char end=object?'}':']';
 if(*r->p==end){r->p++;r->depth--;return true;}
 for(;;){
  if(object){if(*r->p!='"'||!string(r,NULL,0))return false;ws(r);if(*r->p++!=':')return false;ws(r);}
  if(!value(r))return false;
  ws(r);
  if(*r->p==end){r->p++;r->depth--;return true;}
  if(*r->p++!=',')return false;
  ws(r);
 }
}
static bool value(reader_t *r){
 ws(r);
 if(*r->p=='{')return container(r,true);
 if(*r->p=='[')return container(r,false);
 if(*r->p=='"')return string(r,NULL,0);
 const char *literals[]={"true","false","null"};
 for(unsigned i=0;i<3;i++)if(!strncmp(r->p,literals[i],strlen(literals[i]))){r->p+=strlen(literals[i]);return true;}
 const char *start=r->p;
 if(*r->p=='-')r->p++;
 if(*r->p=='0')r->p++;
 else {if(*r->p<'1'||*r->p>'9')return false;while(isdigit((unsigned char)*r->p))r->p++;}
 if(*r->p=='.'){r->p++;if(!isdigit((unsigned char)*r->p))return false;while(isdigit((unsigned char)*r->p))r->p++;}
 if(*r->p=='e'||*r->p=='E'){r->p++;if(*r->p=='+'||*r->p=='-')r->p++;if(!isdigit((unsigned char)*r->p))return false;while(isdigit((unsigned char)*r->p))r->p++;}
 return r->p>start;
}
static bool uuid(const char *id){
 if(strlen(id)!=36)return false;
 for(unsigned i=0;i<36;i++)if(i==8||i==13||i==18||i==23){if(id[i]!='-')return false;}else if(!isxdigit((unsigned char)id[i]))return false;
 return true;
}
static bool follow(reader_t *r,char *id,bool *listen){
 ws(r);if(!strncmp(r->p,"null",4)){r->p+=4;return true;}
 if(*r->p++!='{')return false;
 ws(r);
 bool got_id=false,got_listen=false;
 for(;;){char key[64];if(*r->p!='"'||!string(r,key,sizeof(key)))return false;ws(r);if(*r->p++!=':')return false;ws(r);
  if(!strcmp(key,"question_id")){if(got_id||*r->p!='"'||!string(r,id,37)||!uuid(id))return false;got_id=true;}
  else if(!strcmp(key,"listen")){if(got_listen)return false;got_listen=true;
   if(!strncmp(r->p,"true",4)){*listen=true;r->p+=4;}
   else if(!strncmp(r->p,"false",5)){*listen=false;r->p+=5;}else return false;
  }else if(!value(r))return false;
  ws(r);if(*r->p=='}'){r->p++;break;}if(*r->p++!=',')return false;
  ws(r);
 }
 return got_id&&got_listen;
}
bool voice_turn_parse_metadata(const char *json,char *question_id,size_t capacity,bool *listen,voice_turn_error_t *error){
 if(!json||!question_id||capacity<37||!listen||!error||strlen(json)>1024)return false;
 *error=VOICE_TURN_ERROR_NONE;
 question_id[0]='\0';*listen=false;reader_t r={.p=json};ws(&r);if(*r.p++!='{')return false;ws(&r);
 bool seen=false,seen_error=false;
 if(*r.p!='}')for(;;){char key[64];if(*r.p!='"'||!string(&r,key,sizeof(key)))return false;ws(&r);if(*r.p++!=':')return false;ws(&r);
  if(!strcmp(key,"follow_up")){if(seen||!follow(&r,question_id,listen))return false;seen=true;}
  else if(!strcmp(key,"error")){
   if(seen_error)return false;
   seen_error=true;
   if(!strncmp(r.p,"null",4))r.p+=4;
   else {
    char code[48];if(*r.p!='"'||!string(&r,code,sizeof(code))||!code[0])return false;
    for(const char *c=code;*c;c++)if(!((*c>='a'&&*c<='z')||(*c>='0'&&*c<='9')||*c=='_'))return false;
    *error=!strcmp(code,"agent_timeout")?VOICE_TURN_ERROR_AGENT_TIMEOUT:
     !strcmp(code,"stt_failed")||!strcmp(code,"empty_transcript")?VOICE_TURN_ERROR_STT_FAILED:
     !strcmp(code,"tts_failed")?VOICE_TURN_ERROR_TTS_FAILED:
     !strcmp(code,"audio_receive_failed")?VOICE_TURN_ERROR_CONNECTION:VOICE_TURN_ERROR_UNKNOWN;
   }
  }
  else if(!value(&r))return false;
  ws(&r);if(*r.p=='}')break;if(*r.p++!=',')return false;ws(&r);
 }
 if(*r.p++!='}')return false;
 ws(&r);return *r.p=='\0';
}

bool voice_turn_parse_follow_up(const char *json,char *id,size_t capacity,bool *listen){
 voice_turn_error_t error;return voice_turn_parse_metadata(json,id,capacity,listen,&error);
}

bool voice_turn_parse_stream_flags(const char *json,bool *ready,bool *consumed){
 if(!json||!ready||!consumed||strlen(json)>1024)return false;
 *ready=false;*consumed=false;bool seen_ready=false,seen_consumed=false;
 reader_t r={.p=json};ws(&r);if(*r.p++!='{')return false;ws(&r);
 if(*r.p!='}')for(;;){
  char key[64];if(*r.p!='"'||!string(&r,key,sizeof(key)))return false;ws(&r);if(*r.p++!=':')return false;ws(&r);
  bool *out=NULL;
  if(!strcmp(key,"audio_stream_ready")){if(seen_ready)return false;seen_ready=true;out=ready;}
  else if(!strcmp(key,"audio_stream_consumed")){if(seen_consumed)return false;seen_consumed=true;out=consumed;}
  if(out){
   if(!strncmp(r.p,"true",4)){*out=true;r.p+=4;}
   else if(!strncmp(r.p,"false",5)){*out=false;r.p+=5;}else return false;
  }else if(!value(&r))return false;
  ws(&r);if(*r.p=='}')break;if(*r.p++!=',')return false;ws(&r);
 }
 if(*r.p++!='}')return false;
 ws(&r);return *r.p=='\0' && !(*ready&&*consumed);
}
