#ifndef VOICE_CUE_OPUS_H
#define VOICE_CUE_OPUS_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define VOICE_OPUS_MAX_BYTES 65536U
#define VOICE_OPUS_FRAME_SAMPLES 480U
#define VOICE_OPUS_MAX_SAMPLES 120000U
#define VOICE_OPUS_MAX_PACKETS 252U
typedef struct {uint32_t samples;uint16_t preskip,count;size_t offset;unsigned packet;} voice_cue_opus_t;
typedef struct {
 void *(*open)(void);
 int (*decode)(void *,const uint8_t *,size_t,int16_t out[480]);
 void (*close)(void *);
} voice_cue_decoder_t;
bool voice_cue_opus_parse(const uint8_t *data,size_t size,voice_cue_opus_t *opus);
bool voice_cue_opus_next(voice_cue_opus_t *opus,const uint8_t *data,size_t size,const uint8_t **packet,size_t *length);
const voice_cue_decoder_t *voice_cue_opus_decoder(void);
bool voice_cue_opus_validate(const uint8_t *data,size_t size,bool (*allowed)(void));
#endif
