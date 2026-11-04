#include "voice_cue_opus.h"
#include <string.h>
static unsigned u16(const uint8_t *p){return p[0]|((unsigned)p[1]<<8);}
static uint32_t u32(const uint8_t *p){return p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static bool duration20(const uint8_t *packet,size_t n){
 if(n<2)return false;
 unsigned config=packet[0]>>3,code=packet[0]&3;
 unsigned samples=config>=16?(60U<<(config&3)):config>=12?(240U<<(config&1)):
  (config&3)==3?1440U:(240U<<(config&3));
 unsigned frames=code==0?1:code==3?(packet[1]&63):2;
 return frames && samples*frames==480;
}
bool voice_cue_opus_next(voice_cue_opus_t *o,const uint8_t *data,size_t size,const uint8_t **packet,size_t *length){
 if(!o||!data||!packet||!length||o->packet>=o->count||o->offset>size||size-o->offset<2)return false;
 unsigned n=u16(data+o->offset);size_t start=o->offset+2;
 if(n<2||n>1275||n>size-start||!duration20(data+start,n))return false;
 *packet=data+start;*length=n;o->offset=start+n;o->packet++;return true;
}
bool voice_cue_opus_parse(const uint8_t *data,size_t size,voice_cue_opus_t *o){
 if(!data||!o||size<34||size>65536||memcmp(data,"VCOPUS1\0",8)||u16(data+8)!=1||
    u16(data+10)!=1||u32(data+12)!=24000||u16(data+22)!=480||u16(data+26)||u32(data+28)!=24000)return false;
 voice_cue_opus_t parsed={.samples=u32(data+16),.preskip=u16(data+20),.count=u16(data+24),.offset=32};
 if(!parsed.samples||parsed.samples>120000||parsed.preskip>960||!parsed.count||parsed.count>252||
    parsed.count!=(parsed.samples+parsed.preskip+479)/480)return false;
 voice_cue_opus_t scan=parsed;const uint8_t *packet;size_t length;
 while(scan.packet<scan.count)if(!voice_cue_opus_next(&scan,data,size,&packet,&length))return false;
 if(scan.offset!=size)return false;
 *o=parsed;return true;
}
