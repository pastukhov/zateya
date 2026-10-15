#include <unity.h>
#include "voice_cue_cache.h"
#include "../test_wav_parser/fakes_hw.c"
#include <string.h>
static void test_manifest_limits(void) {
 const char *sha="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
 TEST_ASSERT_TRUE(voice_cue_metadata_valid(4800,24000,1,16,sha));
 TEST_ASSERT_FALSE(voice_cue_metadata_valid(4801,24000,1,16,sha));
 TEST_ASSERT_FALSE(voice_cue_metadata_valid(0,24000,1,16,sha));
 TEST_ASSERT_FALSE(voice_cue_metadata_valid(240002,24000,1,16,sha));
 TEST_ASSERT_FALSE(voice_cue_metadata_valid(20,16000,1,16,sha));
 TEST_ASSERT_FALSE(voice_cue_metadata_valid(20,24000,2,16,sha));
 TEST_ASSERT_FALSE(voice_cue_metadata_valid(20,24000,1,8,sha));
 TEST_ASSERT_FALSE(voice_cue_metadata_valid(20,24000,1,16,"../bad"));
 TEST_ASSERT_FALSE(voice_cue_metadata_valid(20,24000,1,16,NULL));
}
static void test_publication_waits_for_reader(void) {
 voice_cue_slot_t slot={0};uint8_t first[2]={0},next[2]={1};uint8_t *old=NULL;size_t n=99;
 TEST_ASSERT_NULL(voice_cue_slot_acquire(&slot,&n)); TEST_ASSERT_EQUAL(0,n);
 TEST_ASSERT_TRUE(voice_cue_slot_publish(&slot,first,2,&old));TEST_ASSERT_NULL(old);
 TEST_ASSERT_EQUAL_PTR(first,voice_cue_slot_acquire(&slot,&n));TEST_ASSERT_EQUAL(2,n);
 TEST_ASSERT_FALSE(voice_cue_slot_publish(&slot,next,2,&old));
 voice_cue_slot_release(&slot);
 TEST_ASSERT_TRUE(voice_cue_slot_publish(&slot,next,2,&old));TEST_ASSERT_EQUAL_PTR(first,old);
 TEST_ASSERT_EQUAL_PTR(next,voice_cue_slot_acquire(&slot,&n));
 voice_cue_slot_release(&slot);voice_cue_slot_release(&slot);
 TEST_ASSERT_EQUAL(0,slot.readers);
}
int main(void){UNITY_BEGIN();RUN_TEST(test_manifest_limits);RUN_TEST(test_publication_waits_for_reader);return UNITY_END();}
