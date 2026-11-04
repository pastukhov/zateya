#include "voice_mp3_player.h"
#ifdef ESP_PLATFORM
#include "esp_mp3_dec.h"
static void *open_decoder(void){void *d=NULL;return esp_mp3_dec_open(NULL,0,&d)==ESP_AUDIO_ERR_OK?d:NULL;}
static int decode(void *d,const uint8_t *data,size_t size,int16_t *pcm,size_t capacity,unsigned *rate,unsigned *channels){
 esp_audio_dec_in_raw_t raw={.buffer=(uint8_t*)data,.len=size,.frame_recover=ESP_AUDIO_DEC_RECOVERY_NONE};
 esp_audio_dec_out_frame_t frame={.buffer=(uint8_t*)pcm,.len=capacity*2};esp_audio_dec_info_t info={0};
 esp_audio_err_t error=esp_mp3_dec_decode(d,&raw,&frame,&info);
 if(error!=ESP_AUDIO_ERR_OK||raw.consumed!=size||frame.decoded_size>capacity*2||(frame.decoded_size&1)||
    (frame.decoded_size&&info.bits_per_sample!=16))return -1;
 *rate=info.sample_rate;*channels=info.channel;return frame.decoded_size/2;
}
static void close_decoder(void *d){esp_mp3_dec_close(d);}
const voice_mp3_decoder_t *voice_mp3_decoder(void){static const voice_mp3_decoder_t ops={open_decoder,decode,close_decoder};return &ops;}
#else
const voice_mp3_decoder_t *voice_mp3_decoder(void){return NULL;}
#endif
