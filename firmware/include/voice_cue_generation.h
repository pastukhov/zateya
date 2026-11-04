#ifndef VOICE_CUE_GENERATION_H
#define VOICE_CUE_GENERATION_H
#include "voice_cue_cache.h"
#include "voice_cue_store.h"
#define VOICE_CUE_MANIFEST_MAX 8192
/* Complete immutable generation. Caller swaps one bank under its mutex. */
typedef struct {
 char id[65];
 char sha[VOICE_CUE_COUNT][65];
 size_t size[VOICE_CUE_COUNT];
 unsigned rate[VOICE_CUE_COUNT],channels[VOICE_CUE_COUNT];
 voice_cue_bank_t bank;
} voice_cue_generation_t;
void voice_cue_generation_free(voice_cue_generation_t *);
bool voice_cue_generation_parse(const char *,voice_cue_generation_t *);
bool voice_cue_generation_load(voice_cue_store_t *,voice_cue_generation_t *);
bool voice_cue_generation_write(voice_cue_store_t *,const voice_cue_generation_t *,unsigned);
bool voice_cue_generation_commit(voice_cue_store_t *,const voice_cue_generation_t *,const char *);
bool voice_cue_generation_has_space(voice_cue_store_t *,const voice_cue_generation_t *);
void voice_cue_generation_clean(voice_cue_store_t *,const char *);
bool voice_cue_generation_validate_profile(const uint8_t *,size_t,unsigned,unsigned,bool (*)(void));
bool voice_cue_generation_validate(const uint8_t *,size_t,bool (*)(void));
#endif
