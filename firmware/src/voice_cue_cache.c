#include "voice_cue_cache.h"
#include <string.h>
bool voice_cue_metadata_valid(size_t size, int rate, int channels, int bits, const char *sha) {
 if (!size || size>VOICE_CUE_MAX_BYTES || (size&1) || rate!=24000 || channels!=1 || bits!=16 || !sha || strlen(sha)!=64) return false;
 for(unsigned i=0;i<64;i++) if(!((sha[i]>='0'&&sha[i]<='9')||(sha[i]>='a'&&sha[i]<='f'))) return false;
 return true;
}
bool voice_cue_slot_publish(voice_cue_slot_t *s,uint8_t *pcm,size_t size,uint8_t **old) {
 *old=NULL;
 if(s->readers || !pcm || !size || size>VOICE_CUE_MAX_BYTES || (size&1))return false;
 *old=s->pcm;s->pcm=pcm;s->size=size;s->codec=VOICE_CUE_PCM16;return true;
}
const uint8_t *voice_cue_slot_acquire(voice_cue_slot_t *s,size_t *size) {
 *size=s->size;if(s->pcm)s->readers++;return s->pcm;
}
void voice_cue_slot_release(voice_cue_slot_t *s){if(s->readers)s->readers--;}

const char *voice_cue_name(voice_cue_name_t name) {
 static const char *names[]={"listening","processing","offline","ready","done","cancelled",
  "transcribing","thinking","synthesizing","answering","error","timeout","recognition_error","synthesis_error"};
 return (unsigned)name<VOICE_CUE_COUNT ? names[name] : NULL;
}
bool voice_cue_bank_publish_codec(voice_cue_bank_t *bank,voice_cue_name_t name,uint8_t *data,size_t size,voice_cue_codec_t codec,uint8_t **old){
 *old=NULL;
 if(!bank||!voice_cue_name(name)||!data||!size)return false;
 if(codec==VOICE_CUE_PCM16)return voice_cue_slot_publish(&bank->slots[name],data,size,old);
 if((codec!=VOICE_CUE_OPUS && codec!=VOICE_CUE_MP3)||
    size>(codec==VOICE_CUE_MP3?VOICE_CUE_MAX_BYTES:65536)||size<4||bank->slots[name].readers)return false;
 voice_cue_slot_t *s=&bank->slots[name];*old=s->pcm;s->pcm=data;s->size=size;s->codec=codec;return true;
}
voice_cue_audio_t voice_cue_bank_acquire_audio(voice_cue_bank_t *bank,voice_cue_name_t name){
 voice_cue_audio_t audio={0};if(!bank||!voice_cue_name(name))return audio;
 voice_cue_slot_t *s=&bank->slots[name];
 if(s->pcm){s->readers++;audio=(voice_cue_audio_t){s->pcm,s->size,s->codec};}
 return audio;
}
bool voice_cue_bank_publish(voice_cue_bank_t *bank,voice_cue_name_t name,uint8_t *pcm,size_t size,uint8_t **old) {
 *old=NULL;
 return bank && voice_cue_name(name) && voice_cue_slot_publish(&bank->slots[name],pcm,size,old);
}
const uint8_t *voice_cue_bank_acquire(voice_cue_bank_t *bank,voice_cue_name_t name,size_t *size) {
 *size=0;
 return bank && voice_cue_name(name) && bank->slots[name].codec==VOICE_CUE_PCM16 ? voice_cue_slot_acquire(&bank->slots[name],size) : NULL;
}
void voice_cue_bank_release(voice_cue_bank_t *bank,voice_cue_name_t name) {
 if(bank && voice_cue_name(name))voice_cue_slot_release(&bank->slots[name]);
}
const uint8_t *voice_cue_fallback_named(voice_cue_name_t name,size_t *size) {
 /* Three generated80ms patterns: rising ready, low error trill, progress.
  * No speech, dynamic allocation or shared mutable playback buffer. */
 static uint8_t pcm[3][3840];static bool initialized;
 if(!initialized){for(unsigned kind=0;kind<3;kind++)for(unsigned i=0;i<1920;i++){
  unsigned period=kind==1?(i<960?40:20):kind==2?80:24;
  bool audible=kind!=2 || (i/240)%2==0;
  int16_t sample=audible?((i%period)<period/2?4000:-4000):0;
  pcm[kind][2*i]=(uint8_t)sample;pcm[kind][2*i+1]=(uint8_t)(sample>>8);
 }initialized=true;}
 unsigned kind=(name==VOICE_CUE_READY||name==VOICE_CUE_DONE)?1:
  (name==VOICE_CUE_OFFLINE||name>=VOICE_CUE_ERROR)?2:0;
 *size=sizeof(pcm[0]);return pcm[kind];
}
const uint8_t *voice_cue_fallback(size_t *size){return voice_cue_fallback_named(VOICE_CUE_LISTENING,size);}
