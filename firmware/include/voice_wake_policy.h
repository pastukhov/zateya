#ifndef VOICE_WAKE_POLICY_H
#define VOICE_WAKE_POLICY_H
#include <stdbool.h>
#include <stdint.h>
#include "voice_button_mode.h"
typedef enum { WAKE_ARMED, WAKE_CUE, WAKE_SETTLE, WAKE_WAIT_SPEECH,
               WAKE_RECORDING, WAKE_DONE, WAKE_FAILED } voice_wake_state_t;
typedef enum { WAKE_NONE, WAKE_START_RECORD, WAKE_FINISH, WAKE_CANCEL } voice_wake_event_t;
typedef struct {
  voice_wake_state_t state;
  bool manual_hold;
  uint32_t cue_end_ms, started_ms, last_speech_ms, pause_ms, max_ms;
} voice_wake_t;
void voice_wake_init(voice_wake_t *w, uint32_t pause_ms, uint32_t max_ms);
/* Snapshot manual mode at capture start. Wake/follow-up pass manual=false. */
void voice_wake_capture_init(voice_wake_t *w, uint32_t pause_ms, uint32_t max_ms,
                             bool manual, voice_button_mode_t mode);
bool voice_wake_button_finish(const voice_wake_t *w, bool pressed, bool released);
bool voice_wake_activate(voice_wake_t *w, bool eligible, uint32_t now);
void voice_wake_cue_done(voice_wake_t *w, uint32_t now, bool success);
voice_wake_event_t voice_wake_tick(voice_wake_t *w, bool eligible,
                                 uint32_t now, bool speech, bool finish);
#endif
