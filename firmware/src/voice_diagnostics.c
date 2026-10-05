#include "voice_diagnostics.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

#ifdef ESP_PLATFORM
#include "freertos/FreeRTOS.h"
static portMUX_TYPE diag_lock = portMUX_INITIALIZER_UNLOCKED;
#define DIAG_LOCK() portENTER_CRITICAL(&diag_lock)
#define DIAG_UNLOCK() portEXIT_CRITICAL(&diag_lock)
#else
#define DIAG_LOCK() ((void)0)
#define DIAG_UNLOCK() ((void)0)
#endif

static struct {
  voice_diag_snapshot_t data;
  uint32_t event_head;
  bool session_error_set;
} diag;

static void add_event(voice_diag_code_t code, uint32_t uptime_ms,
                      uint32_t arg0, uint32_t arg1) {
  uint32_t index = (diag.event_head + diag.data.event_count) % VOICE_DIAG_EVENT_CAPACITY;
  if (diag.data.event_count == VOICE_DIAG_EVENT_CAPACITY) {
    index = diag.event_head;
    diag.event_head = (diag.event_head + 1) % VOICE_DIAG_EVENT_CAPACITY;
  } else {
    diag.data.event_count++;
  }
  diag.data.events[index] = (voice_diag_event_t){uptime_ms, code, arg0, arg1};
  if (code >= VOICE_DIAG_REC_RING_OVERFLOW && code <= VOICE_DIAG_TURN_RECOVERY_TIMEOUT) {
    diag.data.last_error_code = code;
    diag.session_error_set = true;
  }
  if (code == VOICE_DIAG_TURN_FAILED) {
    diag.data.last_error_code = code;
    diag.session_error_set = true;
  }
}

void voice_diag_reset(void) {
  DIAG_LOCK();
  memset(&diag, 0, sizeof(diag));
  DIAG_UNLOCK();
}

void voice_diag_event(voice_diag_code_t code, uint32_t uptime_ms,
                      uint32_t arg0, uint32_t arg1) {
  DIAG_LOCK();
  add_event(code, uptime_ms, arg0, arg1);
  DIAG_UNLOCK();
}

void voice_diag_begin_recording(uint32_t uptime_ms) {
  DIAG_LOCK();
  diag.data.recording_id++;
  diag.data.captured_bytes = 0;
  diag.data.queued_bytes = 0;
  diag.data.sent_bytes = 0;
  diag.data.ring_high_water_bytes = 0;
  diag.data.upload_high_water_bytes = 0;
  diag.data.write_max_ms = 0;
  diag.session_error_set = false;
  add_event(VOICE_DIAG_RECORDING_STARTED, uptime_ms, diag.data.recording_id, 0);
  DIAG_UNLOCK();
}

void voice_diag_ensure_error(uint32_t uptime_ms) {
  DIAG_LOCK();
  if (!diag.session_error_set)
    add_event(VOICE_DIAG_TURN_FAILED, uptime_ms, 0, 0);
  DIAG_UNLOCK();
}

void voice_diag_clear_current_error(void) {
  DIAG_LOCK();
  diag.session_error_set = false;
  DIAG_UNLOCK();
}

void voice_diag_record_capture(uint32_t bytes, uint32_t ring_bytes) {
  DIAG_LOCK();
  diag.data.captured_bytes += bytes;
  if (ring_bytes > diag.data.ring_high_water_bytes)
    diag.data.ring_high_water_bytes = ring_bytes;
  DIAG_UNLOCK();
}

void voice_diag_record_queue(uint32_t bytes, uint32_t upload_bytes) {
  DIAG_LOCK();
  diag.data.queued_bytes += bytes;
  if (upload_bytes > diag.data.upload_high_water_bytes)
    diag.data.upload_high_water_bytes = upload_bytes;
  DIAG_UNLOCK();
}

void voice_diag_record_send(uint32_t bytes, uint32_t elapsed_ms) {
  DIAG_LOCK();
  diag.data.sent_bytes += bytes;
  if (elapsed_ms > diag.data.write_max_ms)
    diag.data.write_max_ms = elapsed_ms;
  DIAG_UNLOCK();
}

void voice_diag_snapshot(voice_diag_snapshot_t *out) {
  if (!out) return;
  DIAG_LOCK();
  *out = diag.data;
  for (uint32_t i = 0; i < out->event_count; ++i)
    out->events[i] = diag.data.events[(diag.event_head + i) % VOICE_DIAG_EVENT_CAPACITY];
  DIAG_UNLOCK();
}

voice_diag_code_t voice_diag_last_error(void) {
  DIAG_LOCK();
  voice_diag_code_t code = diag.data.last_error_code;
  DIAG_UNLOCK();
  return code;
}

void voice_diag_restore_last_error(voice_diag_code_t code) {
  if (code < VOICE_DIAG_REC_RING_OVERFLOW || code > VOICE_DIAG_TURN_FAILED ||
      code == VOICE_DIAG_UPLOAD_COMPLETED) return;
  DIAG_LOCK();
  diag.data.last_error_code = code;
  DIAG_UNLOCK();
}

bool voice_diag_snapshot_json(const voice_diag_snapshot_t *s,
                              char *out, size_t capacity) {
  if (!s || !out || !capacity || s->event_count > VOICE_DIAG_EVENT_CAPACITY)
    return false;
  int n = snprintf(out, capacity,
      "{\"recording_id\":%lu,\"captured_bytes\":%lu,\"queued_bytes\":%lu,"
      "\"sent_bytes\":%lu,\"ring_high_water_bytes\":%lu,"
      "\"upload_high_water_bytes\":%lu,\"write_max_ms\":%lu,"
      "\"last_error_code\":%u,\"events\":[",
      (unsigned long)s->recording_id, (unsigned long)s->captured_bytes,
      (unsigned long)s->queued_bytes, (unsigned long)s->sent_bytes,
      (unsigned long)s->ring_high_water_bytes,
      (unsigned long)s->upload_high_water_bytes,
      (unsigned long)s->write_max_ms, (unsigned)s->last_error_code);
  if (n < 0 || (size_t)n >= capacity) return false;
  size_t used = (size_t)n;
  for (uint32_t i = 0; i < s->event_count; ++i) {
    const voice_diag_event_t *e = &s->events[i];
    n = snprintf(out + used, capacity - used,
        "%s[%lu,%u,%lu,%lu]", i ? "," : "",
        (unsigned long)e->uptime_ms, (unsigned)e->code,
        (unsigned long)e->arg0, (unsigned long)e->arg1);
    if (n < 0 || (size_t)n >= capacity - used) return false;
    used += (size_t)n;
  }
  n = snprintf(out + used, capacity - used, "]}");
  return n == 2 && (size_t)n < capacity - used;
}
