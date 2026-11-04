#ifndef VOICE_FEEDBACK_POLICY_H
#define VOICE_FEEDBACK_POLICY_H
#include "voice_cue_cache.h"
#include "voice_turn_client.h"
typedef enum {VOICE_CAPTURE_UNAVAILABLE,VOICE_CAPTURE_STARTED,VOICE_CAPTURE_RETRY} voice_capture_start_t;
voice_capture_start_t voice_feedback_capture_result(bool eligible,bool acquired);
typedef enum {FEEDBACK_NONE,FEEDBACK_READY,FEEDBACK_CAPTURE,FEEDBACK_PROCESSING,
 FEEDBACK_TRANSCRIBING,FEEDBACK_THINKING,FEEDBACK_SYNTHESIZING,FEEDBACK_ANSWERING,
 FEEDBACK_DONE,FEEDBACK_CANCELLED,FEEDBACK_ERROR} voice_feedback_event_t;
typedef struct {
 voice_feedback_event_t last;
 voice_cue_name_t routine,error;
 bool routine_pending,error_pending,stage_open,manual_pending,manual_hold,gate_owned;
} voice_feedback_t;
bool voice_feedback_claim_gate(voice_feedback_t *p,bool (*acquire)(void *),void *ctx);
void voice_feedback_release_gate(voice_feedback_t *p,bool (*release)(void *),void *ctx);
bool voice_feedback_cancel_complete(bool requested,bool worker_active,bool storage_failed);
void voice_feedback_init(voice_feedback_t *p);
/* Main boot only, before OTA worker: activity starts as the application lease. */
void voice_feedback_boot_init(voice_feedback_t *p);
void voice_feedback_event(voice_feedback_t *p,voice_feedback_event_t event,voice_turn_error_t error,bool followup);
void voice_feedback_stage(voice_feedback_t *p,voice_turn_status_t stage);
bool voice_feedback_pending(const voice_feedback_t *p);
bool voice_feedback_error_pending(const voice_feedback_t *p);
bool voice_feedback_peek(const voice_feedback_t *p,bool owner_safe,voice_cue_name_t *cue);
void voice_feedback_started(voice_feedback_t *p,voice_cue_name_t cue);
void voice_feedback_clear_routine(voice_feedback_t *p);
voice_cue_name_t voice_feedback_error_cue(voice_turn_error_t error);
bool voice_feedback_is_error(voice_cue_name_t cue);
void voice_feedback_defer_press(voice_feedback_t *p,bool hold);
void voice_feedback_release_button(voice_feedback_t *p);
bool voice_feedback_take_press(voice_feedback_t *p);
#endif
