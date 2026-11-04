#include "voice_cue_cache.h"
#include "voice_cue_store.h"
#include "voice_cue_opus.h"
#include "voice_cue_generation.h"
#ifdef ESP_PLATFORM
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board_sticks3.h"
#include "cJSON.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "mbedtls/sha256.h"
#include "voice_gateway_health.h"
#include "voice_ota.h"
#include "voice_tls.h"

static char base[192],device[32],auth[200],current_sha[VOICE_CUE_COUNT][65];
static SemaphoreHandle_t mutex;
static voice_cue_bank_t bank;
static atomic_bool idle;
static voice_cue_store_t *persistent;
static char active_generation[65];
static bool pending_disk[VOICE_CUE_COUNT];
static int64_t next_persist[VOICE_CUE_COUNT];
static char disk_sha[VOICE_CUE_COUNT][65];
static void preload(void){
 persistent=voice_cue_store_mount();if(!persistent)return;
 voice_cue_generation_t *generation=calloc(1,sizeof(*generation));
 if(generation && voice_cue_generation_load(persistent,generation)) {
  bank=generation->bank;
  memcpy(active_generation,generation->id,65);
  memcpy(current_sha,generation->sha,sizeof(current_sha));
  memset(&generation->bank,0,sizeof(generation->bank));
  free(generation);
  return;
 }
 free(generation);
 for(unsigned i=0;i<VOICE_CUE_COUNT;i++)for(int kind=VOICE_CUE_OPUS;kind>=VOICE_CUE_PCM16;kind--){
  voice_cue_record_t record;voice_cue_codec_t codec=(voice_cue_codec_t)kind;
  if(!voice_cue_store_info_codec(persistent,(voice_cue_name_t)i,codec,&record))continue;
  uint8_t *data=heap_caps_malloc(record.size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  if(!data)continue;
  if(!voice_cue_store_load_codec(persistent,(voice_cue_name_t)i,codec,data,record.size,&record)||
     (codec==VOICE_CUE_OPUS&&!voice_cue_opus_validate(data,record.size,NULL))){free(data);continue;}
  uint8_t *old=NULL;
  if(!voice_cue_bank_publish_codec(&bank,(voice_cue_name_t)i,data,record.size,codec,&old)){free(data);continue;}
  memcpy(current_sha[i],record.sha,65);memcpy(disk_sha[i],record.sha,65);free(old);
  ESP_LOGI("cue_cache","%s cue loaded offline: %u bytes codec %d",voice_cue_name((voice_cue_name_t)i),(unsigned)record.size,kind);
  break;
 }
}
static void persist(unsigned i,int64_t now){
 if(!persistent||!pending_disk[i]||now<next_persist[i])return;
 next_persist[i]=now+1000000;
 if(!atomic_load(&idle)||!voice_ota_storage_begin())return;
 /* Whole filesystem mutation has its own owner, never the app voice lease. */
 if(!atomic_load(&idle)){voice_ota_storage_end();return;}
 voice_cue_audio_t audio=voice_cue_cache_acquire_audio((voice_cue_name_t)i);bool acquired=audio.data!=NULL;
 if(!acquired){voice_ota_storage_end();return;}
 voice_cue_store_result_t result=voice_cue_store_put_codec(persistent,(voice_cue_name_t)i,audio.data,audio.size,current_sha[i],audio.codec);
 voice_cue_cache_release_named((voice_cue_name_t)i);voice_ota_storage_end();
 if(result!=VOICE_CUE_STORE_FAILED){
  memcpy(disk_sha[i],current_sha[i],65);pending_disk[i]=false;
  ESP_LOGI("cue_cache","%s cue persisted",voice_cue_name((voice_cue_name_t)i));
 }else{
  next_persist[i]=now+60000000;ESP_LOGW("cue_cache","persistent write deferred");
 }
}
static bool allowed(void) {
 return atomic_load(&idle) && !voice_ota_busy() &&
        board_sticks3_network_ready() && voice_gateway_health_status()==200;
}
/* Every fetch is bounded and redirects are forbidden (never forward credentials). */
static int fetch(const char *path,uint8_t *out,size_t cap) {
 char url[320];int n=snprintf(url,sizeof(url),"%s%s",base,path);
 if(n<0 || n>=sizeof(url) || !allowed())return -1;
 esp_http_client_config_t config={.url=url,
   .timeout_ms=1500,.disable_auto_redirect=true};
 esp_http_client_handle_t c=voice_tls_client_init(&config);if(!c)return -1;
 esp_http_client_set_header(c,"X-Device-Id",device);
 esp_http_client_set_header(c,"Authorization",auth);
 int result=-1;size_t used=0;int64_t start=esp_timer_get_time();
 if(esp_http_client_open(c,0)!=ESP_OK)goto done;
 int64_t length=esp_http_client_fetch_headers(c);
 if(esp_http_client_get_status_code(c)!=200 || length<=0 || length>(int64_t)cap)goto done;
 while(used<(size_t)length) {
   if(!allowed() || esp_timer_get_time()-start>10000000)goto done;
   size_t chunk=(size_t)length-used;
   if(chunk>4096)chunk=4096;
   int got=esp_http_client_read(c,(char*)out+used,(int)chunk);
   if(got<=0)goto done;
   used+=(size_t)got;
 }
 if(esp_http_client_is_complete_data_received(c))result=(int)used;
 done:esp_http_client_close(c);esp_http_client_cleanup(c);return result;
}
static bool integer(cJSON *o,const char *name,int *value) {
 cJSON *x=cJSON_GetObjectItemCaseSensitive(o,name);
 if(!cJSON_IsNumber(x) || x->valuedouble<0 || x->valuedouble>VOICE_CUE_MAX_BYTES || x->valuedouble!=x->valueint)return false;
 *value=x->valueint;return true;
}
static bool validation_allowed(void){vTaskDelay(1);return atomic_load(&idle);}
static void refresh(voice_cue_name_t name) {
 char manifest_path[96];
 snprintf(manifest_path,sizeof(manifest_path),"/api/device/cues/%s?codec=opus-v1",voice_cue_name(name));
 uint8_t manifest[1024];int n=fetch(manifest_path,manifest,sizeof(manifest)-1);
 if(n<=0)return;
 manifest[n]=0;
 cJSON *o=cJSON_Parse((char*)manifest);if(!o)return;
 int size,rate,channels,bits,samples,skip,frame,count,bitrate;char sha[65];
 cJSON *digest=cJSON_GetObjectItemCaseSensitive(o,"sha256");
 bool valid=integer(o,"size",&size)&&integer(o,"sample_rate",&rate)&&
 integer(o,"channels",&channels)&&integer(o,"bits_per_sample",&bits)&&cJSON_IsString(digest)&&
 size>=34&&size<=VOICE_OPUS_MAX_BYTES&&rate==24000&&channels==1&&bits==16&&
 cJSON_IsString(cJSON_GetObjectItemCaseSensitive(o,"codec"))&&
 !strcmp(cJSON_GetObjectItemCaseSensitive(o,"codec")->valuestring,"opus-v1")&&
 strlen(digest->valuestring)==64&&
 cJSON_IsString(cJSON_GetObjectItemCaseSensitive(o,"container"))&&
 !strcmp(cJSON_GetObjectItemCaseSensitive(o,"container")->valuestring,"vcopus1")&&
 integer(o,"samples",&samples)&&samples>0&&samples<=120000&&
 integer(o,"preskip",&skip)&&skip<=960&&integer(o,"frame_samples",&frame)&&frame==480&&
 integer(o,"packet_count",&count)&&count>0&&count<=252&&integer(o,"bitrate",&bitrate)&&bitrate==24000;
 if(valid)for(unsigned i=0;i<64;i++)if(!((digest->valuestring[i]>='0'&&digest->valuestring[i]<='9')||(digest->valuestring[i]>='a'&&digest->valuestring[i]<='f')))valid=false;
 if(valid)memcpy(sha,digest->valuestring,65);
 cJSON_Delete(o);
 if(!valid || strcmp(sha,current_sha[name])==0)return;
 uint8_t *pcm=heap_caps_malloc((size_t)size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!pcm)return;
 char path[128];snprintf(path,sizeof(path),"/api/device/cues/audio/%s.vop",sha);
 n=fetch(path,pcm,(size_t)size);
 uint8_t digest_bytes[32];char actual[65];
 if(n!=size || mbedtls_sha256(pcm,(size_t)size,digest_bytes,0)!=0){free(pcm);return;}
 for(unsigned i=0;i<32;i++)snprintf(actual+i*2,3,"%02x",digest_bytes[i]);
 voice_cue_opus_t parsed;
 if(strcmp(sha,actual)!=0 || !voice_cue_opus_parse(pcm,(size_t)size,&parsed)||parsed.samples!=(unsigned)samples||parsed.preskip!=(unsigned)skip||parsed.count!=(unsigned)count|| !allowed()){free(pcm);return;}
 /* Serialise decoder validation with voice/OTA, then publish only playable data. */
 if(!voice_ota_storage_begin()){free(pcm);return;}
 bool playable=atomic_load(&idle)&&voice_cue_opus_validate(pcm,(size_t)size,validation_allowed);
 if(!playable){voice_ota_storage_end();free(pcm);return;}
 uint8_t *old=NULL;
 xSemaphoreTake(mutex,portMAX_DELAY);
 bool published=allowed() && voice_cue_bank_publish_codec(&bank,name,pcm,(size_t)size,VOICE_CUE_OPUS,&old);
 xSemaphoreGive(mutex);voice_ota_storage_end();
 if(published){memcpy(current_sha[name],sha,65);
  pending_disk[name]=strcmp(disk_sha[name],sha)!=0;next_persist[name]=0;
  free(old);ESP_LOGI("cue_cache","%s cue cached: %d bytes",voice_cue_name(name),size);}
 else free(pcm);
}
static bool refresh_generation(void) {
 if(!persistent)return false;
 char *manifest=malloc(VOICE_CUE_MANIFEST_MAX);
 voice_cue_generation_t *generation=calloc(1,sizeof(*generation));
 if(!manifest||!generation) {free(manifest);free(generation);return false;}
 int n=fetch("/api/device/cues/generation",(uint8_t*)manifest,VOICE_CUE_MANIFEST_MAX-1);
 bool valid=n>0;
 if(valid) {manifest[n]=0;valid=voice_cue_generation_parse(manifest,generation);}
 if(valid&&!strcmp(generation->id,active_generation))goto done;
 if(valid) {
  valid=allowed()&&voice_ota_storage_begin();
  if(valid) {
   if(atomic_load(&idle))voice_cue_generation_clean(persistent,active_generation);
   valid=atomic_load(&idle)&&voice_cue_generation_has_space(persistent,generation);
   voice_ota_storage_end();
  }
 }
 for(unsigned i=0;valid&&i<VOICE_CUE_COUNT;i++) {
  char path[192];
  snprintf(path,sizeof(path),"/api/device/cues/mp3/%s/%s.mp3",generation->id,voice_cue_name((voice_cue_name_t)i));
  uint8_t *data=heap_caps_malloc(generation->size[i],MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  if(!data) {valid=false;break;}
  generation->bank.slots[i]=(voice_cue_slot_t){.pcm=data,.size=generation->size[i],.codec=VOICE_CUE_MP3};
  n=fetch(path,data,generation->size[i]);
  uint8_t digest[32];char actual[65];
  valid=n==(int)generation->size[i]&&mbedtls_sha256(data,generation->size[i],digest,0)==0;
  if(valid) {
   for(unsigned j=0;j<32;j++)snprintf(actual+j*2,3,"%02x",digest[j]);
   valid=!strcmp(actual,generation->sha[i]);
  }
  if(valid) {
   valid=allowed()&&voice_ota_storage_begin();
   if(valid) {
    valid=atomic_load(&idle)&&voice_cue_generation_validate_profile(data,generation->size[i],generation->rate[i],generation->channels[i],validation_allowed)&&
      atomic_load(&idle)&&voice_cue_generation_write(persistent,generation,i);
    voice_ota_storage_end();
   }
  }
 }
 if(valid) {
  valid=allowed()&&voice_ota_storage_begin();
  if(valid) {
   xSemaphoreTake(mutex,portMAX_DELAY);
   valid=allowed();
   for(unsigned i=0;valid&&i<VOICE_CUE_COUNT;i++)if(bank.slots[i].readers)valid=false;
   if(valid)valid=voice_cue_generation_commit(persistent,generation,manifest);
   if(valid) {
    voice_cue_bank_t old=bank;
    bank=generation->bank;
    generation->bank=old;
    memcpy(active_generation,generation->id,65);
    memcpy(current_sha,generation->sha,sizeof(current_sha));
    memset(pending_disk,0,sizeof(pending_disk));
   }
   xSemaphoreGive(mutex);
   if(valid)voice_cue_generation_clean(persistent,active_generation);
   voice_ota_storage_end();
  }
 }
 done:
 if(!valid&&allowed())ESP_LOGW("cue_cache","complete MP3 generation update deferred; previous set retained");
 voice_cue_generation_free(generation);
 free(generation);free(manifest);
 return valid;
}

static void worker(void *arg) {
 (void)arg;bool attempted[VOICE_CUE_COUNT]={0};int64_t previous[VOICE_CUE_COUNT]={0};
 int64_t next_generation=0;
 for(;;){
  int64_t current=esp_timer_get_time();
  if(allowed()&&current>=next_generation) {
   next_generation=current+60000000;
   (void)refresh_generation();
  }
  if(active_generation[0]) {vTaskDelay(pdMS_TO_TICKS(1000));continue;}
  for(unsigned i=0;i<VOICE_CUE_COUNT && atomic_load(&idle) && !voice_ota_busy();i++){
   int64_t now=esp_timer_get_time();
   if(allowed() && (!attempted[i] || now-previous[i]>=60000000)){
    attempted[i]=true;previous[i]=now;refresh((voice_cue_name_t)i);
   }
   persist(i,esp_timer_get_time());
  }
  vTaskDelay(pdMS_TO_TICKS(1000));
 }
}
bool voice_cue_cache_start(const char *gateway,const char *id,const char *token) {
 if(mutex)return false;
 mutex=xSemaphoreCreateMutex();if(!mutex)return false;
 /* Boot guard still owns flash, before OTA worker/user capture. Local cache
  * deliberately does not depend on configuration or network readiness. */
 preload();
 if(!gateway || !id || !token || !*gateway || !*id || !*token)return false;
 size_t len=strlen(gateway);while(len&&gateway[len-1]=='/')len--;
 int a=snprintf(base,sizeof(base),"%.*s",(int)len,gateway);
 int b=snprintf(device,sizeof(device),"%s",id);int c=snprintf(auth,sizeof(auth),"Bearer %s",token);
 if(a<=0||a>=sizeof(base)||b<=0||b>=sizeof(device)||c<=0||c>=sizeof(auth))return false;
 if(xTaskCreate(worker,"cue_cache",24576,NULL,2,NULL)==pdPASS)return true;
 return false; /* retain preloaded bank even if networking task cannot start */
}
bool voice_cue_cache_generation(char generation[65]) {
 generation[0]=0;
 if(!mutex)return false;
 xSemaphoreTake(mutex,portMAX_DELAY);
 memcpy(generation,active_generation,65);
 xSemaphoreGive(mutex);
 return generation[0]!=0;
}
void voice_cue_cache_set_idle(bool value){atomic_store(&idle,value);}
bool voice_cue_cache_ready_named(voice_cue_name_t name) {
 if(!mutex || !voice_cue_name(name))return false;
 xSemaphoreTake(mutex,portMAX_DELAY);
 bool ready=bank.slots[name].pcm!=NULL;
 xSemaphoreGive(mutex);
 return ready;
}
const uint8_t *voice_cue_cache_acquire_named(voice_cue_name_t name,size_t *size) {
 *size=0;if(!mutex || !voice_cue_name(name))return NULL;
 xSemaphoreTake(mutex,portMAX_DELAY);
 const uint8_t *pcm=voice_cue_bank_acquire(&bank,name,size);
 xSemaphoreGive(mutex);return pcm;
}
voice_cue_audio_t voice_cue_cache_acquire_audio(voice_cue_name_t name){
 voice_cue_audio_t audio={0};if(!mutex||!voice_cue_name(name))return audio;
 xSemaphoreTake(mutex,portMAX_DELAY);audio=voice_cue_bank_acquire_audio(&bank,name);xSemaphoreGive(mutex);return audio;
}
void voice_cue_cache_release_named(voice_cue_name_t name){
 if(mutex && voice_cue_name(name)){
  xSemaphoreTake(mutex,portMAX_DELAY);voice_cue_bank_release(&bank,name);xSemaphoreGive(mutex);
 }
}
#else
bool voice_cue_cache_generation(char generation[65]){generation[0]=0;return false;}
voice_cue_audio_t voice_cue_cache_acquire_audio(voice_cue_name_t n){(void)n;return (voice_cue_audio_t){0};}
bool voice_cue_cache_start(const char*g,const char*d,const char*t){(void)g;(void)d;(void)t;return false;}
void voice_cue_cache_set_idle(bool idle){(void)idle;}
bool voice_cue_cache_ready_named(voice_cue_name_t name){(void)name;return false;}
const uint8_t *voice_cue_cache_acquire_named(voice_cue_name_t name,size_t *size){(void)name;*size=0;return NULL;}
void voice_cue_cache_release_named(voice_cue_name_t name){(void)name;}
#endif
/* Original listening-only API remains available to existing callers. */
bool voice_cue_cache_ready(void){return voice_cue_cache_ready_named(VOICE_CUE_LISTENING);}
const uint8_t *voice_cue_cache_acquire(size_t *size){return voice_cue_cache_acquire_named(VOICE_CUE_LISTENING,size);}
void voice_cue_cache_release(void){voice_cue_cache_release_named(VOICE_CUE_LISTENING);}
