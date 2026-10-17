#include "voice_cue_cache.h"
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

static char base[192],device[32],auth[200],current_sha[65];
static SemaphoreHandle_t mutex;
static voice_cue_slot_t slot;
static atomic_bool idle;
static bool allowed(void) {
 return atomic_load(&idle) && !voice_ota_busy() && board_sticks3_usb_powered() &&
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
   int got=esp_http_client_read(c,(char*)out+used,(int)((size_t)length-used));
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
static void refresh(void) {
 uint8_t manifest[1024];int n=fetch("/api/device/cues/listening",manifest,sizeof(manifest)-1);
 if(n<=0)return;
 manifest[n]=0;
 cJSON *o=cJSON_Parse((char*)manifest);if(!o)return;
 int size,rate,channels,bits;char sha[65];
 cJSON *digest=cJSON_GetObjectItemCaseSensitive(o,"sha256");
 bool valid=integer(o,"size",&size)&&integer(o,"sample_rate",&rate)&&
 integer(o,"channels",&channels)&&integer(o,"bits_per_sample",&bits)&&cJSON_IsString(digest)&&
 voice_cue_metadata_valid((size_t)size,rate,channels,bits,digest->valuestring);
 if(valid)memcpy(sha,digest->valuestring,65);
 cJSON_Delete(o);
 if(!valid || strcmp(sha,current_sha)==0)return;
 uint8_t *pcm=heap_caps_malloc((size_t)size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!pcm)return;
 char path[128];snprintf(path,sizeof(path),"/api/device/cues/audio/%s.pcm",sha);
 n=fetch(path,pcm,(size_t)size);
 uint8_t digest_bytes[32];char actual[65];
 if(n!=size || mbedtls_sha256(pcm,(size_t)size,digest_bytes,0)!=0){free(pcm);return;}
 for(unsigned i=0;i<32;i++)snprintf(actual+i*2,3,"%02x",digest_bytes[i]);
 if(strcmp(sha,actual)!=0 || !allowed()){free(pcm);return;}
 uint8_t *old=NULL;
 xSemaphoreTake(mutex,portMAX_DELAY);
 bool published=voice_cue_slot_publish(&slot,pcm,(size_t)size,&old);
 xSemaphoreGive(mutex);
 if(published){memcpy(current_sha,sha,65);free(old);ESP_LOGI("cue_cache","Listening cue cached: %d bytes",size);}
 else free(pcm);
}
static void worker(void *arg) {
 (void)arg;bool attempted=false;int64_t previous=0;
 for(;;){int64_t now=esp_timer_get_time();
  if(allowed()&&(!attempted||now-previous>=60000000)){attempted=true;previous=now;refresh();}
  vTaskDelay(pdMS_TO_TICKS(1000));
 }
}
bool voice_cue_cache_start(const char *gateway,const char *id,const char *token) {
 if(mutex || !gateway || !id || !token || !*gateway || !*id || !*token)return false;
 size_t len=strlen(gateway);while(len&&gateway[len-1]=='/')len--;
 int a=snprintf(base,sizeof(base),"%.*s",(int)len,gateway);
 int b=snprintf(device,sizeof(device),"%s",id);int c=snprintf(auth,sizeof(auth),"Bearer %s",token);
 if(a<=0||a>=sizeof(base)||b<=0||b>=sizeof(device)||c<=0||c>=sizeof(auth))return false;
 mutex=xSemaphoreCreateMutex();if(!mutex)return false;
 if(xTaskCreate(worker,"cue_cache",8192,NULL,2,NULL)==pdPASS)return true;
 vSemaphoreDelete(mutex);mutex=NULL;return false;
}
void voice_cue_cache_set_idle(bool value){atomic_store(&idle,value);}
bool voice_cue_cache_ready(void) {
 if(!mutex)return false;
 xSemaphoreTake(mutex,portMAX_DELAY);
 bool ready=slot.pcm!=NULL;
 xSemaphoreGive(mutex);
 return ready;
}
const uint8_t *voice_cue_cache_acquire(size_t *size) {
 *size=0;if(!mutex)return NULL;xSemaphoreTake(mutex,portMAX_DELAY);
 const uint8_t *pcm=voice_cue_slot_acquire(&slot,size);xSemaphoreGive(mutex);return pcm;
}
void voice_cue_cache_release(void){if(mutex){xSemaphoreTake(mutex,portMAX_DELAY);voice_cue_slot_release(&slot);xSemaphoreGive(mutex);}}
#else
bool voice_cue_cache_start(const char*g,const char*d,const char*t){(void)g;(void)d;(void)t;return false;}
void voice_cue_cache_set_idle(bool idle){(void)idle;}
bool voice_cue_cache_ready(void){return false;}
const uint8_t *voice_cue_cache_acquire(size_t *size){*size=0;return NULL;}
void voice_cue_cache_release(void){}
#endif
