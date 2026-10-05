#ifndef VOICE_DIAGNOSTICS_H
#define VOICE_DIAGNOSTICS_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define VOICE_DIAG_EVENT_CAPACITY 64u

typedef enum {
  VOICE_DIAG_RECORDING_STARTED = 1,
  VOICE_DIAG_REC_RING_OVERFLOW = 2,
  VOICE_DIAG_UPLOAD_QUEUE_ERROR = 3,
  VOICE_DIAG_UPLOAD_SOCKET_ERROR = 4,
  VOICE_DIAG_WG_TIME_WAIT = 5,
  VOICE_DIAG_WG_HANDSHAKE_TIMEOUT = 6,
  VOICE_DIAG_TURN_RECOVERY_TIMEOUT = 7,
  VOICE_DIAG_UPLOAD_COMPLETED = 8,
  VOICE_DIAG_TURN_FAILED = 9,
} voice_diag_code_t;

typedef struct {
  uint32_t uptime_ms;
  voice_diag_code_t code;
  uint32_t arg0;
  uint32_t arg1;
} voice_diag_event_t;

typedef struct {
  uint32_t recording_id;
  uint32_t captured_bytes;
  uint32_t queued_bytes;
  uint32_t sent_bytes;
  uint32_t ring_high_water_bytes;
  uint32_t upload_high_water_bytes;
  uint32_t write_max_ms;
  voice_diag_code_t last_error_code;
  uint32_t event_count;
  voice_diag_event_t events[VOICE_DIAG_EVENT_CAPACITY];
} voice_diag_snapshot_t;

/* No allocation, flash writes, networking, free-form text, or secrets. */
void voice_diag_reset(void);
void voice_diag_event(voice_diag_code_t code, uint32_t uptime_ms,
                      uint32_t arg0, uint32_t arg1);
void voice_diag_begin_recording(uint32_t uptime_ms);
void voice_diag_record_capture(uint32_t bytes, uint32_t ring_bytes);
void voice_diag_record_queue(uint32_t bytes, uint32_t upload_bytes);
void voice_diag_record_send(uint32_t bytes, uint32_t elapsed_ms);
void voice_diag_snapshot(voice_diag_snapshot_t *out);
void voice_diag_restore_last_error(voice_diag_code_t code);
#ifdef ESP_PLATFORM
void voice_diag_load_last_error(void);
void voice_diag_persist_last_error(void);
#endif
/* Decimal numeric fields only. Returns false if the buffer cannot hold all events. */
bool voice_diag_snapshot_json(const voice_diag_snapshot_t *snapshot,
                              char *out, size_t capacity);

#endif
