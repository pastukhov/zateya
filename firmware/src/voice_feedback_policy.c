#include "voice_feedback_policy.h"
void voice_feedback_init(voice_feedback_t *p){*p=(voice_feedback_t){0};}
void voice_feedback_boot_init(voice_feedback_t *p){voice_feedback_init(p);p->gate_owned=true;}
bool voice_feedback_is_error(voice_cue_name_t c){return c==VOICE_CUE_OFFLINE||c>=VOICE_CUE_ERROR;}
voice_cue_name_t voice_feedback_error_cue(voice_turn_error_t error){
 switch(error){
 case VOICE_TURN_ERROR_AGENT_TIMEOUT:case VOICE_TURN_ERROR_DEADLINE:return VOICE_CUE_TIMEOUT;
 case VOICE_TURN_ERROR_STT_FAILED:return VOICE_CUE_RECOGNITION_ERROR;
 case VOICE_TURN_ERROR_TTS_FAILED:return VOICE_CUE_SYNTHESIS_ERROR;
 case VOICE_TURN_ERROR_CONNECTION:return VOICE_CUE_OFFLINE;
 default:return VOICE_CUE_ERROR;
 }
}
void voice_feedback_event(voice_feedback_t *p,voice_feedback_event_t event,voice_turn_error_t error,bool followup){
 if(event==FEEDBACK_NONE)return;
 if(event==FEEDBACK_CAPTURE){p->last=event;p->routine_pending=false;p->stage_open=false;return;}
 if(event==p->last)return;
 p->last=event;
 if(event==FEEDBACK_ERROR){p->error=voice_feedback_error_cue(error);p->error_pending=true;p->routine_pending=false;p->stage_open=false;return;}
 if(event==FEEDBACK_DONE && followup){p->routine_pending=false;p->stage_open=false;return;}
 voice_cue_name_t cue;
 switch(event){
 case FEEDBACK_READY:cue=VOICE_CUE_READY;p->stage_open=false;break;
 case FEEDBACK_PROCESSING:cue=VOICE_CUE_PROCESSING;p->stage_open=true;break;
 case FEEDBACK_TRANSCRIBING:cue=VOICE_CUE_TRANSCRIBING;break;
 case FEEDBACK_THINKING:cue=VOICE_CUE_THINKING;break;
 case FEEDBACK_SYNTHESIZING:cue=VOICE_CUE_SYNTHESIZING;break;
 case FEEDBACK_ANSWERING:cue=VOICE_CUE_ANSWERING;p->stage_open=false;break;
 case FEEDBACK_DONE:cue=VOICE_CUE_DONE;p->stage_open=false;break;
 case FEEDBACK_CANCELLED:cue=VOICE_CUE_CANCELLED;p->stage_open=false;break;
 default:return;
 }
 p->routine=cue;p->routine_pending=true;
}
void voice_feedback_stage(voice_feedback_t *p,voice_turn_status_t stage){
 if(!p->stage_open)return;
 voice_feedback_event_t event=stage==VOICE_TURN_STATUS_TRANSCRIBING?FEEDBACK_TRANSCRIBING:
  stage==VOICE_TURN_STATUS_THINKING?FEEDBACK_THINKING:
  stage==VOICE_TURN_STATUS_SYNTHESIZING?FEEDBACK_SYNTHESIZING:FEEDBACK_NONE;
 voice_feedback_event(p,event,VOICE_TURN_ERROR_NONE,false);
}
bool voice_feedback_pending(const voice_feedback_t *p){return p->error_pending||p->routine_pending;}
bool voice_feedback_error_pending(const voice_feedback_t *p){return p->error_pending;}
bool voice_feedback_peek(const voice_feedback_t *p,bool safe,voice_cue_name_t *cue){
 if(!safe||!voice_feedback_pending(p))return false;
 *cue=p->error_pending?p->error:p->routine;return true;
}
void voice_feedback_started(voice_feedback_t *p,voice_cue_name_t cue){
 if(p->error_pending && p->error==cue)p->error_pending=false;
 else if(p->routine_pending && p->routine==cue)p->routine_pending=false;
}
void voice_feedback_clear_routine(voice_feedback_t *p){p->routine_pending=false;p->stage_open=false;}
void voice_feedback_defer_press(voice_feedback_t *p,bool hold){p->manual_pending=true;p->manual_hold=hold;}
void voice_feedback_release_button(voice_feedback_t *p){if(p->manual_hold)p->manual_pending=false;}
bool voice_feedback_take_press(voice_feedback_t *p){bool ready=p->manual_pending;p->manual_pending=false;return ready;}

bool voice_feedback_claim_gate(voice_feedback_t *p,bool (*acquire)(void *),void *ctx){
 if(p->gate_owned)return true;
 if(!acquire(ctx))return false;
 p->gate_owned=true;return true;
}
void voice_feedback_release_gate(voice_feedback_t *p,bool (*release)(void *),void *ctx){
 if(p->gate_owned && release(ctx))p->gate_owned=false;
}
bool voice_feedback_cancel_complete(bool requested,bool worker_active,bool storage_failed){
 return requested && !worker_active && !storage_failed;
}
