#ifndef VOICE_CUE_STORE_H
#define VOICE_CUE_STORE_H
#include "voice_cue_cache.h"
#define VOICE_CUE_STORE_OFFSET 0x620000U
#define VOICE_CUE_STORE_SIZE 0x1e0000U
#define VOICE_CUE_STORE_LIMIT (1536U*1024U)
#define VOICE_CUE_RECORD_HEADER 128U
typedef struct {uint8_t type,subtype;uint32_t offset,size;bool encrypted,readonly;} voice_cue_partition_t;
typedef struct {size_t size;char sha[65];} voice_cue_record_t;
typedef bool (*voice_cue_hash_fn)(const uint8_t *,size_t,uint8_t digest[32]);
typedef struct {char root[128];voice_cue_hash_fn hash;size_t limit;} voice_cue_store_t;
typedef enum {VOICE_CUE_STORE_FAILED,VOICE_CUE_STORE_UNCHANGED,VOICE_CUE_STORE_WRITTEN} voice_cue_store_result_t;
bool voice_cue_store_layout_valid(uint32_t flash_size,const voice_cue_partition_t *parts,size_t count);
bool voice_cue_record_encode(uint8_t header[VOICE_CUE_RECORD_HEADER],voice_cue_name_t name,size_t size,const char *sha);
bool voice_cue_record_decode(const uint8_t header[VOICE_CUE_RECORD_HEADER],voice_cue_name_t name,size_t file_size,voice_cue_record_t *record);
bool voice_cue_record_verify(const uint8_t header[VOICE_CUE_RECORD_HEADER],const uint8_t *pcm,size_t size,voice_cue_name_t name,voice_cue_hash_fn hash);
bool voice_cue_store_init(voice_cue_store_t *store,const char *root,voice_cue_hash_fn hash);
bool voice_cue_store_info(voice_cue_store_t *store,voice_cue_name_t name,voice_cue_record_t *record);
bool voice_cue_store_load(voice_cue_store_t *store,voice_cue_name_t name,uint8_t *pcm,size_t capacity,voice_cue_record_t *record);
voice_cue_store_result_t voice_cue_store_put(voice_cue_store_t *store,voice_cue_name_t name,const uint8_t *pcm,size_t size,const char *sha);
void voice_cue_store_clean_temps(voice_cue_store_t *store);
/* ESP startup only, under the boot activity guard. NULL on unsupported layout. */
voice_cue_store_t *voice_cue_store_mount(void);
#endif
