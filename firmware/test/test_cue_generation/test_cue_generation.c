#define _POSIX_C_SOURCE 200809L
#include <unity.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dirent.h>
#include <sys/stat.h>
#include "voice_cue_generation.h"
#include "voice_mp3_player.h"
static char root[128];
static voice_cue_store_t store;
static bool hash(const uint8_t *data,size_t size,uint8_t digest[32]) {
 memset(digest,0,32);
 for(size_t i=0;i<size;i++)digest[i%32]^=data[i];
 return true;
}
void setUp(void) {
 strcpy(root,"/tmp/zateya-generation-test-XXXXXX");
 TEST_ASSERT_NOT_NULL(mkdtemp(root));
 TEST_ASSERT_TRUE(voice_cue_store_init(&store,root,hash));
}
void tearDown(void) {
 DIR *d=opendir(root);struct dirent *e;
 while(d&&(e=readdir(d))) {
  if(e->d_name[0]=='.')continue;
  char path[512];snprintf(path,sizeof(path),"%s/%s",root,e->d_name);unlink(path);
 }
 if(d)closedir(d);
 rmdir(root);
}
static void prepare(voice_cue_generation_t *g,char id,uint8_t *data,size_t size) {
 memset(g,0,sizeof(*g));memset(g->id,id,64);g->id[64]=0;
 uint8_t digest[32];hash(data,size,digest);
 for(unsigned i=0;i<VOICE_CUE_COUNT;i++) {
  g->size[i]=size;
  g->bank.slots[i]=(voice_cue_slot_t){.pcm=data,.size=size,.codec=VOICE_CUE_MP3};
  for(unsigned j=0;j<32;j++)snprintf(g->sha[i]+j*2,3,"%02x",digest[j]);
 }
}
static bool active_is(const char *expected) {
 char path[256],data[256];snprintf(path,sizeof(path),"%s/active-generation.json",root);
 FILE *f=fopen(path,"rb");if(!f)return false;
 size_t n=fread(data,1,sizeof(data)-1,f);fclose(f);data[n]=0;
 return !strcmp(data,expected);
}
static void atomic_generation(void) {
 voice_cue_generation_t old,next;uint8_t a[40]={1},b[48]={2};
 prepare(&old,'a',a,sizeof(a));prepare(&next,'b',b,sizeof(b));
 for(unsigned i=0;i<VOICE_CUE_COUNT;i++)TEST_ASSERT_TRUE(voice_cue_generation_write(&store,&old,i));
 TEST_ASSERT_TRUE(voice_cue_generation_commit(&store,&old,"old-complete"));
 TEST_ASSERT_TRUE(active_is("old-complete"));
 for(unsigned i=0;i<VOICE_CUE_COUNT;i++) {
  /* Power cut at any completed file keeps the old pointer unchanged. */
  TEST_ASSERT_TRUE(active_is("old-complete"));
  TEST_ASSERT_FALSE(voice_cue_generation_commit(&store,&next,"new-complete"));
  TEST_ASSERT_TRUE(voice_cue_generation_write(&store,&next,i));
 }
 TEST_ASSERT_TRUE(voice_cue_generation_commit(&store,&next,"new-complete"));
 TEST_ASSERT_TRUE(active_is("new-complete"));
 voice_cue_generation_clean(&store,next.id);
 char path[256];snprintf(path,sizeof(path),"%s/%s_listening.mp3",root,old.id);
 TEST_ASSERT_TRUE(access(path,F_OK)!=0);
 snprintf(path,sizeof(path),"%s/%s_listening.mp3",root,next.id);
 TEST_ASSERT_EQUAL_INT(0,access(path,F_OK));
}
static void insufficient_space(void) {
 voice_cue_generation_t g;uint8_t data[40]={1};prepare(&g,'a',data,sizeof(data));
 store.limit=2*VOICE_CUE_MANIFEST_MAX+VOICE_CUE_COUNT*sizeof(data)+sizeof(data)-1;
 TEST_ASSERT_FALSE(voice_cue_generation_has_space(&store,&g));
 store.limit++;
 TEST_ASSERT_TRUE(voice_cue_generation_has_space(&store,&g));
}
static void hash_failure(void) {
 voice_cue_generation_t g;uint8_t data[40]={1};prepare(&g,'a',data,sizeof(data));data[3]=4;
 TEST_ASSERT_FALSE(voice_cue_generation_write(&store,&g,0));
 TEST_ASSERT_FALSE(voice_cue_generation_commit(&store,&g,"broken"));
}
#ifdef VOICE_CUE_HOST_JSON
static void *open_decoder(void) {return (void *)1;}
static int decode_fixture(void *ctx,const uint8_t *data,size_t size,int16_t *pcm,
    size_t capacity,unsigned *rate,unsigned *channels) {
 (void)ctx;(void)size;(void)capacity;
 unsigned version;size_t bytes;
 if(!voice_mp3_frame_header(data,4,rate,channels,&version,&bytes))return -1;
 memset(pcm,0,1152* *channels*sizeof(*pcm));
 return 1152* *channels;
}
static void close_decoder(void *ctx) {(void)ctx;}
const voice_mp3_decoder_t *voice_mp3_decoder(void) {
 static const voice_mp3_decoder_t ops={open_decoder,decode_fixture,close_decoder};
 return &ops;
}
static void manifest_for(const voice_cue_generation_t *g,char out[8192]) {
 size_t used=snprintf(out,8192,"{\"generation_id\":\"%s\",\"codec\":\"mp3\",\"status\":\"ready\",\"items\":{",g->id);
 for(unsigned i=0;i<VOICE_CUE_COUNT;i++) {
  used+=snprintf(out+used,8192-used,"%s\"%s\":{\"sha256\":\"%s\",\"size\":%u,\"duration_ms\":26,\"sample_rate\":44100,\"channels\":1}",
    i?",":"",voice_cue_name((voice_cue_name_t)i),g->sha[i],(unsigned)g->size[i]);
 }
 snprintf(out+used,8192-used,"}}");
}
static void full_reload_and_corruption(void) {
 uint8_t data[417]={255,251,144,192};voice_cue_generation_t g,loaded={0};char manifest[8192];
 prepare(&g,'a',data,sizeof(data));manifest_for(&g,manifest);
 TEST_ASSERT_TRUE(voice_cue_generation_parse(manifest,&loaded));
 for(unsigned i=0;i<VOICE_CUE_COUNT;i++)TEST_ASSERT_TRUE(voice_cue_generation_write(&store,&g,i));
 TEST_ASSERT_TRUE(voice_cue_generation_commit(&store,&g,manifest));
 TEST_ASSERT_TRUE(voice_cue_generation_load(&store,&loaded));
 TEST_ASSERT_EQUAL_STRING(g.id,loaded.id);
 for(unsigned i=0;i<VOICE_CUE_COUNT;i++)TEST_ASSERT_EQUAL_UINT(VOICE_CUE_MP3,loaded.bank.slots[i].codec);
 voice_cue_generation_free(&loaded);
 char file[256];snprintf(file,sizeof(file),"%s/%s_done.mp3",root,g.id);
 FILE *f=fopen(file,"r+b");TEST_ASSERT_NOT_NULL(f);fputc(0,f);fclose(f);
 TEST_ASSERT_FALSE(voice_cue_generation_load(&store,&loaded));
 for(unsigned i=0;i<VOICE_CUE_COUNT;i++)TEST_ASSERT_NULL(loaded.bank.slots[i].pcm);
}
#endif
int main(void) {UNITY_BEGIN();RUN_TEST(atomic_generation);RUN_TEST(insufficient_space);RUN_TEST(hash_failure);
#ifdef VOICE_CUE_HOST_JSON
RUN_TEST(full_reload_and_corruption);
#endif
return UNITY_END();}
