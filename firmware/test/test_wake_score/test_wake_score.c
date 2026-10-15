#include <unity.h>
#include "voice_wake_score.h"
#include "../test_wav_parser/fakes_hw.c"
static void test_requires_warmup_and_average(void) {
 voice_wake_score_t s={0};
 for(int i=0;i<99;i++)TEST_ASSERT_FALSE(voice_wake_score_feed(&s,255));
 voice_wake_score_reset(&s);
 for(int i=0;i<100;i++)TEST_ASSERT_FALSE(voice_wake_score_feed(&s,0));
 TEST_ASSERT_FALSE(voice_wake_score_feed(&s,255));
 TEST_ASSERT_FALSE(voice_wake_score_feed(&s,255));
 TEST_ASSERT_TRUE(voice_wake_score_feed(&s,255));
 voice_wake_score_reset(&s);TEST_ASSERT_FALSE(voice_wake_score_feed(&s,255));
}
int main(void){UNITY_BEGIN();RUN_TEST(test_requires_warmup_and_average);return UNITY_END();}
