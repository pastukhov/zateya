#include <unity.h>
#include <string.h>
#include "voice_cue_store.h"
#include "../test_main/fakes/hw_fakes.c"
void setUp(void){}void tearDown(void){}
static void test_layout_requires_exact_actual_ota_and_safe_tail(void){
 voice_cue_partition_t p[]={{1,2,0x9000,0x6000,false,false},{1,1,0xf000,0x1000,false,false},
 {1,0,0x10000,0x2000,false,false},{0,0x10,0x20000,0x300000,false,false},{0,0x11,0x320000,0x300000,false,false}};
 TEST_ASSERT_TRUE(voice_cue_store_layout_valid(0x800000,p,5));
 TEST_ASSERT_FALSE(voice_cue_store_layout_valid(0x400000,p,5));
 p[4].offset=0x330000;TEST_ASSERT_FALSE(voice_cue_store_layout_valid(0x800000,p,5));p[4].offset=0x320000;
 p[4].encrypted=true;TEST_ASSERT_FALSE(voice_cue_store_layout_valid(0x800000,p,5));p[4].encrypted=false;
 p[3].subtype=0;TEST_ASSERT_FALSE(voice_cue_store_layout_valid(0x800000,p,5));
}
static bool hash(const uint8_t *data,size_t n,uint8_t out[32]){
 memset(out,0,32);for(size_t i=0;i<n;i++)out[i%32]^=data[i];return true;
}
static void test_versioned_records_reject_wrong_name_size_format_and_digest(void){
 uint8_t header[VOICE_CUE_RECORD_HEADER],pcm[4]={1,2,3,4};char sha[65]="0102030400000000000000000000000000000000000000000000000000000000";
 TEST_ASSERT_TRUE(voice_cue_record_encode(header,VOICE_CUE_READY,4,sha));
 voice_cue_record_t record;
 TEST_ASSERT_TRUE(voice_cue_record_decode(header,VOICE_CUE_READY,sizeof(header)+4,&record));
 TEST_ASSERT_TRUE(voice_cue_record_verify(header,pcm,4,VOICE_CUE_READY,hash));
 TEST_ASSERT_FALSE(voice_cue_record_decode(header,VOICE_CUE_DONE,sizeof(header)+4,&record));
 TEST_ASSERT_FALSE(voice_cue_record_decode(header,VOICE_CUE_READY,sizeof(header)+3,&record));
 pcm[0]^=1;TEST_ASSERT_FALSE(voice_cue_record_verify(header,pcm,4,VOICE_CUE_READY,hash));
 header[8]=2;TEST_ASSERT_FALSE(voice_cue_record_decode(header,VOICE_CUE_READY,sizeof(header)+4,&record));
 TEST_ASSERT_FALSE(voice_cue_record_encode(header,VOICE_CUE_READY,240002,sha));
 TEST_ASSERT_FALSE(voice_cue_record_encode(header,VOICE_CUE_READY,4,"bad"));
}
int main(void){UNITY_BEGIN();RUN_TEST(test_layout_requires_exact_actual_ota_and_safe_tail);RUN_TEST(test_versioned_records_reject_wrong_name_size_format_and_digest);return UNITY_END();}
