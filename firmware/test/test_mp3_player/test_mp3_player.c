#include <unity.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>
#include "voice_mp3_player.h"
static unsigned decoded,closed;static size_t output,limit=999999;
static unsigned tone_hz;
static uint64_t checksum;
static double energy;
static size_t measured;
static void *open_fake(void){decoded=0;return (void*)1;}
static int decode_fake(void*d,const uint8_t*p,size_t n,int16_t*out,size_t cap,unsigned*rate,unsigned*channels){
 (void)d;(void)n;(void)cap;unsigned v;size_t bytes;
 if(!voice_mp3_frame_header(p,4,rate,channels,&v,&bytes))return -1;
 for(unsigned i=0;i<1152* *channels;i++) {
  unsigned sample=decoded*1152+i/ *channels;
  out[i]=tone_hz?(int16_t)(12000*sin(2*3.141592653589793*tone_hz*sample/ *rate)):(int16_t)(i%100);
 }
 decoded++;return 1152* *channels;
}
static void close_fake(void*d){(void)d;closed++;}
static const voice_mp3_decoder_t ops={open_fake,decode_fake,close_fake};
static size_t sink(void*ctx,const uint8_t*p,size_t n){
 (void)ctx;
 if(n>limit)n=limit;
 for(size_t i=0;i<n;i++)checksum=(checksum^p[i])*1099511628211ULL;
 for(size_t i=0;i+1<n;i+=2) {
  int16_t value;memcpy(&value,p+i,2);
  if(output+i>2048) {energy+=(double)value*value;measured++;}
 }
 output+=n;
 return n;
}
static uint8_t frames[1251];
void setUp(void){memset(frames,0,sizeof(frames));for(unsigned i=0;i<3;i++){frames[i*417]=255;frames[i*417+1]=251;frames[i*417+2]=144;frames[i*417+3]=192;}output=closed=0;limit=999999;tone_hz=0;checksum=1469598103934665603ULL;energy=0;measured=0;}
void tearDown(void){}
static void splits(void){
 uint64_t expected=0;
 for(unsigned split=1;split<=sizeof(frames);split++){
  checksum=1469598103934665603ULL;output=0;
  voice_mp3_player_t *p=calloc(1,sizeof(*p));TEST_ASSERT_TRUE(voice_mp3_player_init(p,&ops,sink,NULL));
  size_t offset=0;while(offset<sizeof(frames)){size_t n=sizeof(frames)-offset;if(n>split)n=split;
   TEST_ASSERT_EQUAL_UINT(n,voice_mp3_player_feed(p,frames+offset,n));offset+=n;}
  TEST_ASSERT_TRUE(voice_mp3_player_finish(p));TEST_ASSERT_EQUAL_UINT(3,decoded);TEST_ASSERT_EQUAL_UINT(44100,p->rate);
  TEST_ASSERT_EQUAL_UINT(3456,p->input_samples);TEST_ASSERT_EQUAL_UINT(1881*44100,p->next_output);
  if(split==1)expected=checksum;
  TEST_ASSERT_EQUAL_UINT64(expected,checksum);
  TEST_ASSERT_EQUAL_UINT(1881*2,output);
  voice_mp3_player_close(p);free(p);
 }
}
static void truncated(void){voice_mp3_player_t p;TEST_ASSERT_TRUE(voice_mp3_player_init(&p,&ops,sink,NULL));voice_mp3_player_feed(&p,frames,sizeof(frames)-1);TEST_ASSERT_FALSE(voice_mp3_player_finish(&p));voice_mp3_player_close(&p);}
static void corrupt(void){voice_mp3_player_t p;frames[417]=0;TEST_ASSERT_TRUE(voice_mp3_player_init(&p,&ops,sink,NULL));voice_mp3_player_feed(&p,frames,sizeof(frames));TEST_ASSERT_TRUE(p.failed);voice_mp3_player_close(&p);}
static void backpressure(void){voice_mp3_player_t p;limit=0;TEST_ASSERT_TRUE(voice_mp3_player_init(&p,&ops,sink,NULL));size_t n=voice_mp3_player_feed(&p,frames,sizeof(frames));TEST_ASSERT_EQUAL_UINT(417,n);TEST_ASSERT_FALSE(voice_mp3_player_finish(&p));limit=64;size_t offset=n;while(offset<sizeof(frames))offset+=voice_mp3_player_feed(&p,frames+offset,sizeof(frames)-offset);while(!voice_mp3_player_finish(&p))TEST_ASSERT_FALSE(p.failed);voice_mp3_player_close(&p);TEST_ASSERT_TRUE(output>0);}
static int empty_decode(void*d,const uint8_t*p,size_t n,int16_t*out,size_t cap,unsigned*rate,unsigned*channels){
 (void)d;(void)p;(void)n;(void)out;(void)cap;(void)rate;(void)channels;return 0;
}
static void empty_pcm(void){voice_mp3_player_t p;voice_mp3_decoder_t empty=ops;empty.decode=empty_decode;
 TEST_ASSERT_TRUE(voice_mp3_player_init(&p,&empty,sink,NULL));voice_mp3_player_feed(&p,frames,sizeof(frames));
 TEST_ASSERT_FALSE(voice_mp3_player_finish(&p));voice_mp3_player_close(&p);}
