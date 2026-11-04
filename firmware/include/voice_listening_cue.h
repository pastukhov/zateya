#ifndef VOICE_LISTENING_CUE_H
#define VOICE_LISTENING_CUE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "voice_cue_opus.h"
typedef enum { CUE_DONE, CUE_BUSY, CUE_ERROR } voice_cue_status_t;
/* Zero-initialize before first use. Caller owns exclusive access to audio. */
typedef struct {
 const uint8_t *pcm;
 size_t size, position;
 uint32_t started_ms;
 voice_cue_status_t status;
 void (*release)(void *ctx);
 void *release_ctx;
 const voice_cue_decoder_t *decoder_ops;
 void *decoder;
 voice_cue_opus_t opus;
 size_t decoded_index,queued,queue_position;
 int16_t frame[480];
} voice_listening_cue_t;
bool voice_listening_cue_start(voice_listening_cue_t *c, const uint8_t *pcm,
                              size_t size, uint32_t now);
/* Takes ownership of one acquired PCM lease, even on rejected start. */
bool voice_listening_cue_start_lease(voice_listening_cue_t *c,const uint8_t *pcm,
                                    size_t size,uint32_t now,
                                    void (*release)(void *ctx),void *ctx);
bool voice_listening_cue_start_opus(voice_listening_cue_t *c,const uint8_t *data,size_t size,
                                   uint32_t now,const voice_cue_decoder_t *ops,
                                   void (*release)(void *ctx),void *ctx);
voice_cue_status_t voice_listening_cue_tick(voice_listening_cue_t *c, uint32_t now);
void voice_listening_cue_cancel(voice_listening_cue_t *c);
#endif
