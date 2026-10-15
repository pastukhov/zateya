#ifndef VOICE_WAKE_DETECTOR_H
#define VOICE_WAKE_DETECTOR_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
bool voice_wake_detector_start(void);
bool voice_wake_detector_ready(void);
void voice_wake_detector_reset(void);
void voice_wake_detector_feed(const uint8_t *pcm, size_t bytes);
bool voice_wake_detector_detected(void);
#ifdef __cplusplus
}
#endif
#endif
