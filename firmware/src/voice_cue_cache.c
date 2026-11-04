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
 *old=s->pcm;s->pcm=pcm;s->size=size;return true;
}
const uint8_t *voice_cue_slot_acquire(voice_cue_slot_t *s,size_t *size) {
 *size=s->size;if(s->pcm)s->readers++;return s->pcm;
}
void voice_cue_slot_release(voice_cue_slot_t *s){if(s->readers)s->readers--;}

const char *voice_cue_name(voice_cue_name_t name) {
 static const char *names[]={"listening","processing","offline"};
 return (unsigned)name<VOICE_CUE_COUNT ? names[name] : NULL;
}
bool voice_cue_bank_publish(voice_cue_bank_t *bank,voice_cue_name_t name,uint8_t *pcm,size_t size,uint8_t **old) {
 *old=NULL;
 return bank && voice_cue_name(name) && voice_cue_slot_publish(&bank->slots[name],pcm,size,old);
}
const uint8_t *voice_cue_bank_acquire(voice_cue_bank_t *bank,voice_cue_name_t name,size_t *size) {
 *size=0;
 return bank && voice_cue_name(name) ? voice_cue_slot_acquire(&bank->slots[name],size) : NULL;
}
void voice_cue_bank_release(voice_cue_bank_t *bank,voice_cue_name_t name) {
 if(bank && voice_cue_name(name))voice_cue_slot_release(&bank->slots[name]);
}
const uint8_t *voice_cue_fallback(size_t *size) {
 /* Small generated 80 ms signal, PCM16 mono24k. No speech payload. */
 static uint8_t signal[3840];static bool initialized;
 if(!initialized){for(unsigned i=0;i<sizeof(signal)/2;i++){
  int16_t sample=(i%24)<12?1000:-1000;
  signal[2*i]=(uint8_t)sample;signal[2*i+1]=(uint8_t)(sample>>8);
 }initialized=true;}
 *size=sizeof(signal);return signal;
}
