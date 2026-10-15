#include "voice_wake_policy.h"

void voice_wake_init(voice_wake_t *w, uint32_t pause_ms, uint32_t max_ms) {
  *w = (voice_wake_t){.state = WAKE_ARMED,
    .pause_ms = pause_ms < 1000 ? 1000 : pause_ms > 10000 ? 10000 : pause_ms,
    .max_ms = max_ms ? max_ms : 600000};
}
bool voice_wake_activate(voice_wake_t *w, bool eligible, uint32_t now) {
  if (!eligible || w->state != WAKE_ARMED) return false;
  w->state = WAKE_CUE;
  w->started_ms = now;
  return true;
}
void voice_wake_cue_done(voice_wake_t *w, uint32_t now, bool success) {
  if (w->state != WAKE_CUE) return;
  w->state = success ? WAKE_SETTLE : WAKE_FAILED;
  w->cue_end_ms = now;
}
voice_wake_event_t voice_wake_tick(voice_wake_t *w, bool eligible,
                                 uint32_t now, bool speech, bool finish) {
  if (w->state == WAKE_ARMED || w->state == WAKE_DONE) return WAKE_NONE;
  if (w->state == WAKE_FAILED ||
      (!eligible && w->state != WAKE_RECORDING)) {
    w->state = WAKE_DONE;
    return WAKE_CANCEL;
  }
  if (w->state == WAKE_CUE) {
    /* A stalled playback must not retain the microphone/OTA gate forever. */
    if ((uint32_t)(now - w->started_ms) >= 8000) {
      w->state = WAKE_DONE;
      return WAKE_CANCEL;
    }
    return WAKE_NONE;
  }
  if (w->state == WAKE_SETTLE) {
    if ((uint32_t)(now - w->cue_end_ms) < 150) return WAKE_NONE;
    w->started_ms = w->cue_end_ms + 150;
    w->state = WAKE_WAIT_SPEECH;
  }
  if (w->state == WAKE_WAIT_SPEECH) {
    if (finish || (uint32_t)(now - w->started_ms) >= 8000) {
      w->state = WAKE_DONE;
      return WAKE_CANCEL;
    }
    if (!speech) return WAKE_NONE;
    w->last_speech_ms = now;
    w->state = WAKE_RECORDING;
    return WAKE_START_RECORD;
  }
  if (speech) w->last_speech_ms = now;
  if (finish || (uint32_t)(now - w->started_ms) >= w->max_ms ||
      (uint32_t)(now - w->last_speech_ms) >= w->pause_ms) {
    w->state = WAKE_DONE;
    return WAKE_FINISH;
  }
  return WAKE_NONE;
}
