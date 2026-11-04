#ifndef VOICE_STATIC_CUES_H
#define VOICE_STATIC_CUES_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef enum {VOICE_CUE_LISTENING,VOICE_CUE_PROCESSING,VOICE_CUE_OFFLINE} voice_static_cue_t;
bool voice_static_cue_valid(const uint8_t *pcm,size_t size,uint32_t crc);
/* Immutable embedded flash, no network/cache lease. Invalid assets return
 * a short built-in signal; the screen still identifies the current state. */
const uint8_t *voice_static_cue_get(voice_static_cue_t name,size_t *size);
#endif
