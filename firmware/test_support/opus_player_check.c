#include "voice_listening_cue.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
extern void *opus_decoder_create(int,int,int*);
extern int opus_decode(void*,const unsigned char*,int,short*,int,int);
extern void opus_decoder_destroy(void*);
static unsigned char output[240000];static size_t used;static int releases,opens,closes,writes;static bool drained;
void hw_audio_capture_stop(void){}
void hw_audio_playback_start(const void *data,size_t size){(void)data;(void)size;}
void hw_audio_playback_stop(void){}
bool hw_audio_playback_drained(void){return drained;}
size_t hw_audio_playback_write(const uint8_t *p,size_t n){size_t limits[]={0,2,126,960};size_t take=limits[writes++%4];if(take>n)take=n;assert(used+take<=sizeof(output));memcpy(output+used,p,take);used+=take;return take;}
static void *open_dec(void){int error;void *d=opus_decoder_create(24000,1,&error);assert(d&&!error);opens++;return d;}
static int decode(void*d,const uint8_t*p,size_t n,int16_t*out){return opus_decode(d,p,n,out,480,0);}
static void close_dec(void*d){closes++;opus_decoder_destroy(d);}
static void release(void *ctx){(void)ctx;releases++;}
int main(int argc,char **argv){const voice_cue_decoder_t ops={open_dec,decode,close_dec};
 for(int f=1;f<argc;f++){
  FILE *in=fopen(argv[f],"rb");assert(in);fseek(in,0,SEEK_END);size_t size=ftell(in);rewind(in);uint8_t *data=malloc(size);assert(fread(data,1,size,in)==size);fclose(in);
  voice_cue_opus_t parsed;assert(voice_cue_opus_parse(data,size,&parsed));
  int16_t *reference=calloc(parsed.count*480,2);void*d=open_dec();const uint8_t*packet;size_t n;unsigned i=0;
  while(voice_cue_opus_next(&parsed,data,size,&packet,&n)){assert(decode(d,packet,n,reference+480*i)==480);i++;}close_dec(d);
  voice_listening_cue_t player={0};used=0;writes=0;drained=false;int before=releases;
  assert(voice_listening_cue_start_opus(&player,data,size,0,&ops,release,NULL));
  for(unsigned tick=0;tick<7000 && used<parsed.samples*2;tick++)assert(voice_listening_cue_tick(&player,tick)==CUE_BUSY);
  assert(used==parsed.samples*2);assert(!memcmp(output,reference+parsed.preskip,used));assert(releases==before);
  drained=true;assert(voice_listening_cue_tick(&player,7001)==CUE_DONE);assert(releases==before+1&&opens==closes);
  for(unsigned cancel=0;cancel<20;cancel++){player=(voice_listening_cue_t){0};used=0;writes=0;drained=false;before=releases;
   assert(voice_listening_cue_start_opus(&player,data,size,0,&ops,release,NULL));
   for(unsigned tick=0;tick<cancel;tick++)voice_listening_cue_tick(&player,tick);
   voice_listening_cue_cancel(&player);voice_listening_cue_cancel(&player);assert(releases==before+1&&opens==closes);
  }
  free(reference);free(data);
 }
 printf("Real libopus + production C player: %d cues, exact PCM, partial/zero writes, drain and %d cancellations PASS\n",argc-1,20*(argc-1));
}
