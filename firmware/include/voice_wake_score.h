#ifndef VOICE_WAKE_SCORE_H
#define VOICE_WAKE_SCORE_H
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct { uint8_t values[5]; unsigned index, warmup; } voice_wake_score_t;
void voice_wake_score_reset(voice_wake_score_t *s);
bool voice_wake_score_feed(voice_wake_score_t *s, uint8_t probability);
#ifdef __cplusplus
}
#endif
#endif