static void invalid_id3(void){
 for(unsigned version=2;version<=4;version++){
  voice_mp3_player_t p;uint8_t tag[10]={'I','D','3',version,0,16,0,0,0,0};
  TEST_ASSERT_TRUE(voice_mp3_player_init(&p,&ops,sink,NULL));voice_mp3_player_feed(&p,tag,10);
  TEST_ASSERT_EQUAL(version!=4,p.failed);voice_mp3_player_close(&p);
 }
}
static void id3(void){voice_mp3_player_t p;uint8_t id3[10]={'I','D','3',4,0,0,0,0,0,3};TEST_ASSERT_TRUE(voice_mp3_player_init(&p,&ops,sink,NULL));for(unsigned i=0;i<10;i++)TEST_ASSERT_EQUAL_UINT(1,voice_mp3_player_feed(&p,id3+i,1));uint8_t tag[3]={0};voice_mp3_player_feed(&p,tag,3);voice_mp3_player_feed(&p,frames,sizeof(frames));TEST_ASSERT_TRUE(voice_mp3_player_finish(&p));voice_mp3_player_close(&p);}
static double tone_energy(unsigned frequency) {
 voice_mp3_player_t p;tone_hz=frequency;output=measured=0;energy=0;
 TEST_ASSERT_TRUE(voice_mp3_player_init(&p,&ops,sink,NULL));
 for(unsigned i=0;i<100;i++)TEST_ASSERT_EQUAL_UINT(sizeof(frames),voice_mp3_player_feed(&p,frames,sizeof(frames)));
 TEST_ASSERT_TRUE(voice_mp3_player_finish(&p));
 voice_mp3_player_close(&p);
 return sqrt(energy/measured);
}
static void resampler_alias_rejection(void) {
 double speech=tone_energy(1000),alias=tone_energy(20000);
 TEST_ASSERT_TRUE(speech>8000);
 TEST_ASSERT_TRUE(alias/speech<.02);
}
static void gapless_metadata_is_informational(void) {
 voice_mp3_player_t p;
 memcpy(frames+21,"Xing",4);frames[28]=1;frames[32]=3;
 memcpy(frames+33,"LAME3.100",9);
 frames[54]=36;frames[55]=0;frames[56]=100; /* delay576, padding100 */
 TEST_ASSERT_TRUE(voice_mp3_player_init(&p,&ops,sink,NULL));
 voice_mp3_player_feed(&p,frames,sizeof(frames));TEST_ASSERT_TRUE(voice_mp3_player_finish(&p));
 TEST_ASSERT_TRUE(p.gapless_metadata);TEST_ASSERT_EQUAL_UINT(576,p.encoder_delay);
 TEST_ASSERT_EQUAL_UINT(100,p.encoder_padding);TEST_ASSERT_EQUAL_UINT(1881*2,output);
 voice_mp3_player_close(&p);
}
static void *open_oom(void) {return NULL;}
static void oom_and_cancel_release(void) {
 voice_mp3_player_t p;voice_mp3_decoder_t fail=ops;fail.open=open_oom;
 TEST_ASSERT_FALSE(voice_mp3_player_init(&p,&fail,sink,NULL));voice_mp3_player_close(&p);
 TEST_ASSERT_EQUAL_UINT(0,closed);
 TEST_ASSERT_TRUE(voice_mp3_player_init(&p,&ops,sink,NULL));limit=0;
 TEST_ASSERT_EQUAL_UINT(417,voice_mp3_player_feed(&p,frames,sizeof(frames)));
 voice_mp3_player_close(&p);voice_mp3_player_close(&p);
 TEST_ASSERT_EQUAL_UINT(1,closed);
}
int main(void){UNITY_BEGIN();RUN_TEST(splits);RUN_TEST(truncated);RUN_TEST(corrupt);RUN_TEST(backpressure);RUN_TEST(id3);RUN_TEST(empty_pcm);RUN_TEST(invalid_id3);RUN_TEST(resampler_alias_rejection);RUN_TEST(gapless_metadata_is_informational);RUN_TEST(oom_and_cancel_release);return UNITY_END();}
