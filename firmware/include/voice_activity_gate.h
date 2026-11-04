#ifndef VOICE_ACTIVITY_GATE_H
#define VOICE_ACTIVITY_GATE_H
#include <stdbool.h>
#include <stdatomic.h>
typedef enum {VOICE_ACTIVITY_IDLE,VOICE_ACTIVITY_VOICE,VOICE_ACTIVITY_OTA,VOICE_ACTIVITY_STORAGE} voice_activity_t;
bool voice_activity_claim(atomic_int *activity,voice_activity_t owner);
bool voice_activity_release(atomic_int *activity,voice_activity_t owner,bool boot_confirmed);
#endif
