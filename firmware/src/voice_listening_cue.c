#include "voice_listening_cue.h"
#include "hardware.h"

static void release_lease(voice_listening_cue_t *c) {
  if(c->decoder){c->decoder_ops->close(c->decoder);c->decoder=NULL;}
  if(c->release){c->release(c->release_ctx);c->release=NULL;c->release_ctx=NULL;c->pcm=NULL;}
}
bool voice_listening_cue_start(voice_listening_cue_t *c, const uint8_t *pcm,
                              size_t size, uint32_t now) {
  if (c->status == CUE_BUSY || !pcm || !size || (size & 1) || size > 240000)
    return false;
  *c = (voice_listening_cue_t){.pcm=pcm,.size=size,.started_ms=now,.status=CUE_BUSY};
  hw_audio_capture_stop();
  hw_audio_playback_start(NULL, 0);
  return true;
}
bool voice_listening_cue_start_lease(voice_listening_cue_t *c,const uint8_t *pcm,
                                    size_t size,uint32_t now,
                                    void (*release)(void *ctx),void *ctx) {
  if(!voice_listening_cue_start(c,pcm,size,now)){
    if(release)release(ctx);
    return false;
  }
  c->release=release;c->release_ctx=ctx;
  return true;
}
bool voice_listening_cue_start_opus(voice_listening_cue_t *c,const uint8_t *data,size_t size,
                                   uint32_t now,const voice_cue_decoder_t *ops,
                                   void (*release)(void *ctx),void *ctx){
  voice_cue_opus_t parsed;
  if(c->status==CUE_BUSY||!ops||!ops->open||!ops->decode||!ops->close||!voice_cue_opus_parse(data,size,&parsed)){
    if(release)release(ctx);
    return false;
  }
  void *decoder=ops->open();
  if(!decoder){if(release)release(ctx);return false;}
  *c=(voice_listening_cue_t){.pcm=data,.size=size,.started_ms=now,.status=CUE_BUSY,
    .release=release,.release_ctx=ctx,.decoder_ops=ops,.decoder=decoder,.opus=parsed};
  hw_audio_capture_stop();hw_audio_playback_start(NULL,0);return true;
}
static voice_cue_status_t tick_opus(voice_listening_cue_t *c){
  if(c->queue_position==c->queued && c->opus.packet<c->opus.count){
    const uint8_t *packet;size_t length;
    if(!voice_cue_opus_next(&c->opus,c->pcm,c->size,&packet,&length)||
       c->decoder_ops->decode(c->decoder,packet,length,c->frame)!=480){voice_listening_cue_cancel(c);return c->status;}
    size_t start=c->decoded_index,end=start+480;
    size_t first=start<c->opus.preskip?c->opus.preskip-start:0;if(first>480)first=480;
    size_t limit=c->opus.preskip+c->opus.samples;
    size_t last=end>limit?(limit>start?limit-start:0):480;
    c->decoded_index=end;c->queue_position=first*2;c->queued=last*2;
    if(c->queue_position>c->queued)c->queue_position=c->queued;
  }
  size_t remaining=c->queued-c->queue_position;
  if(remaining){
    size_t written=hw_audio_playback_write((const uint8_t*)c->frame+c->queue_position,remaining);
    if(written>remaining||(written&1)){voice_listening_cue_cancel(c);return c->status;}
    c->queue_position+=written;c->position+=written;
  }
  if(c->opus.packet==c->opus.count && c->queue_position==c->queued && hw_audio_playback_drained()){
    hw_audio_playback_stop();c->status=CUE_DONE;release_lease(c);
  }
  return c->status;
}
void voice_listening_cue_cancel(voice_listening_cue_t *c) {
  if (c->status == CUE_BUSY) hw_audio_playback_stop();
  c->status = CUE_ERROR;
  release_lease(c);
}
voice_cue_status_t voice_listening_cue_tick(voice_listening_cue_t *c, uint32_t now) {
  if (c->status != CUE_BUSY) return c->status;
  if ((uint32_t)(now-c->started_ms) >= 8000) {
    voice_listening_cue_cancel(c);
    return c->status;
  }
  if(c->decoder)return tick_opus(c);
  size_t remaining = c->size-c->position;
  if (remaining) {
    size_t chunk = remaining > 1024 ? 1024 : remaining;
    size_t written = hw_audio_playback_write(c->pcm+c->position, chunk);
    if (written > chunk || (written & 1)) {
      voice_listening_cue_cancel(c);
      return c->status;
    }
    c->position += written;
  }
  if (c->position == c->size && hw_audio_playback_drained()) {
    hw_audio_playback_stop();
    c->status = CUE_DONE;
    release_lease(c);
  }
  return c->status;
}
