#include "voice_vad.h"
#include <string.h>
#include "webrtc/common_audio/vad/include/webrtc_vad.h"
static VadInst *vad;
static int16_t frame[160];
static size_t used;
static bool ready;
bool voice_vad_reset(void) {
 if(!vad && WebRtcVad_Create(&vad)!=0)return false;
 used=0;ready=vad && WebRtcVad_Init(vad)==0 && WebRtcVad_set_mode(vad,2)==0;
 return ready;
}
bool voice_vad_ready(void){return ready;}
bool voice_vad_feed(const uint8_t *pcm,size_t bytes) {
 bool speech=false;if(!ready)return false;
 while(bytes) {
  size_t n=sizeof(frame)-used;if(n>bytes)n=bytes;
  memcpy((uint8_t*)frame+used,pcm,n);used+=n;pcm+=n;bytes-=n;
  if(used==sizeof(frame)) {
   int result=WebRtcVad_Process(vad,16000,frame,160);used=0;
   if(result<0){ready=false;return false;}
   if(result>0)speech=true;
  }
 }
 return speech;
}
