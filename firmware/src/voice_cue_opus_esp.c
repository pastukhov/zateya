#include "voice_cue_opus.h"
#ifdef ESP_PLATFORM
#include "esp_opus_dec.h"
static void *open_decoder(void){
 esp_opus_dec_cfg_t cfg={.sample_rate=24000,.channel=1,.frame_duration=ESP_OPUS_DEC_FRAME_DURATION_20_MS,.self_delimited=false};
 void *decoder=NULL;return esp_opus_dec_open(&cfg,sizeof(cfg),&decoder)==ESP_AUDIO_ERR_OK?decoder:NULL;
}
static int decode(void *decoder,const uint8_t *packet,size_t length,int16_t out[480]){
 esp_audio_dec_in_raw_t raw={.buffer=(uint8_t*)packet,.len=length,.frame_recover=ESP_AUDIO_DEC_RECOVERY_NONE};
 esp_audio_dec_out_frame_t frame={.buffer=(uint8_t*)out,.len=960};esp_audio_dec_info_t info={0};
 if(esp_opus_dec_decode(decoder,&raw,&frame,&info)!=ESP_AUDIO_ERR_OK||raw.consumed!=length||frame.decoded_size!=960||
    info.sample_rate!=24000||info.channel!=1||info.bits_per_sample!=16)return -1;
 return 480;
}
static void close_decoder(void *decoder){(void)esp_opus_dec_close(decoder);}
const voice_cue_decoder_t *voice_cue_opus_decoder(void){static const voice_cue_decoder_t ops={open_decoder,decode,close_decoder};return &ops;}
#else
const voice_cue_decoder_t *voice_cue_opus_decoder(void){return NULL;}
#endif
bool voice_cue_opus_validate(const uint8_t *data,size_t size,bool (*allowed)(void)){
 voice_cue_opus_t o;if(!voice_cue_opus_parse(data,size,&o))return false;
 const voice_cue_decoder_t *ops=voice_cue_opus_decoder();if(!ops)return false;
 void *decoder=ops->open();if(!decoder)return false;
 bool valid=true;int16_t frame[480];const uint8_t *packet;size_t length;
 while(o.packet<o.count){
  if((allowed&&!allowed())||!voice_cue_opus_next(&o,data,size,&packet,&length)||ops->decode(decoder,packet,length,frame)!=480){valid=false;break;}
 }
 ops->close(decoder);return valid;
}
