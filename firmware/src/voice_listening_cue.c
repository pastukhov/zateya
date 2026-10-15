#include "voice_listening_cue.h"
#include "hardware.h"

bool voice_listening_cue_start(voice_listening_cue_t *c, const uint8_t *pcm,
                              size_t size, uint32_t now) {
  if (c->status == CUE_BUSY || !pcm || !size || (size & 1) || size > 240000)
    return false;
  *c = (voice_listening_cue_t){.pcm=pcm,.size=size,.started_ms=now,.status=CUE_BUSY};
  hw_audio_capture_stop();
  hw_audio_playback_start(NULL, 0);
  return true;
}
void voice_listening_cue_cancel(voice_listening_cue_t *c) {
  if (c->status == CUE_BUSY) hw_audio_playback_stop();
  c->status = CUE_ERROR;
}
voice_cue_status_t voice_listening_cue_tick(voice_listening_cue_t *c, uint32_t now) {
  if (c->status != CUE_BUSY) return c->status;
  if ((uint32_t)(now-c->started_ms) >= 8000) {
    voice_listening_cue_cancel(c);
    return c->status;
  }
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
  }
  return c->status;
}
