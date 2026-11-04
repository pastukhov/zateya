#ifndef VOICE_CUE_CACHE_H
#define VOICE_CUE_CACHE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define VOICE_CUE_MAX_BYTES 240000
typedef enum {VOICE_CUE_LISTENING,VOICE_CUE_PROCESSING,VOICE_CUE_OFFLINE,
 VOICE_CUE_READY,VOICE_CUE_DONE,VOICE_CUE_CANCELLED,VOICE_CUE_TRANSCRIBING,
 VOICE_CUE_THINKING,VOICE_CUE_SYNTHESIZING,VOICE_CUE_ANSWERING,VOICE_CUE_ERROR,
 VOICE_CUE_TIMEOUT,VOICE_CUE_RECOGNITION_ERROR,VOICE_CUE_SYNTHESIS_ERROR,VOICE_CUE_COUNT} voice_cue_name_t;
/* Pure slot policy; caller serializes access and owns buffer allocation/free. */
typedef struct {uint8_t *pcm;size_t size;unsigned readers;} voice_cue_slot_t;
bool voice_cue_metadata_valid(size_t size, int rate, int channels, int bits, const char *sha);
bool voice_cue_slot_publish(voice_cue_slot_t *slot, uint8_t *pcm, size_t size, uint8_t **old);
const uint8_t *voice_cue_slot_acquire(voice_cue_slot_t *slot, size_t *size);
void voice_cue_slot_release(voice_cue_slot_t *slot);
typedef struct {voice_cue_slot_t slots[VOICE_CUE_COUNT];} voice_cue_bank_t;
bool voice_cue_bank_publish(voice_cue_bank_t *bank,voice_cue_name_t name,uint8_t *pcm,size_t size,uint8_t **old);
const uint8_t *voice_cue_bank_acquire(voice_cue_bank_t *bank,voice_cue_name_t name,size_t *size);
void voice_cue_bank_release(voice_cue_bank_t *bank,voice_cue_name_t name);
const uint8_t *voice_cue_fallback(size_t *size);
const uint8_t *voice_cue_fallback_named(voice_cue_name_t name,size_t *size);
const char *voice_cue_name(voice_cue_name_t name);
bool voice_cue_cache_ready_named(voice_cue_name_t name);
const uint8_t *voice_cue_cache_acquire_named(voice_cue_name_t name,size_t *size);
void voice_cue_cache_release_named(voice_cue_name_t name);
/* ESP worker. An acquired buffer stays valid until release. */
bool voice_cue_cache_start(const char *gateway, const char *device, const char *token);
void voice_cue_cache_set_idle(bool idle);
bool voice_cue_cache_ready(void);
const uint8_t *voice_cue_cache_acquire(size_t *size);
void voice_cue_cache_release(void);
#endif
