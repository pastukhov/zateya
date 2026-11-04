#include <unity.h>
#include <string.h>
#include "voice_cue_opus.h"
#include "../test_main/fakes/hw_fakes.c"
#include "fixture.h"
void setUp(void){}void tearDown(void){}
static void test_bounded_parser_and_duration(void){
 voice_cue_opus_t o;TEST_ASSERT_TRUE(voice_cue_opus_parse(fixture,sizeof(fixture),&o));
 TEST_ASSERT_EQUAL(1000,o.samples);TEST_ASSERT_EQUAL(156,o.preskip);TEST_ASSERT_EQUAL(3,o.count);
 const uint8_t *packet;size_t length;
 for(unsigned i=0;i<3;i++)TEST_ASSERT_TRUE(voice_cue_opus_next(&o,fixture,sizeof(fixture),&packet,&length));
 TEST_ASSERT_FALSE(voice_cue_opus_next(&o,fixture,sizeof(fixture),&packet,&length));
 uint8_t data[sizeof(fixture)+1];memcpy(data,fixture,sizeof(fixture));data[sizeof(fixture)]=0;
 TEST_ASSERT_FALSE(voice_cue_opus_parse(data,sizeof(data),&o));
 TEST_ASSERT_FALSE(voice_cue_opus_parse(data,sizeof(fixture)-1,&o));
 data[20]=255;data[21]=255;TEST_ASSERT_FALSE(voice_cue_opus_parse(data,sizeof(fixture),&o));
 memcpy(data,fixture,sizeof(fixture));data[32]=0;data[33]=0;TEST_ASSERT_FALSE(voice_cue_opus_parse(data,sizeof(fixture),&o));
 memcpy(data,fixture,sizeof(fixture));data[34]=0x80;TEST_ASSERT_FALSE(voice_cue_opus_parse(data,sizeof(fixture),&o));
}
int main(void){UNITY_BEGIN();RUN_TEST(test_bounded_parser_and_duration);return UNITY_END();}
