#include "voice_static_cues.h"
static uint32_t crc32(const uint8_t *data,size_t size){
 uint32_t crc=0xffffffffu;
 for(size_t i=0;i<size;i++){crc^=data[i];for(unsigned b=0;b<8;b++)crc=(crc>>1)^((crc&1)?0xedb88320u:0);}
 return ~crc;
}
bool voice_static_cue_valid(const uint8_t *pcm,size_t size,uint32_t crc){
 return pcm && size>0 && size<=240000 && !(size&1) && crc32(pcm,size)==crc;
}
#ifdef ESP_PLATFORM
#include "voice_static_cues_manifest.h"
extern const uint8_t listening_start[] asm("_binary_voice_listening_pcm_start");
extern const uint8_t listening_end[] asm("_binary_voice_listening_pcm_end");
extern const uint8_t processing_start[] asm("_binary_voice_processing_pcm_start");
extern const uint8_t processing_end[] asm("_binary_voice_processing_pcm_end");
extern const uint8_t offline_start[] asm("_binary_voice_offline_pcm_start");
extern const uint8_t offline_end[] asm("_binary_voice_offline_pcm_end");
#endif
const uint8_t *voice_static_cue_get(voice_static_cue_t name,size_t *size){
#ifdef ESP_PLATFORM
 const uint8_t *starts[]={listening_start,processing_start,offline_start};
 const uint8_t *ends[]={listening_end,processing_end,offline_end};
 static const uint32_t crcs[]={VOICE_LISTENING_CRC,VOICE_PROCESSING_CRC,VOICE_OFFLINE_CRC};
 static int checked[3];
 if(name>=VOICE_CUE_LISTENING && name<=VOICE_CUE_OFFLINE){
  unsigned i=(unsigned)name;size_t n=(size_t)(ends[i]-starts[i]);
  if(!checked[i])checked[i]=voice_static_cue_valid(starts[i],n,crcs[i])?1:-1;
  if(checked[i]>0){*size=n;return starts[i];}
 }
#endif
 /* A quiet 1 kHz signal, 80 ms, PCM16 mono 24 kHz. Never substituted speech. */
 static uint8_t signal[3840];static bool initialized;
 if(!initialized){for(unsigned i=0;i<sizeof(signal)/2;i++){
  int16_t sample=(i%24)<12?1000:-1000;
  signal[2*i]=(uint8_t)sample;signal[2*i+1]=(uint8_t)(sample>>8);
 }initialized=true;}
 *size=sizeof(signal);return signal;
}
