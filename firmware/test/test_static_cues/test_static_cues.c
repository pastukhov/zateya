#include <unity.h>
#include "voice_static_cues.h"
#include "../test_main/fakes/hw_fakes.c"
void setUp(void){}void tearDown(void){}
static void test_integrity_and_fallback(void){
 const uint8_t pcm[]={1,2,3,4};
 TEST_ASSERT_TRUE(voice_static_cue_valid(pcm,4,0xb63cfbcdu));
 TEST_ASSERT_FALSE(voice_static_cue_valid(pcm,3,0xb63cfbcdu));
 TEST_ASSERT_FALSE(voice_static_cue_valid(pcm,4,0));
 for(int i=VOICE_CUE_LISTENING;i<=VOICE_CUE_OFFLINE;i++){
  size_t n=0;const uint8_t *a=voice_static_cue_get(i,&n);
  TEST_ASSERT_NOT_NULL(a);TEST_ASSERT_TRUE(n>0 && n<=240000 && !(n&1));
  size_t n2=0;TEST_ASSERT_EQUAL_PTR(a,voice_static_cue_get(i,&n2));TEST_ASSERT_EQUAL(n,n2);
 }
}
int main(void){UNITY_BEGIN();RUN_TEST(test_integrity_and_fallback);return UNITY_END();}
