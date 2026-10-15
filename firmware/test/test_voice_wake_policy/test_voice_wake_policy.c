#include <unity.h>
#include "voice_wake_policy.h"

static void test_cue_and_echo_are_not_recorded(void) {
  voice_wake_t w; voice_wake_init(&w,3000,600000);
  TEST_ASSERT_FALSE(voice_wake_activate(&w,false,0));
  TEST_ASSERT_TRUE(voice_wake_activate(&w,true,0));
  TEST_ASSERT_FALSE(voice_wake_activate(&w,true,0));
  TEST_ASSERT_EQUAL(WAKE_NONE,voice_wake_tick(&w,true,500,true,false));
  voice_wake_cue_done(&w,1000,true);
  TEST_ASSERT_EQUAL(WAKE_NONE,voice_wake_tick(&w,true,1149,true,false));
  TEST_ASSERT_EQUAL(WAKE_START_RECORD,voice_wake_tick(&w,true,1150,true,false));
}
static void test_silence_and_manual_endpoint(void) {
  voice_wake_t w; voice_wake_init(&w,3000,600000);
  voice_wake_activate(&w,true,0); voice_wake_cue_done(&w,10,true);
  TEST_ASSERT_EQUAL(WAKE_START_RECORD,voice_wake_tick(&w,true,160,true,false));
  TEST_ASSERT_EQUAL(WAKE_NONE,voice_wake_tick(&w,true,2000,true,false));
  TEST_ASSERT_EQUAL(WAKE_NONE,voice_wake_tick(&w,true,4999,false,false));
  TEST_ASSERT_EQUAL(WAKE_FINISH,voice_wake_tick(&w,true,5000,false,false));
  TEST_ASSERT_EQUAL(WAKE_NONE,voice_wake_tick(&w,true,5001,false,false));
  voice_wake_init(&w,3000,600000);voice_wake_activate(&w,true,0);
  voice_wake_cue_done(&w,0,true);voice_wake_tick(&w,true,150,true,false);
  TEST_ASSERT_EQUAL(WAKE_FINISH,voice_wake_tick(&w,true,151,true,true));
}
static void test_no_speech_and_power_loss(void) {
  voice_wake_t w;voice_wake_init(&w,3000,600000);
  voice_wake_activate(&w,true,0);voice_wake_cue_done(&w,0,true);
  TEST_ASSERT_EQUAL(WAKE_NONE,voice_wake_tick(&w,true,8149,false,false));
  TEST_ASSERT_EQUAL(WAKE_CANCEL,voice_wake_tick(&w,true,8150,false,false));
  voice_wake_init(&w,3000,600000);voice_wake_activate(&w,true,0);
  TEST_ASSERT_EQUAL(WAKE_CANCEL,voice_wake_tick(&w,false,100,false,false));
  voice_wake_init(&w,3000,600000);voice_wake_activate(&w,true,0);
  voice_wake_cue_done(&w,0,true);voice_wake_tick(&w,true,150,true,false);
  TEST_ASSERT_EQUAL(WAKE_NONE,voice_wake_tick(&w,false,500,true,false));
  TEST_ASSERT_EQUAL(WAKE_FINISH,voice_wake_tick(&w,false,3500,false,false));
}
static void test_wrap_limit_and_failed_cue(void) {
  voice_wake_t w;uint32_t t=UINT32_MAX-200;
  voice_wake_init(&w,3000,1000);voice_wake_activate(&w,true,t);
  voice_wake_cue_done(&w,t,true);
  TEST_ASSERT_EQUAL(WAKE_START_RECORD,voice_wake_tick(&w,true,t+150,true,false));
  TEST_ASSERT_EQUAL(WAKE_FINISH,voice_wake_tick(&w,true,t+1150,true,false));
  voice_wake_init(&w,3000,600000);voice_wake_activate(&w,true,0);
  voice_wake_cue_done(&w,10,false);
  TEST_ASSERT_EQUAL(WAKE_CANCEL,voice_wake_tick(&w,true,11,true,false));
}
int main(void){UNITY_BEGIN();RUN_TEST(test_cue_and_echo_are_not_recorded);
RUN_TEST(test_silence_and_manual_endpoint);RUN_TEST(test_no_speech_and_power_loss);
RUN_TEST(test_wrap_limit_and_failed_cue);return UNITY_END();}
