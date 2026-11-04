#include "voice_cue_store.h"
#ifdef ESP_PLATFORM
#include "esp_flash.h"
#include "esp_partition.h"
#include "esp_littlefs.h"
#include "esp_log.h"
#include "mbedtls/sha256.h"
#include <string.h>
static voice_cue_store_t store;
static bool attempted,ready;
static const esp_partition_t *partition;
static bool hash_pcm(const uint8_t *pcm,size_t n,uint8_t out[32]){return mbedtls_sha256(pcm,n,out,0)==0;}
static bool erased(void){
 uint8_t bytes[1024];
 for(size_t offset=0;offset<VOICE_CUE_STORE_SIZE;offset+=sizeof(bytes)){
  if(esp_partition_read(partition,offset,bytes,sizeof(bytes))!=ESP_OK)return false;
  for(size_t i=0;i<sizeof(bytes);i++)if(bytes[i]!=0xff)return false;
 }
 return true;
}
voice_cue_store_t *voice_cue_store_mount(void){
 if(attempted)return ready?&store:NULL;
 attempted=true;uint32_t size=0;
 if(esp_flash_get_physical_size(NULL,&size)!=ESP_OK){ESP_LOGW("cue_store","disabled: flash size");return NULL;}
 voice_cue_partition_t parts[16];size_t count=0;
 esp_partition_iterator_t it=esp_partition_find(ESP_PARTITION_TYPE_ANY,ESP_PARTITION_SUBTYPE_ANY,NULL);
 while(it){
  const esp_partition_t *p=esp_partition_get(it);
  if(count==16){esp_partition_iterator_release(it);ESP_LOGW("cue_store","disabled: partition count");return NULL;}
  parts[count++]=(voice_cue_partition_t){p->type,p->subtype,p->address,p->size,p->encrypted,p->readonly};
  it=esp_partition_next(it);
 }
 if(!voice_cue_store_layout_valid(size,parts,count)){ESP_LOGW("cue_store","disabled: unsupported layout");return NULL;}
 if(esp_partition_register_external(NULL,VOICE_CUE_STORE_OFFSET,VOICE_CUE_STORE_SIZE,"voice_cues",
       ESP_PARTITION_TYPE_DATA,ESP_PARTITION_SUBTYPE_DATA_LITTLEFS,&partition)!=ESP_OK){
  ESP_LOGW("cue_store","disabled: registration");return NULL;
 }
 const esp_vfs_littlefs_conf_t config={.base_path="/voice_cues",.partition_label=NULL,.partition=partition,
   .format_if_mount_failed=false,.read_only=false,.dont_mount=false,.grow_on_mount=false};
 esp_err_t error=esp_vfs_littlefs_register(&config);
 if(error!=ESP_OK){
  /* Never format a corrupt/nonblank or unreadable tail. Only a fully erased
   * range permits the first filesystem creation, under the boot voice guard. */
  if(!erased() || esp_littlefs_format_partition(partition)!=ESP_OK || esp_vfs_littlefs_register(&config)!=ESP_OK){
   ESP_LOGW("cue_store","disabled: mount; nonblank data retained");return NULL;
  }
 }
 ready=voice_cue_store_init(&store,"/voice_cues",hash_pcm);
 if(ready){voice_cue_store_clean_temps(&store);ESP_LOGI("cue_store","persistent cache mounted");}
 return ready?&store:NULL;
}
#else
voice_cue_store_t *voice_cue_store_mount(void){return NULL;}
#endif
