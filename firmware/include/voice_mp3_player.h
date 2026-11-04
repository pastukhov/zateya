#ifndef VOICE_MP3_PLAYER_H
#define VOICE_MP3_PLAYER_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define VOICE_MP3_MAX_BYTES (16U*1024U*1024U)
#define VOICE_MP3_MAX_FRAME 2048U
#define VOICE_MP3_PCM_SAMPLES 2304U
/* One persistent decoder per stream, including its Layer III bit reservoir. */
typedef struct {
 void *(*open)(void);
 int (*decode)(void *,const uint8_t *,size_t,int16_t *,size_t,unsigned *,unsigned *);
 void (*close)(void *);
} voice_mp3_decoder_t;
typedef size_t (*voice_mp3_sink_t)(void *,const uint8_t *,size_t);
typedef struct {
 const voice_mp3_decoder_t *ops;void *decoder;
 voice_mp3_sink_t sink;void *ctx;
 uint8_t input[VOICE_MP3_MAX_FRAME];size_t used,needed,total,skip;
 unsigned rate,channels,version,frames;
 bool header_checked,failed,finished;
 /* Informational until target decoder delay is physically validated. */
 bool gapless_metadata;
 uint16_t encoder_delay,encoder_padding;
 uint32_t declared_frames;
 int16_t decoded[VOICE_MP3_PCM_SAMPLES],output[2304];size_t queued,sent;
 /* FIR anti-alias filter followed by rational linear interpolation. */
 float taps[32],history[32],previous;unsigned history_pos;
 uint64_t input_samples,next_output,pcm_samples;
} voice_mp3_player_t;
const voice_mp3_decoder_t *voice_mp3_decoder(void);
bool voice_mp3_player_init(voice_mp3_player_t *,const voice_mp3_decoder_t *,voice_mp3_sink_t,void *);
size_t voice_mp3_player_feed(voice_mp3_player_t *,const uint8_t *,size_t);
bool voice_mp3_player_finish(voice_mp3_player_t *);
void voice_mp3_player_close(voice_mp3_player_t *);
/* Structural check without decoding, for staging before the decoder pass. */
bool voice_mp3_frame_header(const uint8_t *,size_t,unsigned *,unsigned *,unsigned *,size_t *);
#endif
