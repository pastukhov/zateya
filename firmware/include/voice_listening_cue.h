#ifndef VOICE_LISTENING_CUE_H
#define VOICE_LISTENING_CUE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef enum { CUE_DONE, CUE_BUSY, CUE_ERROR } voice_cue_status_t;
/* Zero-initialize before first use. Caller owns exclusive access to audio. */
typedef struct {
 const uint8_t *pcm;
 size_t size, position;
 uint32_t started_ms;
 voice_cue_status_t status;
} voice_listening_cue_t;
bool voice_listening_cue_start(voice_listening_cue_t *c, const uint8_t *pcm,
                              size_t size, uint32_t now);
voice_cue_status_t voice_listening_cue_tick(voice_listening_cue_t *c, uint32_t now);
void voice_listening_cue_cancel(voice_listening_cue_t *c);
#endif
