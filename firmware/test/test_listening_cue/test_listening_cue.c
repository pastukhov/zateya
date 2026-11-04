#include <unity.h>
#include <string.h>
#include "voice_listening_cue.h"
#include "hardware.h"
static bool drained, blocked, bad_write;static unsigned stops;static size_t written;
uint32_t hw_clock_ms(void){return 0;}bool hw_button_raw(void){return false;}
bool hw_report_error(const char*x){(void)x;return false;}
void hw_audio_capture_start(void){}void hw_audio_capture_stop(void){}
size_t hw_audio_capture_read(uint8_t*b,size_t n){(void)b;(void)n;return 0;}
void hw_audio_playback_start(const void*p,size_t n){(void)p;(void)n;}
void hw_audio_playback_stop(void){stops++;}
bool hw_audio_playback_drained(void){return drained;}
size_t hw_audio_playback_write(const uint8_t*p,size_t n){(void)p;if(bad_write)return n+2;if(blocked)return 0;written+=n;return n;}
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
static unsigned releases;
static void release_lease(void *ctx){(*(unsigned*)ctx)++;}
static void test_leases_release_on_done_cancel_error_and_failed_start(void){
 voice_listening_cue_t c={0};uint8_t pcm[2]={0};releases=0;drained=false;blocked=false;
 TEST_ASSERT_TRUE(voice_listening_cue_start_lease(&c,pcm,2,0,release_lease,&releases));
 /* Rejecting a second acquired cue must return only the new lease. */
 TEST_ASSERT_FALSE(voice_listening_cue_start_lease(&c,pcm,2,1,release_lease,&releases));
 TEST_ASSERT_EQUAL(1,releases);TEST_ASSERT_EQUAL(CUE_BUSY,voice_listening_cue_tick(&c,2));
 drained=true;TEST_ASSERT_EQUAL(CUE_DONE,voice_listening_cue_tick(&c,3));TEST_ASSERT_EQUAL(2,releases);
 voice_listening_cue_cancel(&c);TEST_ASSERT_EQUAL(2,releases);
 TEST_ASSERT_TRUE(voice_listening_cue_start_lease(&c,pcm,2,4,release_lease,&releases));
 voice_listening_cue_cancel(&c);TEST_ASSERT_EQUAL(3,releases);voice_listening_cue_cancel(&c);TEST_ASSERT_EQUAL(3,releases);
 TEST_ASSERT_FALSE(voice_listening_cue_start_lease(&c,pcm,1,5,release_lease,&releases));TEST_ASSERT_EQUAL(4,releases);
 blocked=true;TEST_ASSERT_TRUE(voice_listening_cue_start_lease(&c,pcm,2,6,release_lease,&releases));
 TEST_ASSERT_EQUAL(CUE_ERROR,voice_listening_cue_tick(&c,8006));TEST_ASSERT_EQUAL(5,releases);
 bad_write=true;blocked=false;
 TEST_ASSERT_TRUE(voice_listening_cue_start_lease(&c,pcm,2,9000,release_lease,&releases));
 TEST_ASSERT_EQUAL(CUE_ERROR,voice_listening_cue_tick(&c,9001));TEST_ASSERT_EQUAL(6,releases);
 bad_write=false;
 /* Missing cache uses a normal non-leased buffer, including repeat/cancel. */
 TEST_ASSERT_TRUE(voice_listening_cue_start_lease(&c,pcm,2,10000,NULL,NULL));
 voice_listening_cue_cancel(&c);TEST_ASSERT_EQUAL(6,releases);
}
#include "../test_cue_opus/fixture.h"
static unsigned opens,closes;static bool fail_open,fail_decode;
static void *decoder_open(void){opens++;return fail_open?NULL:&opens;}
static int decoder_decode(void *d,const uint8_t *p,size_t n,int16_t out[480]){(void)d;(void)p;(void)n;memset(out,0,960);return fail_decode?-1:480;}
static void decoder_close(void *d){(void)d;closes++;}
static void test_opus_failures_release_and_fallback(void){
 voice_listening_cue_t c={0};voice_cue_decoder_t ops={decoder_open,decoder_decode,decoder_close};
 unsigned count=0;uint8_t tone[2]={0};opens=closes=0;fail_open=true;
 TEST_ASSERT_FALSE(voice_listening_cue_start_opus(&c,fixture,sizeof(fixture),0,&ops,release_lease,&count));
 TEST_ASSERT_EQUAL(1,count);TEST_ASSERT_EQUAL(0,closes);
 TEST_ASSERT_TRUE(voice_listening_cue_start(&c,tone,sizeof(tone),0));voice_listening_cue_cancel(&c);
 fail_open=false;fail_decode=true;
 TEST_ASSERT_TRUE(voice_listening_cue_start_opus(&c,fixture,sizeof(fixture),1,&ops,release_lease,&count));
 TEST_ASSERT_EQUAL(CUE_ERROR,voice_listening_cue_tick(&c,2));
 TEST_ASSERT_EQUAL(2,count);TEST_ASSERT_EQUAL(1,closes);voice_listening_cue_cancel(&c);TEST_ASSERT_EQUAL(1,closes);
 fail_decode=false;
 TEST_ASSERT_TRUE(voice_listening_cue_start_opus(&c,fixture,sizeof(fixture),3,&ops,release_lease,&count));
 voice_listening_cue_cancel(&c);TEST_ASSERT_EQUAL(3,count);TEST_ASSERT_EQUAL(2,closes);
}
int main(void){UNITY_BEGIN();RUN_TEST(test_opus_failures_release_and_fallback);RUN_TEST(test_leases_release_on_done_cancel_error_and_failed_start);RUN_TEST(test_waits_for_drain_and_stops);RUN_TEST(test_stall_timeout_cancel_and_input);return UNITY_END();}
