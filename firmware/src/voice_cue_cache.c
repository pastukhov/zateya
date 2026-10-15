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
