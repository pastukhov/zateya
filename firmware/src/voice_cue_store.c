#include "voice_cue_store.h"
#include "voice_cue_opus.h"
#include <stdio.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static uint32_t u32(const uint8_t *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static void put32(uint8_t *p,uint32_t x){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(x>>(8*i));}
bool voice_cue_store_layout_valid(uint32_t size,const voice_cue_partition_t *p,size_t count){
 if(size!=0x800000 || !p || count!=5)return false;
 const voice_cue_partition_t expected[]={
  {1,2,0x9000,0x6000,0,0},{1,1,0xf000,0x1000,0,0},{1,0,0x10000,0x2000,0,0},
  {0,0x10,0x20000,0x300000,0,0},{0,0x11,0x320000,0x300000,0,0}};
 unsigned seen=0;
 for(size_t i=0;i<count;i++){
  if(p[i].encrypted||p[i].readonly||!p[i].size||p[i].offset%4096||p[i].size%4096||
     (uint64_t)p[i].offset+p[i].size>VOICE_CUE_STORE_OFFSET)return false;
  bool found=false;
  for(unsigned j=0;j<5;j++)if(p[i].type==expected[j].type && p[i].subtype==expected[j].subtype &&
    p[i].offset==expected[j].offset && p[i].size==expected[j].size){
    if(seen&(1U<<j))return false;
    seen|=1U<<j;found=true;break;
  }
  if(!found)return false;
 }
 return seen==31;
}
bool voice_cue_record_encode_codec(uint8_t h[VOICE_CUE_RECORD_HEADER],voice_cue_name_t name,size_t size,const char *sha,voice_cue_codec_t codec){
 const char *label=voice_cue_name(name);
 if(!h||!label||!sha||strlen(sha)!=64)return false;
 for(unsigned i=0;i<64;i++)if(!((sha[i]>='0'&&sha[i]<='9')||(sha[i]>='a'&&sha[i]<='f')))return false;
 if(codec==VOICE_CUE_PCM16){if(!voice_cue_metadata_valid(size,24000,1,16,sha))return false;}
 else if(codec!=VOICE_CUE_OPUS||size<34||size>65536)return false;
 memset(h,0,VOICE_CUE_RECORD_HEADER);memcpy(h,codec==VOICE_CUE_OPUS?"VCUEOPU1":"VCUEPCM1",8);put32(h+8,codec==VOICE_CUE_OPUS?2:1);put32(h+12,(uint32_t)size);
 memcpy(h+16,label,strlen(label));memcpy(h+40,sha,64);put32(h+108,24000);h[112]=1;h[114]=16;put32(h+116,codec);
 return true;
}
bool voice_cue_record_decode(const uint8_t h[VOICE_CUE_RECORD_HEADER],voice_cue_name_t name,size_t bytes,voice_cue_record_t *r){
 const char *label=voice_cue_name(name);
 if(!h||!r||!label)return false;
 voice_cue_codec_t codec=!memcmp(h,"VCUEPCM1",8)&&u32(h+8)==1?VOICE_CUE_PCM16:
  !memcmp(h,"VCUEOPU1",8)&&u32(h+8)==2?VOICE_CUE_OPUS:(voice_cue_codec_t)2;
 if(codec>VOICE_CUE_OPUS||u32(h+116)!=(uint32_t)codec||
    !memchr(h+16,0,24)||strcmp((const char*)h+16,label)||h[104]||
    u32(h+108)!=24000||h[112]!=1||h[113]||h[114]!=16||h[115])return false;
 size_t n=u32(h+12);char sha[65];memcpy(sha,h+40,64);sha[64]=0;
 uint8_t expected[128];
 if(!voice_cue_record_encode_codec(expected,name,n,sha,codec)||bytes!=VOICE_CUE_RECORD_HEADER+n)return false;
 r->size=n;r->codec=codec;memcpy(r->sha,sha,65);return true;
}
bool voice_cue_record_verify(const uint8_t h[VOICE_CUE_RECORD_HEADER],const uint8_t *pcm,size_t n,voice_cue_name_t name,voice_cue_hash_fn hash){
 voice_cue_record_t r;uint8_t digest[32];char actual[65];
 if(!pcm||!hash||!voice_cue_record_decode(h,name,VOICE_CUE_RECORD_HEADER+n,&r)||!hash(pcm,n,digest))return false;
 for(unsigned i=0;i<32;i++)snprintf(actual+2*i,3,"%02x",digest[i]);
 voice_cue_opus_t opus;
 return !strcmp(actual,r.sha) && (r.codec==VOICE_CUE_PCM16 || voice_cue_opus_parse(pcm,n,&opus));
}
static bool path(voice_cue_store_t *s,voice_cue_name_t name,const char *suffix,char out[192]){
 const char *label=voice_cue_name(name);if(!s||!label)return false;
 int n=snprintf(out,192,"%s/%s.%s",s->root,label,suffix);return n>0&&n<192;
}
bool voice_cue_store_init(voice_cue_store_t *s,const char *root,voice_cue_hash_fn hash){
 if(!s||!root||!hash||!*root||strlen(root)>=sizeof(s->root))return false;
 memset(s,0,sizeof(*s));strcpy(s->root,root);s->hash=hash;s->limit=VOICE_CUE_STORE_LIMIT;return true;
}
static bool header(FILE *f,voice_cue_name_t name,uint8_t h[128],voice_cue_record_t *r){
 struct stat info;
 return fstat(fileno(f),&info)==0 && S_ISREG(info.st_mode) && info.st_size>=128 &&
  info.st_size<=128+VOICE_CUE_MAX_BYTES && fread(h,1,128,f)==128 &&
  voice_cue_record_decode(h,name,(size_t)info.st_size,r);
}
bool voice_cue_store_info_codec(voice_cue_store_t *s,voice_cue_name_t name,voice_cue_codec_t codec,voice_cue_record_t *r){
 char file[192];uint8_t h[128];if(!path(s,name,codec==VOICE_CUE_OPUS?"vopus":"vcue",file))return false;
 FILE *f=fopen(file,"rb");if(!f)return false;
 bool valid=header(f,name,h,r)&&r->codec==codec;if(fclose(f))valid=false;
 return valid;
}
bool voice_cue_store_load_codec(voice_cue_store_t *s,voice_cue_name_t name,voice_cue_codec_t codec,uint8_t *pcm,size_t cap,voice_cue_record_t *r){
 char file[192];uint8_t h[128];if(!pcm||!path(s,name,codec==VOICE_CUE_OPUS?"vopus":"vcue",file))return false;
 FILE *f=fopen(file,"rb");if(!f)return false;
 bool valid=header(f,name,h,r) && r->codec==codec && r->size<=cap && fread(pcm,1,r->size,f)==r->size &&
  voice_cue_record_verify(h,pcm,r->size,name,s->hash);
 if(fclose(f))valid=false;
 return valid;
}
static bool identical(const char *file,voice_cue_name_t name,const uint8_t *pcm,size_t size,const char *sha,voice_cue_codec_t codec){
 FILE *f=fopen(file,"rb");if(!f)return false;
 uint8_t h[128],chunk[512];voice_cue_record_t r;
 bool valid=header(f,name,h,&r)&&r.codec==codec&&r.size==size&&!strcmp(r.sha,sha);
 for(size_t offset=0;valid&&offset<size;){size_t n=size-offset;if(n>sizeof(chunk))n=sizeof(chunk);
  valid=fread(chunk,1,n,f)==n&&!memcmp(chunk,pcm+offset,n);offset+=n;
 }
 if(fclose(f))valid=false;
 return valid;
}
voice_cue_store_result_t voice_cue_store_put_codec(voice_cue_store_t *s,voice_cue_name_t name,const uint8_t *pcm,size_t size,const char *sha,voice_cue_codec_t codec){
 uint8_t h[128];char file[192],temp[192];
 if(!s||!voice_cue_record_encode_codec(h,name,size,sha,codec)||!voice_cue_record_verify(h,pcm,size,name,s->hash)||
    !path(s,name,codec==VOICE_CUE_OPUS?"vopus":"vcue",file)||!path(s,name,codec==VOICE_CUE_OPUS?"opus.tmp":"tmp",temp))return VOICE_CUE_STORE_FAILED;
 if(identical(file,name,pcm,size,sha,codec))return VOICE_CUE_STORE_UNCHANGED;
 uint64_t total=128+size;
 for(unsigned i=0;i<VOICE_CUE_COUNT;i++)for(unsigned kind=0;kind<2;kind++){
  if(i==(unsigned)name&&kind==(unsigned)codec)continue;
  char other[192];struct stat info;path(s,(voice_cue_name_t)i,kind?"vopus":"vcue",other);
  if(stat(other,&info)==0){
   if(!S_ISREG(info.st_mode)||info.st_size<0||info.st_size>128+(kind?65536:240000))return VOICE_CUE_STORE_FAILED;
   total+=(uint64_t)info.st_size;
  }else if(errno!=ENOENT)return VOICE_CUE_STORE_FAILED;
 }
 if(total>s->limit)return VOICE_CUE_STORE_FAILED;
 /* Only a fixed owned temp is removed. Never unlink the committed record. */
 (void)unlink(temp);FILE *f=fopen(temp,"wb");if(!f)return VOICE_CUE_STORE_FAILED;
 bool valid=fwrite(h,1,128,f)==128;
 for(size_t offset=0;valid&&offset<size;){size_t n=size-offset;if(n>4096)n=4096;
  valid=fwrite(pcm+offset,1,n,f)==n;offset+=n;
 }
 if(fflush(f))valid=false;
 if(valid&&fsync(fileno(f)))valid=false;
 if(fclose(f))valid=false;
 if(valid)valid=identical(temp,name,pcm,size,sha,codec);
 if(!valid || rename(temp,file)){(void)unlink(temp);return VOICE_CUE_STORE_FAILED;}
 return VOICE_CUE_STORE_WRITTEN;
}
void voice_cue_store_clean_temps(voice_cue_store_t *s){
 for(unsigned i=0;i<VOICE_CUE_COUNT;i++)for(unsigned kind=0;kind<2;kind++){
  char temp[192];if(path(s,(voice_cue_name_t)i,kind?"opus.tmp":"tmp",temp))(void)unlink(temp);
 }
}
bool voice_cue_record_encode(uint8_t h[128],voice_cue_name_t name,size_t n,const char *sha){return voice_cue_record_encode_codec(h,name,n,sha,VOICE_CUE_PCM16);}
bool voice_cue_store_info(voice_cue_store_t *s,voice_cue_name_t name,voice_cue_record_t *r){return voice_cue_store_info_codec(s,name,VOICE_CUE_PCM16,r);}
bool voice_cue_store_load(voice_cue_store_t *s,voice_cue_name_t name,uint8_t *p,size_t n,voice_cue_record_t *r){return voice_cue_store_load_codec(s,name,VOICE_CUE_PCM16,p,n,r);}
voice_cue_store_result_t voice_cue_store_put(voice_cue_store_t *s,voice_cue_name_t name,const uint8_t *p,size_t n,const char *sha){return voice_cue_store_put_codec(s,name,p,n,sha,VOICE_CUE_PCM16);}
