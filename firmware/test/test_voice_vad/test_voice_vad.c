#include <unity.h>
#include "voice_vad.h"
#include "../test_wav_parser/fakes_hw.c"
static void silence_and_fragments(void){
 uint8_t zero[320]={0};TEST_ASSERT_TRUE(voice_vad_reset());
 for(int i=0;i<100;i++){TEST_ASSERT_FALSE(voice_vad_feed(zero,127));TEST_ASSERT_FALSE(voice_vad_feed(zero,193));}
 TEST_ASSERT_TRUE(voice_vad_ready());TEST_ASSERT_TRUE(voice_vad_reset());
}
int main(void){UNITY_BEGIN();RUN_TEST(silence_and_fragments);return UNITY_END();}
