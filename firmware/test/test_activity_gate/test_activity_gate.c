#include <unity.h>
#include "voice_activity_gate.h"
#include "../test_main/fakes/hw_fakes.c"
void setUp(void){}void tearDown(void){}
static void test_every_owner_excludes_every_other_and_release_is_scoped(void){
 atomic_int gate=VOICE_ACTIVITY_VOICE;
 TEST_ASSERT_FALSE(voice_activity_claim(&gate,VOICE_ACTIVITY_STORAGE));
 TEST_ASSERT_FALSE(voice_activity_release(&gate,VOICE_ACTIVITY_VOICE,false));
 TEST_ASSERT_TRUE(voice_activity_release(&gate,VOICE_ACTIVITY_VOICE,true));
 for(int owner=1;owner<=3;owner++){
  TEST_ASSERT_TRUE(voice_activity_claim(&gate,(voice_activity_t)owner));
  for(int other=1;other<=3;other++){
   TEST_ASSERT_FALSE(voice_activity_claim(&gate,(voice_activity_t)other));
   if(other!=owner)TEST_ASSERT_FALSE(voice_activity_release(&gate,(voice_activity_t)other,true));
  }
  TEST_ASSERT_EQUAL(owner,atomic_load(&gate));
  TEST_ASSERT_TRUE(voice_activity_release(&gate,(voice_activity_t)owner,true));
 }
 TEST_ASSERT_FALSE(voice_activity_claim(&gate,(voice_activity_t)4));
}
int main(void){UNITY_BEGIN();RUN_TEST(test_every_owner_excludes_every_other_and_release_is_scoped);return UNITY_END();}
