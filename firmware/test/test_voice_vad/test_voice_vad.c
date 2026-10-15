#include <unity.h>
#include "voice_vad.h"
#include "../test_wav_parser/fakes_hw.c"
static void silence_and_fragments(void){
 uint8_t zero[320]={0};TEST_ASSERT_TRUE(voice_vad_reset());
 for(int i=0;i<100;i++){TEST_ASSERT_FALSE(voice_vad_feed(zero,127));TEST_ASSERT_FALSE(voice_vad_feed(zero,193));}
 TEST_ASSERT_TRUE(voice_vad_ready());TEST_ASSERT_TRUE(voice_vad_reset());
}
static void isolated_click_does_not_start_speech(void) {
 int16_t click[160]={0}; uint8_t silence[320]={0};
 for(int i=0;i<160;i++)click[i]=(i%16<8)?4000:-4000;
 TEST_ASSERT_TRUE(voice_vad_reset());
 TEST_ASSERT_FALSE(voice_vad_feed((const uint8_t*)click,sizeof(click)));
 for(int i=0;i<100;i++)TEST_ASSERT_FALSE(voice_vad_feed(silence,sizeof(silence)));
}
static void sustained_sound_starts_and_silence_ends(void) {
 int16_t pcm[160];bool detected=false;unsigned noise=1;
 TEST_ASSERT_TRUE(voice_vad_reset());
 for(int f=0;f<50;f++) {
  for(int i=0;i<160;i++){noise=noise*1664525u+1013904223u;pcm[i]=(int16_t)((noise>>16)%12000)-6000;}
  detected=voice_vad_feed((const uint8_t*)pcm,sizeof(pcm))||detected;
 }
 TEST_ASSERT_TRUE(detected);
 uint8_t silence[320]={0};for(int i=0;i<100;i++)voice_vad_feed(silence,sizeof(silence));
 TEST_ASSERT_FALSE(voice_vad_feed(silence,sizeof(silence)));
 TEST_ASSERT_TRUE(voice_vad_reset());
 TEST_ASSERT_FALSE(voice_vad_feed(silence,sizeof(silence)));
}
int main(void){UNITY_BEGIN();RUN_TEST(silence_and_fragments);RUN_TEST(isolated_click_does_not_start_speech);RUN_TEST(sustained_sound_starts_and_silence_ends);return UNITY_END();}
