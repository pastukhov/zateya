#ifndef VOICE_VAD_H
#define VOICE_VAD_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
bool voice_vad_reset(void);
/* Require 200 ms consecutive speech after reset; then report raw VAD
 * activity for pause detection. Failure fails closed. */
bool voice_vad_feed(const uint8_t *pcm,size_t bytes);
bool voice_vad_ready(void);
#endif
