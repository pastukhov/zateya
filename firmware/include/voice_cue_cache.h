#ifndef VOICE_CUE_CACHE_H
#define VOICE_CUE_CACHE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define VOICE_CUE_MAX_BYTES 240000
/* Pure slot policy; caller serializes access and owns buffer allocation/free. */
typedef struct {uint8_t *pcm;size_t size;unsigned readers;} voice_cue_slot_t;
bool voice_cue_metadata_valid(size_t size, int rate, int channels, int bits, const char *sha);
bool voice_cue_slot_publish(voice_cue_slot_t *slot, uint8_t *pcm, size_t size, uint8_t **old);
const uint8_t *voice_cue_slot_acquire(voice_cue_slot_t *slot, size_t *size);
void voice_cue_slot_release(voice_cue_slot_t *slot);
/* ESP worker. An acquired buffer stays valid until release. */
bool voice_cue_cache_start(const char *gateway, const char *device, const char *token);
void voice_cue_cache_set_idle(bool idle);
bool voice_cue_cache_ready(void);
const uint8_t *voice_cue_cache_acquire(size_t *size);
void voice_cue_cache_release(void);
#endif
