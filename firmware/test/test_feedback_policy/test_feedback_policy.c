#include <unity.h>
#include <string.h>
#include "voice_feedback_policy.h"
#include "../test_main/fakes/hw_fakes.c"
void setUp(void){}void tearDown(void){}
static void test_states_stages_duplicate_and_followup(void){
 voice_feedback_t p;voice_feedback_init(&p);voice_cue_name_t cue;
 voice_feedback_event(&p,FEEDBACK_READY,VOICE_TURN_ERROR_NONE,false);
 TEST_ASSERT_TRUE(voice_feedback_peek(&p,true,&cue));TEST_ASSERT_EQUAL(VOICE_CUE_READY,cue);
 voice_feedback_started(&p,cue);
 voice_feedback_event(&p,FEEDBACK_READY,VOICE_TURN_ERROR_NONE,false);TEST_ASSERT_FALSE(voice_feedback_pending(&p));
 voice_feedback_event(&p,FEEDBACK_CAPTURE,0,false);TEST_ASSERT_FALSE(voice_feedback_pending(&p));
 voice_feedback_event(&p,FEEDBACK_PROCESSING,0,false);
 voice_feedback_stage(&p,VOICE_TURN_STATUS_TRANSCRIBING);voice_feedback_stage(&p,VOICE_TURN_STATUS_THINKING);
 TEST_ASSERT_TRUE(voice_feedback_peek(&p,true,&cue));TEST_ASSERT_EQUAL(VOICE_CUE_THINKING,cue);
 voice_feedback_event(&p,FEEDBACK_ANSWERING,0,false);voice_feedback_stage(&p,VOICE_TURN_STATUS_SYNTHESIZING);
 TEST_ASSERT_TRUE(voice_feedback_peek(&p,true,&cue));TEST_ASSERT_EQUAL(VOICE_CUE_ANSWERING,cue);
 voice_feedback_event(&p,FEEDBACK_DONE,0,true);TEST_ASSERT_FALSE(voice_feedback_pending(&p));
 voice_feedback_event(&p,FEEDBACK_CAPTURE,0,false);voice_feedback_event(&p,FEEDBACK_DONE,0,false);
 TEST_ASSERT_TRUE(voice_feedback_peek(&p,true,&cue));TEST_ASSERT_EQUAL(VOICE_CUE_DONE,cue);
}
static void test_error_waits_for_owner_and_survives_ready_and_cancel(void){
 voice_feedback_t p;voice_feedback_init(&p);voice_cue_name_t cue;
 voice_feedback_event(&p,FEEDBACK_PROCESSING,0,false);
 voice_feedback_event(&p,FEEDBACK_ERROR,VOICE_TURN_ERROR_AGENT_TIMEOUT,false);
 voice_feedback_event(&p,FEEDBACK_CANCELLED,0,false);voice_feedback_event(&p,FEEDBACK_READY,0,false);
 TEST_ASSERT_TRUE(voice_feedback_error_pending(&p));TEST_ASSERT_FALSE(voice_feedback_peek(&p,false,&cue));
 TEST_ASSERT_TRUE(voice_feedback_peek(&p,true,&cue));TEST_ASSERT_EQUAL(VOICE_CUE_TIMEOUT,cue);
 TEST_ASSERT_TRUE(voice_feedback_error_pending(&p)); /* failed start/OTA cannot consume */
 voice_feedback_started(&p,cue);TEST_ASSERT_FALSE(voice_feedback_error_pending(&p));
 TEST_ASSERT_TRUE(voice_feedback_peek(&p,true,&cue));TEST_ASSERT_EQUAL(VOICE_CUE_READY,cue);
}
static void test_error_classes_fallback_and_deferred_hold(void){
 TEST_ASSERT_EQUAL(VOICE_CUE_RECOGNITION_ERROR,voice_feedback_error_cue(VOICE_TURN_ERROR_STT_FAILED));
 TEST_ASSERT_EQUAL(VOICE_CUE_SYNTHESIS_ERROR,voice_feedback_error_cue(VOICE_TURN_ERROR_TTS_FAILED));
 TEST_ASSERT_EQUAL(VOICE_CUE_ERROR,voice_feedback_error_cue(VOICE_TURN_ERROR_UNKNOWN));
 size_t a,b,c;const uint8_t *progress=voice_cue_fallback_named(VOICE_CUE_PROCESSING,&a);
 const uint8_t *done=voice_cue_fallback_named(VOICE_CUE_DONE,&b);const uint8_t *error=voice_cue_fallback_named(VOICE_CUE_ERROR,&c);
 TEST_ASSERT_TRUE(a&&b&&c);TEST_ASSERT_TRUE(!(a&1)&&!(b&1)&&!(c&1));
 TEST_ASSERT_TRUE(a<=24000 && b<=24000 && c<=24000);
 TEST_ASSERT_TRUE(a!=b || memcmp(progress,done,a));TEST_ASSERT_TRUE(b!=c || memcmp(done,error,b));
 voice_feedback_t p;voice_feedback_init(&p);voice_feedback_defer_press(&p,true);voice_feedback_release_button(&p);
 TEST_ASSERT_FALSE(voice_feedback_take_press(&p));
 voice_feedback_defer_press(&p,false);voice_feedback_release_button(&p);TEST_ASSERT_TRUE(voice_feedback_take_press(&p));
 TEST_ASSERT_FALSE(voice_feedback_take_press(&p));
}
typedef struct {unsigned calls;int owner;bool can_release;} gate_fake_t;
static bool acquire_gate(void *ctx){gate_fake_t *g=ctx;g->calls++;if(g->owner)return false;g->owner=1;return true;}
static bool release_gate(void *ctx){gate_fake_t *g=ctx;if(!g->can_release)return false;g->owner=0;return true;}
static void test_ready_cue_gate_transfers_to_press_and_never_bypasses_ota(void){
 voice_feedback_t p;voice_feedback_init(&p);gate_fake_t gate={.can_release=true};
 TEST_ASSERT_TRUE(voice_feedback_claim_gate(&p,acquire_gate,&gate));
 voice_feedback_event(&p,FEEDBACK_READY,0,false);voice_feedback_started(&p,VOICE_CUE_READY);
 /* Natural completion and active-cue preemption both retain the app lease. */
 voice_feedback_clear_routine(&p);voice_feedback_event(&p,FEEDBACK_CAPTURE,0,false);
 TEST_ASSERT_TRUE(voice_feedback_claim_gate(&p,acquire_gate,&gate));TEST_ASSERT_EQUAL(1,gate.calls);
 voice_feedback_release_gate(&p,release_gate,&gate);TEST_ASSERT_FALSE(p.gate_owned);
 gate.owner=2;TEST_ASSERT_FALSE(voice_feedback_claim_gate(&p,acquire_gate,&gate));TEST_ASSERT_FALSE(p.gate_owned);
 gate.owner=0;TEST_ASSERT_TRUE(voice_feedback_claim_gate(&p,acquire_gate,&gate));
 gate.can_release=false;voice_feedback_release_gate(&p,release_gate,&gate);TEST_ASSERT_TRUE(p.gate_owned);
}
static void test_cancel_after_ready_worker_exit_completes_locally(void){
 TEST_ASSERT_TRUE(voice_feedback_cancel_complete(true,false,false));
 TEST_ASSERT_FALSE(voice_feedback_cancel_complete(true,true,false));
 TEST_ASSERT_FALSE(voice_feedback_cancel_complete(false,false,false));
 TEST_ASSERT_FALSE(voice_feedback_cancel_complete(true,false,true));
}
static void test_boot_guard_is_adopted_until_confirmation_and_resumed_turn_done(void){
 voice_feedback_t p;gate_fake_t gate={.owner=1,.can_release=false};
 voice_feedback_boot_init(&p);
 voice_feedback_event(&p,FEEDBACK_PROCESSING,0,false);
 TEST_ASSERT_TRUE(voice_feedback_claim_gate(&p,acquire_gate,&gate));TEST_ASSERT_EQUAL(0,gate.calls);
 voice_feedback_release_gate(&p,release_gate,&gate);TEST_ASSERT_TRUE(p.gate_owned);TEST_ASSERT_EQUAL(1,gate.owner);
 /* Confirmation allows release, but a resumed turn retains it until caller
  * reaches safe terminal idle; ANSWERING can use the same boot lease. */
 gate.can_release=true;voice_feedback_event(&p,FEEDBACK_ANSWERING,0,false);
 TEST_ASSERT_TRUE(voice_feedback_claim_gate(&p,acquire_gate,&gate));TEST_ASSERT_EQUAL(0,gate.calls);
 voice_feedback_release_gate(&p,release_gate,&gate);TEST_ASSERT_FALSE(p.gate_owned);TEST_ASSERT_EQUAL(0,gate.owner);
}
int main(void){UNITY_BEGIN();RUN_TEST(test_boot_guard_is_adopted_until_confirmation_and_resumed_turn_done);RUN_TEST(test_ready_cue_gate_transfers_to_press_and_never_bypasses_ota);RUN_TEST(test_cancel_after_ready_worker_exit_completes_locally);RUN_TEST(test_states_stages_duplicate_and_followup);RUN_TEST(test_error_waits_for_owner_and_survives_ready_and_cancel);RUN_TEST(test_error_classes_fallback_and_deferred_hold);return UNITY_END();}
