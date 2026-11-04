#include "voice_cue_generation.h"
#include "voice_mp3_player.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
#if defined(ESP_PLATFORM) || defined(VOICE_CUE_HOST_JSON)
#include "cJSON.h"
#endif
#ifdef ESP_PLATFORM
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#define alloc(n) heap_caps_malloc((n),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)
#else
#define alloc(n) malloc(n)
#endif

static bool hex(const char *s) {
  if(!s || strlen(s)!=64)return false;
  for(unsigned i=0;i<64;i++)
    if(!((s[i]>='0'&&s[i]<='9') || (s[i]>='a'&&s[i]<='f')))return false;
  return true;
}
static bool path(voice_cue_store_t *s,const char *id,unsigned i,char out[256]) {
  if(!s || !hex(id) || i>=VOICE_CUE_COUNT)return false;
  int n=snprintf(out,256,"%s/%s_%s.mp3",s->root,id,voice_cue_name((voice_cue_name_t)i));
  return n>0 && n<256;
}
void voice_cue_generation_free(voice_cue_generation_t *g) {
  if(!g)return;
  for(unsigned i=0;i<VOICE_CUE_COUNT;i++) {
    free(g->bank.slots[i].pcm);
    g->bank.slots[i].pcm=NULL;
  }
}
bool voice_cue_generation_parse(const char *json,voice_cue_generation_t *g) {
#if defined(ESP_PLATFORM) || defined(VOICE_CUE_HOST_JSON)
  cJSON *o=cJSON_Parse(json);
  if(!o)return false;
  cJSON *id=cJSON_GetObjectItemCaseSensitive(o,"generation_id");
  cJSON *codec=cJSON_GetObjectItemCaseSensitive(o,"codec");
  cJSON *status=cJSON_GetObjectItemCaseSensitive(o,"status");
  cJSON *items=cJSON_GetObjectItemCaseSensitive(o,"items");
  bool valid=cJSON_IsString(id)&&hex(id->valuestring)&&cJSON_IsString(codec)&&
    !strcmp(codec->valuestring,"mp3")&&cJSON_IsString(status)&&!strcmp(status->valuestring,"ready")&&
    cJSON_IsObject(items)&&cJSON_GetArraySize(items)==VOICE_CUE_COUNT;
  if(valid)memcpy(g->id,id->valuestring,65);
  size_t total=0;
  for(unsigned i=0;valid&&i<VOICE_CUE_COUNT;i++) {
    cJSON *item=cJSON_GetObjectItemCaseSensitive(items,voice_cue_name((voice_cue_name_t)i));
    cJSON *sha=cJSON_GetObjectItemCaseSensitive(item,"sha256");
    cJSON *size=cJSON_GetObjectItemCaseSensitive(item,"size");
    cJSON *duration=cJSON_GetObjectItemCaseSensitive(item,"duration_ms");
    cJSON *rate=cJSON_GetObjectItemCaseSensitive(item,"sample_rate");
    cJSON *channels=cJSON_GetObjectItemCaseSensitive(item,"channels");
    valid=cJSON_IsObject(item)&&cJSON_IsString(sha)&&hex(sha->valuestring)&&
      cJSON_IsNumber(size)&&size->valuedouble==size->valueint&&size->valueint>=4&&size->valueint<=VOICE_CUE_MAX_BYTES&&
      cJSON_IsNumber(duration)&&duration->valuedouble>0&&duration->valuedouble<=6000&&
      cJSON_IsNumber(rate)&&rate->valuedouble==rate->valueint&&(rate->valueint==24000||rate->valueint==44100||rate->valueint==48000)&&
      cJSON_IsNumber(channels)&&channels->valuedouble==channels->valueint&&(channels->valueint==1||channels->valueint==2);
    if(valid) {
      memcpy(g->sha[i],sha->valuestring,65);
      g->size[i]=(size_t)size->valueint;
      g->rate[i]=(unsigned)rate->valueint;
      g->channels[i]=(unsigned)channels->valueint;
      total+=g->size[i];
    }
  }
  cJSON_Delete(o);
  return valid && total<=VOICE_CUE_STORE_LIMIT;
#else
  (void)json;(void)g;
  return false;
#endif
}
static bool hash_matches(voice_cue_store_t *s,const uint8_t *data,size_t size,const char *sha) {
  uint8_t digest[32];char actual[65];
  if(!s->hash(data,size,digest))return false;
  for(unsigned i=0;i<32;i++)snprintf(actual+i*2,3,"%02x",digest[i]);
  return !strcmp(actual,sha);
}
static size_t discard(void *ctx,const uint8_t *data,size_t size) {
  (void)ctx;(void)data;
  return size;
}
bool voice_cue_generation_validate_profile(const uint8_t *data,size_t size,unsigned rate,unsigned channels,bool (*allowed)(void)) {
  voice_mp3_player_t *p=calloc(1,sizeof(*p));
  if(!p)return false;
  bool valid=voice_mp3_player_init(p,voice_mp3_decoder(),discard,NULL);
  size_t offset=0;
  while(valid&&offset<size) {
    if(allowed&&!allowed()) {valid=false;break;}
    size_t n=size-offset;
    if(n>512)n=512;
    size_t used=voice_mp3_player_feed(p,data+offset,n);
    if(p->failed||!used) {valid=false;break;}
    offset+=used;
#ifdef ESP_PLATFORM
    /* Startup preload also decodes every cue; yield without requiring Wi-Fi. */
    vTaskDelay(1);
#endif
  }
  if(valid)valid=voice_mp3_player_finish(p)&&p->pcm_samples<=(uint64_t)p->rate*6&&
    (!rate||p->rate==rate)&&(!channels||p->channels==channels);
  voice_mp3_player_close(p);
  free(p);
  return valid;
}
bool voice_cue_generation_validate(const uint8_t *data,size_t size,bool (*allowed)(void)) {
  return voice_cue_generation_validate_profile(data,size,0,0,allowed);
}
static bool write_file(const char *file,const uint8_t *data,size_t size) {
  char temp[272];
  int n=snprintf(temp,sizeof(temp),"%s.part",file);
  if(n<0||(size_t)n>=sizeof(temp))return false;
  FILE *f=fopen(temp,"wb");
  if(!f)return false;
  bool valid=fwrite(data,1,size,f)==size;
  if(fflush(f))valid=false;
  if(valid&&fsync(fileno(f)))valid=false;
  if(fclose(f))valid=false;
  if(!valid||rename(temp,file)) {unlink(temp);return false;}
  return true;
}
bool voice_cue_generation_write(voice_cue_store_t *s,const voice_cue_generation_t *g,unsigned i) {
  char file[256];
  if(!path(s,g->id,i,file)||!g->bank.slots[i].pcm||g->bank.slots[i].size!=g->size[i]||
     !hash_matches(s,g->bank.slots[i].pcm,g->size[i],g->sha[i]))return false;
  return write_file(file,g->bank.slots[i].pcm,g->size[i]);
}
bool voice_cue_generation_commit(voice_cue_store_t *s,const voice_cue_generation_t *g,const char *manifest) {
  if(!s||!g||!hex(g->id)||!manifest||strlen(manifest)>=VOICE_CUE_MANIFEST_MAX)return false;
  /* The only active pointer is the durable manifest. All immutable cue files
   * are flushed first; power failure leaves either the old or the new set. */
  for(unsigned i=0;i<VOICE_CUE_COUNT;i++) {
    char file[256];struct stat st;
    if(!path(s,g->id,i,file)||stat(file,&st)||st.st_size!=(off_t)g->size[i])return false;
  }
  char file[256];snprintf(file,sizeof(file),"%s/active-generation.json",s->root);
  return write_file(file,(const uint8_t*)manifest,strlen(manifest));
}
bool voice_cue_generation_load(voice_cue_store_t *s,voice_cue_generation_t *g) {
  if(!s||!g)return false;
  char file[256];snprintf(file,sizeof(file),"%s/active-generation.json",s->root);
  FILE *f=fopen(file,"rb");
  if(!f)return false;
  char *manifest=malloc(VOICE_CUE_MANIFEST_MAX);
  if(!manifest) {fclose(f);return false;}
  size_t n=fread(manifest,1,VOICE_CUE_MANIFEST_MAX-1,f);
  bool valid=!ferror(f)&&feof(f);
  fclose(f);manifest[n]=0;
  if(valid)valid=voice_cue_generation_parse(manifest,g);
  free(manifest);
  for(unsigned i=0;valid&&i<VOICE_CUE_COUNT;i++) {
    if(!path(s,g->id,i,file)) {valid=false;break;}
    f=fopen(file,"rb");
    uint8_t *data=alloc(g->size[i]);
    if(!f||!data) {if(f)fclose(f);free(data);valid=false;break;}
    n=fread(data,1,g->size[i],f);
    valid=n==g->size[i]&&fgetc(f)==EOF&&!ferror(f);
    fclose(f);
    if(valid)valid=hash_matches(s,data,n,g->sha[i])&&voice_cue_generation_validate_profile(data,n,g->rate[i],g->channels[i],NULL);
    if(!valid) {free(data);break;}
    g->bank.slots[i]=(voice_cue_slot_t){.pcm=data,.size=n,.codec=VOICE_CUE_MP3};
  }
  if(!valid)voice_cue_generation_free(g);
  return valid;
}
bool voice_cue_generation_has_space(voice_cue_store_t *s,const voice_cue_generation_t *g) {
  if(!s||!g||!hex(g->id))return false;
  DIR *d=opendir(s->root);
  if(!d)return false;
  uint64_t total=VOICE_CUE_MANIFEST_MAX*2;
  size_t largest=0;
  for(unsigned i=0;i<VOICE_CUE_COUNT;i++) {
    total+=g->size[i];
    if(g->size[i]>largest)largest=g->size[i];
  }
  /* Replacing a completed candidate still needs one durable temp alongside it. */
  total+=largest;
  struct dirent *entry;
  while((entry=readdir(d))) {
    if(!strcmp(entry->d_name,".")||!strcmp(entry->d_name,".."))continue;
    /* Existing candidate files are included in the candidate's total above. */
    if(!strncmp(entry->d_name,g->id,64)&&entry->d_name[64]=='_')continue;
    char file[320];struct stat st;
    int n=snprintf(file,sizeof(file),"%s/%s",s->root,entry->d_name);
    if(n<=0||(size_t)n>=sizeof(file)||stat(file,&st)||!S_ISREG(st.st_mode)||st.st_size<0) {
      closedir(d);return false;
    }
    total+=(uint64_t)st.st_size;
  }
  closedir(d);
  return total<=s->limit;
}
void voice_cue_generation_clean(voice_cue_store_t *s,const char *active) {
  if(!s||!active||(*active&&!hex(active)))return;
  DIR *d=opendir(s->root);
  if(!d)return;
  struct dirent *entry;
  while((entry=readdir(d))) {
    size_t n=strlen(entry->d_name);
    if(n<69||entry->d_name[64]!='_')continue;
    char id[65];memcpy(id,entry->d_name,64);id[64]=0;
    if(!hex(id))continue;
    for(unsigned i=0;i<VOICE_CUE_COUNT;i++) {
      char expected[128];snprintf(expected,sizeof(expected),"%s_%s.mp3",id,voice_cue_name((voice_cue_name_t)i));
      bool complete=!strcmp(entry->d_name,expected);
      char temp[144];snprintf(temp,sizeof(temp),"%s.part",expected);
      bool staging=!strcmp(entry->d_name,temp);
      if(!staging&&(!complete||!strncmp(id,active,64)))continue;
      char file[400];
      int written=snprintf(file,sizeof(file),"%s/%s",s->root,entry->d_name);
      if(written>0&&(size_t)written<sizeof(file))unlink(file);
    }
  }
  closedir(d);
}
