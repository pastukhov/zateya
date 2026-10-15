#include <unity.h>
#include "voice_listening_cue.h"
#include "hardware.h"
static bool drained, blocked;static unsigned stops;static size_t written;
uint32_t hw_clock_ms(void){return 0;}bool hw_button_raw(void){return false;}
bool hw_report_error(const char*x){(void)x;return false;}
void hw_audio_capture_start(void){}void hw_audio_capture_stop(void){}
size_t hw_audio_capture_read(uint8_t*b,size_t n){(void)b;(void)n;return 0;}
void hw_audio_playback_start(const void*p,size_t n){(void)p;(void)n;}
void hw_audio_playback_stop(void){stops++;}
bool hw_audio_playback_drained(void){return drained;}
size_t hw_audio_playback_write(const uint8_t*p,size_t n){(void)p;if(blocked)return 0;written+=n;return n;}
static void test_waits_for_drain_and_stops(void){
 voice_listening_cue_t c={0};uint8_t pcm[2048]={0};stops=0;written=0;drained=false;blocked=false;
 TEST_ASSERT_TRUE(voice_listening_cue_start(&c,pcm,sizeof(pcm),0));
 TEST_ASSERT_EQUAL(CUE_BUSY,voice_listening_cue_tick(&c,1));
 TEST_ASSERT_EQUAL(CUE_BUSY,voice_listening_cue_tick(&c,2));
 TEST_ASSERT_EQUAL(2048,written);TEST_ASSERT_EQUAL(0,stops);
 drained=true;TEST_ASSERT_EQUAL(CUE_DONE,voice_listening_cue_tick(&c,3));
 TEST_ASSERT_EQUAL(1,stops);TEST_ASSERT_EQUAL(CUE_DONE,voice_listening_cue_tick(&c,4));
 TEST_ASSERT_EQUAL(1,stops);
}
static void test_stall_timeout_cancel_and_input(void){
 voice_listening_cue_t c={0};uint8_t pcm[2]={0};stops=0;blocked=true;
 TEST_ASSERT_FALSE(voice_listening_cue_start(&c,pcm,1,0));
 TEST_ASSERT_FALSE(voice_listening_cue_start(&c,pcm,240002,0));
 TEST_ASSERT_TRUE(voice_listening_cue_start(&c,pcm,2,UINT32_MAX-10));
 TEST_ASSERT_FALSE(voice_listening_cue_start(&c,pcm,2,0));
 TEST_ASSERT_EQUAL(CUE_ERROR,voice_listening_cue_tick(&c,UINT32_MAX-10+8000u));
 TEST_ASSERT_EQUAL(1,stops);
 TEST_ASSERT_TRUE(voice_listening_cue_start(&c,pcm,2,0));
 voice_listening_cue_cancel(&c);TEST_ASSERT_EQUAL(2,stops);
 TEST_ASSERT_EQUAL(CUE_ERROR,voice_listening_cue_tick(&c,1));
}
int main(void){UNITY_BEGIN();RUN_TEST(test_waits_for_drain_and_stops);RUN_TEST(test_stall_timeout_cancel_and_input);return UNITY_END();}
