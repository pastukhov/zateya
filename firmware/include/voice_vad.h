#ifndef VOICE_VAD_H
#define VOICE_VAD_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
bool voice_vad_reset(void);
/* Any 10 ms frame with speech sets true; failure fails closed. */
bool voice_vad_feed(const uint8_t *pcm,size_t bytes);
bool voice_vad_ready(void);
#endif
