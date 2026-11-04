/*
 * Voice Terminal — main application state machine (Milestone 1 loopback).
 *
 * States: BOOT -> IDLE -> RECORDING -> PROCESSING -> PLAYING -> IDLE,
 * with any state able to drop to ERROR and recover back to IDLE.
 *
 * This revision (M1-03/M1-04 integration) wires the previously stubbed
 * audio capture and playback actions to the real M1-03/M1-04 modules:
 *
 *   Capture (M1-03) : audio_capture (include/audio_capture.h) via the hw
 *                     seam (hw_audio_capture_start/stop/read). RECORDING
 *                     pulls freshly captured PCM once per tick and fans it
 *                     out to both the network-drain buffer (spec section
 *                     10/11, M2 upload — unchanged from the previous
 *                     revision) and a second buffer that holds the audio
 *                     for local playback, since Milestone 1 has no backend
 *                     to fetch a reply from (see "Loopback" below).
 *
 *   Playback (M1-04): audio_playback (include/audio_playback.h) via the hw
 *                     seam (hw_audio_playback_start/stop/write/drained).
 *                     PLAYING drains the loopback buffer to the speaker
 *                     once per tick and waits for the hardware to confirm
 *                     it has actually finished playing (not just queued)
 *                     before returning to IDLE.
 *
 *   Button read   : button_driver (include/button_driver.h), unchanged.
 *   State display : board_sticks3_display_update() renders the LCD.
 *
 * Loopback (Milestone 1 hardware smoke test): there is no backend turn to
 * fetch a reply from yet (networking is Milestone 2, out of scope here),
 * so M1's "reply" is simply the audio that was just recorded, played back
 * through the speaker. STATE_PROCESSING is therefore a single, immediate
 * tick that hands off to STATE_PLAYING — the real "wait for the backend"
 * logic lands with the M2 network wiring; the state exists now so the
 * transition table doesn't need to change again then.
 *
 * Buffering note: ATOM Echo has no PSRAM, so neither buffer below may hold
 * more than a short recording (RING_BUFFER_CAPACITY_DEFAULT each, spec
 * section 10). The M1 loopback scenario (a short spoken phrase) fits well
 * within that; a long recording will legitimately hit ring_buffer overflow
 * on one or both buffers exactly like the M2 upload path already handles.
 *
 * Non-goals in this revision: networking (Milestone 2, http_session stays
 * a pure state-tracking seam with no real transport), GPIO module
 * changes, and any refactor of the existing modules — this task only
 * wires main.c to the audio hw seam that board_atom_echo.c already backs
 * with the real M1-03/M1-04 modules.
 *
 * Recording path (spec sections 7 + 10):
 *   - Capture pushes into app.rb (ring_buffer, 32 KiB); the writer drains it
 *     into the HTTP session once per tick (M2 upload path, kept as-is).
 *   - Capture also pushes the same bytes into app.playback_rb, the M1
 *     loopback buffer M1-04 plays back once the turn finishes.
 *   - Sticky overflow flag (on app.rb) => stop recording immediately, stop
 *     the capture hardware, close the HTTP session gracefully when
 *     possible (abort fallback), show ERROR on the LCD, recover to
 *     IDLE only after a fresh button tap — no reboot.
 *   - MAX_RECORD_SECONDS (configurable, spec section 7): button_driver fires
 *     MAX_RECORD_TIMEOUT at the limit, which the RECORDING tick treats like a
 *     release, so the recording auto-finishes and the session closes.
 */

#include "voice_tls.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#ifdef ESP_PLATFORM
#include "esp_mac.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"
#include "esp_random.h"
#include "esp_timer.h"
#endif

#include "button_driver.h"
#include "hardware.h"
#include "http_session.h"
#include "http_voice_client.h"
#include "board_sticks3.h"
#include "voice_config_httpd.h"
#include "voice_settings.h"
#include "voice_turn_http.h"
#include "voice_gateway_health.h"
#include "voice_cue_cache.h"
#include "voice_wake_detector.h"
#include "voice_wake_policy.h"
#include "voice_listening_cue.h"
#include "voice_feedback_policy.h"
#include "voice_vad.h"
#include "voice_wake_ui.h"
#ifdef ESP_PLATFORM
#include "esp_wifi.h"
#include "esp_heap_caps.h"
#endif
#include "voice_diagnostics.h"
#include "voice_diag_delivery_esp.h"
#include "voice_ota.h"
#include "voice_turn_client.h"
#include "wav_parser.h"

#ifndef VOICE_WIFI_SSID
#define VOICE_WIFI_SSID ""
#endif
#ifndef VOICE_WIFI_PASSWORD
#define VOICE_WIFI_PASSWORD ""
#endif
#ifndef VOICE_GATEWAY_URL
#define VOICE_GATEWAY_URL "http://192.168.1.10:8000"
#endif
#ifndef VOICE_DEVICE_TOKEN
#define VOICE_DEVICE_TOKEN NULL
#endif
#include "ring_buffer.h"
#include "state_machine.h"

/* Ticks the app waits in BOOT before entering IDLE. */
#define APP_BOOT_TICKS 5u

typedef struct {
  state_machine_t sm;
  button_driver_t btn;
  uint32_t boot_ticks;
  bool error_ack_ready;
  bool error_ack_pressed;
  bool ignore_button_until_release;
  /* Recording path (spec section 10): network-drain buffer (M2 upload). */
  uint8_t rb_storage[RING_BUFFER_CAPACITY_DEFAULT];
  ring_buffer_t rb;
  http_session_t session;
  /* M1 loopback: holds what was just captured until M1-04 plays it back
   * (see file header "Loopback"). Filled in parallel with app.rb during
   * RECORDING, drained to the speaker during PLAYING. */
  uint8_t playback_storage[RING_BUFFER_CAPACITY_DEFAULT];
  ring_buffer_t playback_rb;
  /* One chunk the speaker hasn't accepted yet (hw_audio_playback_write is
   * all-or-nothing, see playback_drain()); kept here instead of losing or
   * reordering audio when the sink is momentarily full. */
  uint8_t playback_pending[256];
  size_t playback_pending_len;
  /*
   * Playback-side error flags (spec sections 8/13/38): sticky, set by the
   * test-simulation hooks below exactly like app.rb's ring-buffer-overflow
   * flag models a RECORDING-side failure. Real backend wiring lands with
   * M2 (see http_session.c file header); until then these flags are how
   * "backend connection dropped mid-stream" and "malformed WAV header on
   * the reply" are driven deterministically for host tests and, later, by
   * the real M2 download/parsing paths.
   */
  bool playback_conn_dropped;
  bool playback_bad_wav_header;
  /*
   * Playback position counter (spec section 8): total bytes handed to the
   * speaker so far this playback session. Reset to 0 by playback_start()
   * and, deterministically, by playback_release_resources() on every
   * PLAYING -> IDLE/ERROR exit, so a stale count from a finished turn can
   * never leak into the next one.
   */
  size_t playback_position;
  wav_parser_t wav;
#ifdef ESP_PLATFORM
  StreamBufferHandle_t turn_audio_stream;
  StreamBufferHandle_t turn_upload_stream;
  voice_turn_http_t turn_http;
  voice_turn_client_t turn_client;
  volatile voice_turn_result_t turn_result;
  volatile bool turn_task_active;
  volatile bool turn_cancel_requested;
  volatile bool turn_audio_started;
  volatile bool turn_upload_active;
  volatile bool turn_upload_finished;
  volatile bool turn_upload_release_requested;
  volatile bool turn_upload_failed;
  bool turn_http_ready;
  bool turn_fresh;
  volatile bool turn_storage_failed;
  bool turn_pending_byte;
  uint8_t turn_pending_value;
#endif
} app_t;

static app_t app;
static http_voice_client_t voice_client;
static voice_settings_t voice_settings;
#ifdef ESP_PLATFORM
static voice_wake_t wake;
static voice_listening_cue_t wake_cue;
static bool wake_listening, wake_active, wake_recording, wake_speech,wake_pending;
static unsigned wake_ui;
static voice_listening_cue_t feedback_cue;
static bool feedback_active;
static voice_feedback_t feedback;
static voice_cue_name_t feedback_current;
static bool idle_followup;
static char capture_answer_to[VOICE_TURN_ID_CAPACITY];
static void cue_release(void *ctx) {
  voice_cue_cache_release_named((voice_cue_name_t)(uintptr_t)ctx);
}
static bool local_cue_start(voice_listening_cue_t *cue,voice_cue_name_t name,uint32_t now) {
  size_t size=0;const uint8_t *pcm=voice_cue_cache_acquire_named(name,&size);
  bool acquired=pcm!=NULL;
  if(!pcm)pcm=voice_cue_fallback_named(name,&size);
  return voice_listening_cue_start_lease(cue,pcm,size,now,
      acquired?cue_release:NULL,(void*)(uintptr_t)name);
}
static bool voice_gate_acquire(void *ctx){(void)ctx;return voice_ota_voice_begin();}
static bool voice_gate_release(void *ctx){
  (void)ctx;if(voice_ota_boot_pending())return false;
  voice_ota_voice_end();return true;
}
static bool feedback_start(voice_cue_name_t name,uint32_t now) {
  if(feedback_active)return false;
  /* This application is the sole voice-gate owner: processing may retain
   * its existing lease; idle offline feedback must acquire one too. */
  if(!voice_feedback_claim_gate(&feedback,voice_gate_acquire,NULL))return false;
  voice_cue_cache_set_idle(false);
  feedback_active=local_cue_start(&feedback_cue,name,now);
  if(feedback_active)feedback_current=name;
  return feedback_active;
}
static bool feedback_tick(uint32_t now) {
  if(feedback_active && voice_listening_cue_tick(&feedback_cue,now)!=CUE_BUSY)
    feedback_active=false;
  return feedback_active;
}
static void feedback_cancel_routine(void) {
  voice_feedback_clear_routine(&feedback);
  if(feedback_active && !voice_feedback_is_error(feedback_current)){
    voice_listening_cue_cancel(&feedback_cue);feedback_active=false;
  }
}
static void feedback_request(voice_feedback_event_t event,voice_turn_error_t error,bool followup) {
  voice_feedback_event(&feedback,event,error,followup);
  if(event==FEEDBACK_ERROR && feedback_active && !voice_feedback_is_error(feedback_current)){
    voice_listening_cue_cancel(&feedback_cue);feedback_active=false;
  }
}
#define WAKE_PREROLL_BYTES 9600
static uint8_t *wake_preroll;
static bool wake_start_attempted;
static size_t wake_pre_used, wake_pre_head;
unsigned app_wake_status(void) { return wake_ui; }
static void wake_stop(void) {
  bool owned_gate=wake_active;
  if(wake_cue.status==CUE_BUSY)voice_listening_cue_cancel(&wake_cue);
  if(wake_listening || wake_active)hw_audio_capture_stop();
  wake_listening=false;wake_active=false;wake_pending=false;wake_ui=0;capture_answer_to[0]=0;
  if(owned_gate)voice_feedback_release_gate(&feedback,voice_gate_release,NULL);
  voice_wake_detector_reset();
  voice_wake_init(&wake,3000,MAX_RECORD_SECONDS_DEFAULT*1000U);
}
static void feedback_service(uint32_t now,state_t state) {
  if(wake_active || wake_recording || state==STATE_RECORDING || state==STATE_PLAYING)return;
  if(voice_feedback_pending(&feedback) && wake_listening)wake_stop();
  if(feedback_tick(now))return;
  voice_cue_name_t cue;
  if(voice_feedback_peek(&feedback,!wake_listening && !voice_ota_busy(),&cue) && feedback_start(cue,now))
    voice_feedback_started(&feedback,cue);
}
#else
unsigned app_wake_status(void) { return 0; }
#endif


#ifdef ESP_PLATFORM
static voice_turn_io_result_t turn_lookup(void *ctx, const char *request_id,
                                           voice_turn_response_t *response) {
  app_t *a = ctx;
  return voice_turn_http_ops()->lookup_request(&a->turn_http, request_id, response);
}
static voice_turn_io_result_t turn_poll(void *ctx, const char *turn_id,
                                         voice_turn_response_t *response) {
  app_t *a = ctx;
  return voice_turn_http_ops()->poll_turn(&a->turn_http, turn_id, response);
}
static voice_turn_io_result_t turn_download(void *ctx, const char *turn_id,
                                             voice_turn_response_t *response) {
  app_t *a = ctx;
  return voice_turn_http_ops()->download_audio(&a->turn_http, turn_id, response);
}
static voice_turn_io_result_t turn_cancel(void *ctx, const char *turn_id) {
  app_t *a = ctx;
  return voice_turn_http_ops()->cancel_turn(&a->turn_http, turn_id);
}
static bool turn_save_id(void *ctx, const char *turn_id) {
  app_t *a = ctx;
  if (strlcpy(voice_settings.turn_id, turn_id,
              sizeof(voice_settings.turn_id)) >= sizeof(voice_settings.turn_id))
    return false;
  if (voice_settings_save(&voice_settings) != ESP_OK) {
    a->turn_storage_failed = true;
    return false;
  }
  return true;
}
static void turn_clear_ids(void *ctx) {
  app_t *a = ctx;
  voice_settings.request_id[0] = '\0';
  voice_settings.turn_id[0] = '\0';
  if (voice_settings_save(&voice_settings) != ESP_OK) a->turn_storage_failed = true;
}
static const voice_turn_ops_t TURN_OPS = {
  .lookup_request = turn_lookup,
  .poll_turn = turn_poll,
  .download_audio = turn_download,
  .cancel_turn = turn_cancel,
  .save_turn_id = turn_save_id,
  .clear_ids = turn_clear_ids,
};

static void upload_recording(app_t *a) {
  uint8_t chunk[1024];
  http_session_init(&a->session);
  bool open = http_session_open(&a->session);
  if (!open) {
    a->turn_upload_failed = true;
    voice_diag_event(VOICE_DIAG_UPLOAD_SOCKET_ERROR,
                     (uint32_t)(esp_timer_get_time() / 1000), 0, 0);
  }
  while (open) {
    if (a->turn_upload_failed) break;
    size_t count = xStreamBufferReceive(a->turn_upload_stream, chunk,
                                        sizeof(chunk), pdMS_TO_TICKS(100));
    if (count) {
      uint32_t started = (uint32_t)(esp_timer_get_time() / 1000);
      if (http_session_write(&a->session, chunk, count) != count) {
        a->turn_upload_failed = true;
        voice_diag_event(VOICE_DIAG_UPLOAD_SOCKET_ERROR,
                         (uint32_t)(esp_timer_get_time() / 1000),
                         (uint32_t)count, (uint32_t)(esp_timer_get_time() / 1000) - started);
        break;
      }
      voice_diag_record_send((uint32_t)count,
                             (uint32_t)(esp_timer_get_time() / 1000) - started);
    }
    if (a->turn_upload_finished &&
        xStreamBufferBytesAvailable(a->turn_upload_stream) == 0) break;
  }
  if (open && !a->turn_upload_failed) {
    if (!http_session_close(&a->session)) {
      http_session_abort(&a->session);
      a->turn_upload_failed = true;
      voice_diag_event(VOICE_DIAG_UPLOAD_SOCKET_ERROR,
                       (uint32_t)(esp_timer_get_time() / 1000), 0, 0);
    } else if (http_voice_client_status(&voice_client) == 202) {
      voice_diag_event(VOICE_DIAG_UPLOAD_COMPLETED,
                       (uint32_t)(esp_timer_get_time() / 1000), 202, 0);
      const char *turn_id = http_voice_client_turn_id(&voice_client);
      if (turn_id && turn_id[0] && !turn_save_id(a, turn_id))
        a->turn_storage_failed = true;
    }
  } else if (open) {
    http_session_abort(&a->session);
  }
  a->turn_upload_active = false;
}

static void turn_worker(void *arg) {
  app_t *a = arg;
  if (a->turn_upload_active) {
    upload_recording(a);
    if (a->turn_upload_failed) {
      a->turn_result = VOICE_TURN_FAILED;
      a->turn_task_active = false;
      vTaskDelete(NULL);
      return;
    }
  }
  voice_turn_client_init(&a->turn_client, &TURN_OPS, a,
      voice_settings.request_id,
      voice_settings.turn_id[0] ? voice_settings.turn_id : NULL,
      (uint64_t)(esp_timer_get_time() / 1000ULL));
  if (a->turn_client.result == VOICE_TURN_FAILED) {
    a->turn_result = VOICE_TURN_FAILED;
    a->turn_task_active = false;
    vTaskDelete(NULL);
    return;
  }
  for (;;) {
    if (a->turn_cancel_requested && a->turn_client.turn_id[0]) {
      uint64_t now = (uint64_t)(esp_timer_get_time() / 1000ULL);
      a->turn_result = voice_turn_client_cancel(&a->turn_client, now);
      if (a->turn_result != VOICE_TURN_WAITING) break;
      vTaskDelay(pdMS_TO_TICKS(50));
      continue;
    }
    uint64_t now = (uint64_t)(esp_timer_get_time() / 1000ULL);
    a->turn_result = voice_turn_client_tick(&a->turn_client, now);
    if (a->turn_result != VOICE_TURN_WAITING) break;
    vTaskDelay(pdMS_TO_TICKS(50));
  }
  a->turn_task_active = false;
  vTaskDelete(NULL);
}

static bool start_turn_worker(bool upload_pending) {
  if (!app.turn_http_ready || !app.turn_audio_stream || !app.turn_upload_stream ||
      !voice_settings.request_id[0]) return false;
  if (app.turn_task_active) return true;
  xStreamBufferReset(app.turn_audio_stream);
  xStreamBufferReset(app.turn_upload_stream);
  app.turn_cancel_requested = false;
  app.turn_audio_started = false;
  app.turn_pending_byte = false;
  app.turn_storage_failed = false;
  app.turn_upload_failed = false;
  app.turn_upload_finished = !upload_pending;
  app.turn_upload_release_requested = false;
  app.turn_upload_active = upload_pending;
  /* Before upload, not only after it: never inherit prior server failure. */
  memset(&app.turn_client,0,sizeof(app.turn_client));
  app.turn_client.status=VOICE_TURN_STATUS_QUEUED;
  app.turn_fresh = upload_pending;
  app.turn_result = VOICE_TURN_WAITING;
  app.turn_task_active = true;
  if (xTaskCreate(turn_worker, "voice_turn", 8192, &app, 5, NULL) != pdPASS) {
    app.turn_task_active = false;
    return false;
  }
  return true;
}

static bool begin_turn_request(void) {
  uint8_t random_bytes[16];
  char request_id[VOICE_TURN_REQUEST_ID_CAPACITY];
  esp_fill_random(random_bytes, sizeof(random_bytes));
  if (!voice_turn_format_uuid(random_bytes, request_id, sizeof(request_id))) return false;
  strlcpy(voice_settings.request_id, request_id, sizeof(voice_settings.request_id));
  voice_settings.turn_id[0] = '\0';
  return voice_settings_save(&voice_settings) == ESP_OK;
}
#endif

static void enter_state(state_t next, const char* error_what) {
#ifdef ESP_PLATFORM
  state_t previous=state_machine_get_state(&app.sm);
#endif
  if (!state_machine_step(&app.sm, next)) {
    return; /* illegal transition: leave state, report if we can */
  }
#ifdef ESP_PLATFORM
  if(next==STATE_ERROR || next==STATE_IDLE)wake_recording=false;
  if(next==STATE_ERROR)app.turn_client.follow_up_listen=false;
#endif
  if (next == STATE_ERROR) {
#ifdef ESP_PLATFORM
    if(wake_active || wake_listening)wake_stop();
    hw_audio_capture_stop();
    if(app.turn_task_active) {
      app.turn_cancel_requested=true;
      app.turn_upload_failed=true;
      app.turn_upload_finished=true;
    }
    /* Main is the sole I2S owner. Release answer/cue speaker before queuing
     * an error; queue survives a temporarily held OTA gate. */
    hw_audio_playback_stop();
    if(feedback_active){voice_listening_cue_cancel(&feedback_cue);feedback_active=false;}
    voice_turn_error_t failure=app.turn_client.error;
    if(!board_sticks3_network_ready() || voice_gateway_health_status()==0)
      failure=VOICE_TURN_ERROR_CONNECTION;
    feedback_request(FEEDBACK_ERROR,failure,false);
#endif
    voice_diag_ensure_error(hw_clock_ms());
    app.error_ack_ready = false;
    app.error_ack_pressed = false;
    if (error_what) {
      hw_report_error(error_what);
    }
  }
#ifdef ESP_PLATFORM
  if(next==STATE_PROCESSING)feedback_request(FEEDBACK_PROCESSING,VOICE_TURN_ERROR_NONE,false);
  if(next==STATE_IDLE){
    bool cancelled=app.turn_cancel_requested || app.turn_result==VOICE_TURN_CANCELLED;
    voice_feedback_event_t event=previous==STATE_PLAYING?(cancelled?FEEDBACK_CANCELLED:FEEDBACK_DONE):
      previous==STATE_PROCESSING?FEEDBACK_CANCELLED:FEEDBACK_READY;
    feedback_request(event,VOICE_TURN_ERROR_NONE,idle_followup);
  }
#endif
  if (next == STATE_IDLE) {
    voice_diag_clear_current_error();
    button_reset(&app.btn); /* don't let a stale hold re-trigger */
  }
}

/*
 * Start of a recording session: clean both buffers, fresh HTTP session,
 * start the microphone (M1-03). The buffer reset also clears the sticky
 * overflow flag, so a previous overflow can never leak into a new
 * recording.
 */
static bool recording_start(void) {
#ifdef ESP_PLATFORM
  if (!voice_tls_ready() || !app.turn_http_ready) return false;
  if (app.turn_task_active) return false;
  if (!begin_turn_request()) return false;
#endif
  ring_buffer_reset(&app.rb);
  ring_buffer_reset(&app.playback_rb);
#ifdef ESP_PLATFORM
  {
    voice_diag_begin_recording(hw_clock_ms());
    if (!start_turn_worker(true)) return false;
    hw_audio_capture_start();
    return true;
  }
#else
  http_session_init(&app.session);
  if (!http_session_open(&app.session)) return false;
  voice_diag_begin_recording(hw_clock_ms());
  hw_audio_capture_start();
  return true;
#endif
}

#ifdef ESP_PLATFORM
/* Manual, wake and question answers share capture ownership/lifecycle.
 * Wake monitoring alone additionally requires USB power and a loaded detector. */
static bool capture_eligible(void) {
  wifi_mode_t mode=WIFI_MODE_NULL;
  return wake_preroll && esp_wifi_get_mode(&mode)==ESP_OK && mode==WIFI_MODE_STA &&
    board_sticks3_network_ready() && voice_tls_ready() && app.turn_http_ready &&
    !voice_ota_busy() && !voice_ota_boot_pending() && !app.turn_task_active &&
    !voice_diag_delivery_busy() && !voice_config_httpd_wifi_scanning() && !feedback_active &&
    !voice_feedback_error_pending(&feedback);
}
static bool wake_eligible(void) {
  return voice_settings.wake_enabled && board_sticks3_usb_powered() &&
    voice_gateway_health_status()==200 && voice_wake_detector_ready() && capture_eligible();
}
static void wake_pre_append(const uint8_t *pcm,size_t bytes) {
  for(size_t i=0;i<bytes;i++) {
    wake_preroll[wake_pre_head]=pcm[i];wake_pre_head=(wake_pre_head+1)%WAKE_PREROLL_BYTES;
    if(wake_pre_used<WAKE_PREROLL_BYTES)wake_pre_used++;
  }
}
static voice_capture_start_t capture_begin(uint32_t now,const char *answer_to,bool manual) {
  bool eligible=capture_eligible();
  voice_capture_start_t outcome=voice_feedback_capture_result(eligible,
    eligible && voice_feedback_claim_gate(&feedback,voice_gate_acquire,NULL));
  /* A failed CAS is retryable even if storage releases before caller runs.
   * Never derive that decision from a later busy snapshot. */
  if(outcome!=VOICE_CAPTURE_STARTED)return outcome;
  app.turn_client.error=VOICE_TURN_ERROR_NONE;
  voice_cue_cache_set_idle(false);
  feedback_cancel_routine();
  feedback_request(FEEDBACK_CAPTURE,VOICE_TURN_ERROR_NONE,false);
  if(wake_listening)hw_audio_capture_stop();
  voice_wake_detector_reset();wake_listening=false;
  wake_active=true;wake_ui=2;
  strlcpy(capture_answer_to,answer_to?answer_to:"",sizeof(capture_answer_to));
  voice_wake_capture_init(&wake,voice_settings.wake_pause_ms,MAX_RECORD_SECONDS_DEFAULT*1000U,
                           manual,voice_settings.button_mode);
  (void)voice_wake_activate(&wake,true,now);
  if(!local_cue_start(&wake_cue,VOICE_CUE_LISTENING,now)){wake_stop();return VOICE_CAPTURE_UNAVAILABLE;}
  return VOICE_CAPTURE_STARTED;
}
static void wake_idle_tick(uint32_t now, button_event_t button) {
  bool pressed=button==BUTTON_EVENT_PRESSED;
  bool released=button==BUTTON_EVENT_RELEASED;
  if(!wake_active) {
    if(pressed || !wake_eligible()) {
      if(wake_listening)wake_stop();
      return;
    }
    if(!wake_listening){voice_wake_detector_reset();hw_audio_capture_start();wake_listening=true;}
    wake_ui=1;uint8_t chunk[320];
    for(unsigned i=0;i<16;i++) {
      size_t n=hw_audio_capture_read(chunk,sizeof(chunk));if(!n)break;
      voice_wake_detector_feed(chunk,n);
    }
    if(wake_pending || voice_wake_detector_detected()){
      voice_capture_start_t result=capture_begin(now,NULL,false);
      wake_pending=result==VOICE_CAPTURE_RETRY;
    }
    return;
  }
  if(voice_wake_button_finish(&wake,pressed,released) || !capture_eligible()) {
    wake_stop();feedback_request(FEEDBACK_CANCELLED,VOICE_TURN_ERROR_NONE,false);
    app.ignore_button_until_release=hw_button_raw();return;
  }
  if(wake.state==WAKE_CUE) {
    voice_cue_status_t status=voice_listening_cue_tick(&wake_cue,now);
    if(status==CUE_BUSY)return;
    if(status!=CUE_DONE || !voice_vad_reset()){
      wake_stop();enter_state(STATE_ERROR,"voice activity detection failed");return;
    }
    voice_wake_cue_done(&wake,now,true);
    hw_audio_capture_start();wake_pre_used=0;wake_pre_head=0;wake_ui=3;
  }
  bool speech=false;uint8_t chunk[320];
  for(unsigned i=0;i<16;i++) {
    size_t n=hw_audio_capture_read(chunk,sizeof(chunk));if(!n)break;
    if(wake.state==WAKE_SETTLE && (uint32_t)(now-wake.cue_end_ms)<150)continue;
    wake_pre_append(chunk,n);speech=voice_vad_feed(chunk,n)||speech;
  }
  if(!voice_vad_ready()){wake_stop();enter_state(STATE_ERROR,"voice activity detection failed");return;}
  voice_wake_event_t event=voice_wake_tick(&wake,true,now,speech,false);
  if(event==WAKE_CANCEL){wake_stop();feedback_request(FEEDBACK_CANCELLED,VOICE_TURN_ERROR_NONE,false);
    app.ignore_button_until_release=hw_button_raw();return;}
  if(event==WAKE_START_RECORD) {
    if(!recording_start()){wake_stop();enter_state(STATE_ERROR,"voice recording failed");return;}
    size_t first=(wake_pre_head+WAKE_PREROLL_BYTES-wake_pre_used)%WAKE_PREROLL_BYTES;
    size_t part=WAKE_PREROLL_BYTES-first;if(part>wake_pre_used)part=wake_pre_used;
    ring_buffer_push(&app.rb,wake_preroll+first,part);
    ring_buffer_push(&app.rb,wake_preroll,wake_pre_used-part);
    wake_active=false;wake_recording=true;wake_ui=0;
    /* Preserve debounced edges; snapshotted mode decides what release means. */
    app.btn.press_ms=now;enter_state(STATE_RECORDING,NULL);
    ESP_LOGI("capture","Dictation started after cue, settle and speech");
  }
}
#endif

/*
 * Spec section 10 step 2: close the HTTP session gracefully when the
 * connection still allows it; fall back to abort when a graceful close
 * cannot complete (network already dead).
 */
#ifndef ESP_PLATFORM
static void session_close_or_abort(void) {
  if (http_session_is_active(&app.session)) {
    if (!http_session_close(&app.session)) {
      http_session_abort(&app.session);
    }
  }
}

#endif

/*
 * Capture side of the audio path (M1-03). Pulls whatever PCM the
 * microphone has ready this tick and fans it out to both the
 * network-drain buffer (app.rb, M2 upload — unchanged) and the loopback
 * buffer (app.playback_rb) that M1-04 plays back once the turn finishes.
 * "One tick = everything ready" mirrors recording_drain()'s shape below.
 */
static void recording_capture(void) {
  uint8_t chunk[256];
  size_t n;
  while ((n = hw_audio_capture_read(chunk, sizeof(chunk))) > 0) {
#ifdef ESP_PLATFORM
    if(wake_recording)wake_speech=voice_vad_feed(chunk,n)||wake_speech;
#endif
    size_t accepted = ring_buffer_push(&app.rb, chunk, n);
    voice_diag_record_capture((uint32_t)accepted,
                              (uint32_t)ring_buffer_count(&app.rb));
#ifndef ESP_PLATFORM
    ring_buffer_push(&app.playback_rb, chunk, n);
#endif
  }
}

/*
 * Writer side of the audio path: drain the ring buffer into the HTTP
 * session. "One tick = everything that fits" models the network rate;
 * the real writer paces itself with the transport. Stops as soon as the
 * overflow flag is up so no data is handed over after the failure.
 */
static void recording_drain(void) {
  uint8_t chunk[256];
  while (!ring_buffer_overflow(&app.rb) && !ring_buffer_empty(&app.rb)) {
    size_t limit = sizeof(chunk);
#ifdef ESP_PLATFORM
    {
      size_t available = xStreamBufferSpacesAvailable(app.turn_upload_stream);
      if (!available) return;
      if (limit > available) limit = available;
    }
#endif
    size_t n = ring_buffer_pop(&app.rb, chunk, limit);
    if (n == 0) {
      break;
    }
#ifdef ESP_PLATFORM
    {
      if (xStreamBufferSend(app.turn_upload_stream, chunk, n, 0) != n) {
        app.turn_upload_failed = true;
        voice_diag_event(VOICE_DIAG_UPLOAD_QUEUE_ERROR, hw_clock_ms(),
                         (uint32_t)n,
                         (uint32_t)xStreamBufferSpacesAvailable(app.turn_upload_stream));
        return;
      }
      voice_diag_record_queue((uint32_t)n,
                              (uint32_t)xStreamBufferBytesAvailable(app.turn_upload_stream));
    }
#else
    (void)http_session_write(&app.session, chunk, n);
#endif
  }
}

/*
 * Spec section 10 reaction, called when the sticky overflow flag is set:
 *   1. recording stops immediately (capture task sees the flag + this
 *      transition; the drain loop stops writing),
 *   2. microphone stopped (M1-03),
 *   3. HTTP session closed gracefully if possible,
 *   4. ERROR shown,
 *   5. recovery back to IDLE happens in the ERROR state (no reboot).
 */
static void on_ring_buffer_overflow(void) {
  voice_diag_event(VOICE_DIAG_REC_RING_OVERFLOW, hw_clock_ms(),
                   (uint32_t)ring_buffer_count(&app.rb),
                   (uint32_t)ring_buffer_capacity(&app.rb));
  hw_audio_capture_stop();
#ifdef ESP_PLATFORM
  {
    app.turn_upload_failed = true;
    app.turn_upload_finished = true;
    app.turn_cancel_requested = true;
  }
#else
  session_close_or_abort();
#endif
  enter_state(STATE_ERROR, "ring buffer overflow");
}

/*
 * Spec section 8: release every playback resource, deterministically and
 * idempotently, as part of entering IDLE (EOF path) or ERROR (playback
 * error path) out of PLAYING. Called exactly once per PLAYING exit by
 * both on_playback_error() and the EOF handler in app_tick()'s
 * STATE_PLAYING case, so the two paths can never diverge in what they
 * clean up:
 *   - stop the DMA/I2S peripheral (hw_audio_playback_stop()) so no more
 *     bytes reach the speaker regardless of what was still queued,
 *   - free/zero the loopback ring buffer (ring_buffer_reset(), which also
 *     clears its internal head/tail/count -- no stale audio or dangling
 *     read/write position survives into the next turn),
 *   - drop the one pending unwritten chunk (app.playback_pending_len = 0;
 *     the bytes themselves are stale scratch space, not a resource that
 *     needs freeing, but the length must be zeroed so a later playback
 *     session never mistakes them for real pending data),
 *   - clear the playback position counter (app.playback_position = 0).
 * Safe to call from a state that has already released these resources
 * (e.g. a spurious repeated call): every step here is itself idempotent
 * (hw_audio_playback_stop() / ring_buffer_reset() on an already-stopped/
 * already-empty target is a no-op), so calling this twice in a row is
 * harmless -- the idempotency guarantee in the app_tick() EOF check below
 * only needs to ensure it isn't reached at all while already IDLE.
 */
static void playback_release_resources(void) {
  hw_audio_playback_stop();
  ring_buffer_reset(&app.playback_rb);
#ifdef ESP_PLATFORM
  app.turn_pending_byte = false;
#endif
  app.playback_pending_len = 0;
  app.playback_position = 0;
}

/*
 * Spec sections 8/13/38 reaction, called when a playback-side error flag is
 * set (backend connection dropped mid-stream, or the reply's WAV header is
 * malformed):
 *   1. playback stops immediately (no more bytes handed to the speaker),
 *   2. the speaker hardware is stopped (mirrors on_ring_buffer_overflow's
 *      hw_audio_capture_stop() on the RECORDING side),
 *   3. the loopback buffer is drained/reset so no stale audio survives into
 *      the next turn,
 *   4. ERROR is shown,
 *   5. recovery back to IDLE happens in the ERROR state (no reboot),
 *      exactly like the ring-buffer-overflow path already does.
 */
static void on_playback_error(const char* what) {
#ifdef ESP_PLATFORM
  app.turn_cancel_requested = true;
#endif
  playback_release_resources();
  enter_state(STATE_ERROR, what);
}

/*
 * Start of local playback (M1-04): prime the speaker so playback_drain()
 * can begin writing to it next tick.
 */
#ifndef ESP_PLATFORM
static void playback_start(void) {
  app.playback_pending_len = 0;
  app.playback_position = 0;
  app.playback_conn_dropped = false;
  app.playback_bad_wav_header = false;
  hw_audio_playback_start(NULL, 0);
}
#endif

/*
 * Drain side of the audio path (M1-04): hand the loopback buffer to the
 * speaker. hw_audio_playback_write() is all-or-nothing (see
 * board_atom_echo.c) — a chunk it doesn't accept in full is kept in
 * app.playback_pending and retried next tick instead of being lost or, if
 * we instead popped the next chunk in its place, played back out of
 * order.
 */
#ifndef ESP_PLATFORM
static void playback_drain(void) {
  if (app.playback_pending_len > 0) {
    size_t written =
        hw_audio_playback_write(app.playback_pending, app.playback_pending_len);
    if (written < app.playback_pending_len) {
      return; /* sink still full; try the same chunk again next tick */
    }
    app.playback_position += written;
    app.playback_pending_len = 0;
  }
  while (!ring_buffer_empty(&app.playback_rb)) {
    size_t n = ring_buffer_pop(&app.playback_rb, app.playback_pending,
                                sizeof(app.playback_pending));
    if (n == 0) {
      break;
    }
    size_t written = hw_audio_playback_write(app.playback_pending, n);
    if (written < n) {
      app.playback_pending_len = n; /* retry this whole chunk next tick */
      break;
    }
    app.playback_position += written;
  }
}

#endif

#ifdef ESP_PLATFORM
static bool turn_playback_drain(void) {
  uint8_t audio[1025];
  size_t prefix = 0;
  if (app.turn_pending_byte) {
    audio[0] = app.turn_pending_value;
    prefix = 1;
    app.turn_pending_byte = false;
  }
  size_t received = xStreamBufferReceive(app.turn_audio_stream,
      audio + prefix, sizeof(audio) - prefix, 0);
  size_t total = prefix + received;
  if (total & 1u) {
    app.turn_pending_byte = true;
    app.turn_pending_value = audio[total - 1];
    total--;
  }
  if (!total) return true;
  size_t written = hw_audio_playback_write(audio, total);
  if (written != total) return false;
  app.playback_position += written;
  return true;
}
#endif

/* True once every captured byte has been handed to the speaker AND the
 * hardware confirms it actually finished playing them (not just queued). */
#ifndef ESP_PLATFORM
static bool playback_finished(void) {
  return ring_buffer_empty(&app.playback_rb) && app.playback_pending_len == 0 &&
         hw_audio_playback_drained()
      ;
}

#endif

void app_init(void) {
#ifdef ESP_PLATFORM
  /* voice_ota activity is initially1 (boot/app), before its worker starts. */
  voice_feedback_boot_init(&feedback);feedback_active=false;idle_followup=false;
#endif
  voice_diag_reset();
  state_machine_init(&app.sm);
  /* MAX_RECORD_SECONDS is the configurable cap from spec section 7;
   * button_driver auto-fires MAX_RECORD_TIMEOUT, which the RECORDING tick
   * treats like a release, so a held button never records past the limit. */
  button_init(&app.btn, BUTTON_DEBOUNCE_MS_DEFAULT, MAX_RECORD_SECONDS_DEFAULT);
  app.boot_ticks = 0;
  app.error_ack_ready = false;
  app.error_ack_pressed = false;
  app.ignore_button_until_release = false;
  ring_buffer_init(&app.rb, app.rb_storage, RING_BUFFER_CAPACITY_DEFAULT);
  ring_buffer_init(&app.playback_rb, app.playback_storage,
                    RING_BUFFER_CAPACITY_DEFAULT);
  app.playback_pending_len = 0;
  app.playback_position = 0;
  app.playback_conn_dropped = false;
  app.playback_bad_wav_header = false;
  http_session_init(&app.session);
#ifdef ESP_PLATFORM
  (void)voice_settings_load(&voice_settings);
  voice_diag_load_last_error();
  uint8_t sta_mac[6];
  ESP_ERROR_CHECK(esp_read_mac(sta_mac, ESP_MAC_WIFI_STA));
  voice_settings_set_device_id_from_mac(&voice_settings, sta_mac);
  board_sticks3_display_set_device_id(voice_settings.device_id);
  ESP_LOGI("power", "Battery idle sleep timeout: %lu seconds",
           (unsigned long)voice_settings.sleep_timeout_seconds);
  app.turn_task_active = false;
  app.turn_cancel_requested = false;
  app.turn_audio_started = false;
  app.turn_upload_active = false;
  app.turn_upload_finished = false;
  app.turn_upload_failed = false;
  app.turn_result = VOICE_TURN_FAILED;
  app.turn_http_ready = false;
  app.turn_storage_failed = false;
  app.turn_pending_byte = false;
  {
    app.turn_audio_stream = xStreamBufferCreate(8192, 1);
    /* Capture starts before DNS/TCP/TLS completes. Keep up to 16 seconds
     * of 16 kHz mono PCM in PSRAM while the upload worker connects or stalls.
     * FreeRTOS reserves one byte in a statically supplied stream buffer. */
    enum { UPLOAD_CAPACITY = 512 * 1024 };
    static StaticStreamBuffer_t upload_control;
    static uint8_t *upload_storage;
    if (!upload_storage)
      upload_storage = heap_caps_malloc(UPLOAD_CAPACITY + 1,
                                        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (upload_storage)
      app.turn_upload_stream = xStreamBufferCreateStatic(
          UPLOAD_CAPACITY + 1, 1, upload_storage, &upload_control);
    else
      ESP_LOGE("voice_turn", "Cannot allocate upload buffer in PSRAM");
    if (app.turn_audio_stream && app.turn_upload_stream &&
        voice_settings_valid(&voice_settings)) {
      app.turn_http_ready = voice_turn_http_init(&app.turn_http,
          voice_settings.gateway_url, voice_settings.device_id,
          voice_settings.device_token, app.turn_audio_stream,
          &app.turn_cancel_requested, &app.turn_audio_started);
    }
  }
  if (voice_wifi_first_profile(voice_settings.wifi) >= 0) {
    if (!board_sticks3_wifi_start(voice_settings.wifi)) {
      (void)board_sticks3_wifi_start_ap();
    }
  } else {
    (void)board_sticks3_wifi_start_ap();
  }
  voice_tls_start();
  (void)voice_gateway_health_start(voice_settings.gateway_url);

  /* Spoken cues are fetched in idle time; a short tone covers cold boot. */
  (void)voice_cue_cache_start(voice_settings.gateway_url,
                             voice_settings.device_id,voice_settings.device_token);
  wake_preroll=heap_caps_malloc(WAKE_PREROLL_BYTES,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
  (void)voice_ota_start(voice_settings.gateway_url,
                        voice_settings.device_id, voice_settings.device_token);
  if (voice_diag_delivery_start(voice_settings.gateway_url,
                                voice_settings.device_id,
                                voice_settings.device_token)) {
    voice_diag_snapshot_t previous;
    voice_diag_snapshot(&previous);
    if (previous.last_error_code) voice_diag_delivery_request();
  }
  voice_config_httpd_start(&voice_settings);
  const http_voice_config_t cfg = {
      .url = voice_settings.gateway_url,
      .device_id = voice_settings.device_id,
      .token = voice_settings.device_token[0] ? voice_settings.device_token : NULL,
      .timeout_ms = 5000,
      .request_id = voice_settings.request_id,
      .answer_to = capture_answer_to,
  };
  if (http_voice_client_init(&voice_client, &cfg) == 0)
    http_session_bind_transport(&app.session, http_voice_client_transport(&voice_client));
#endif
}

/* Current app state (test hook). */
state_t app_state(void) {
  return state_machine_get_state(&app.sm);
}

/* Current HTTP session state (test hook). */
http_session_state_t app_session_state(void) {
  return http_session_state(&app.session);
}

/* True if the last session ended via abort() (test hook). */
bool app_session_aborted(void) {
  return app.session.aborted;
}

/* Test hooks (spec section 8 acceptance criteria): expose the playback
 * resources directly so tests can verify they are actually released on
 * PLAYING -> IDLE/ERROR, not just that the state getter reads IDLE. */
size_t app_playback_position(void) {
  return app.playback_position;
}
size_t app_playback_pending_len(void) {
  return app.playback_pending_len;
}
size_t app_playback_rb_count(void) {
  return ring_buffer_count(&app.playback_rb);
}

/*
 * Test hook: simulate the I2S capture task overflowing the ring buffer —
 * pushes through the public API until the sticky flag is raised, exactly
 * like a real capture task that outran the network would do.
 */
void app_test_simulate_ring_overflow(void) {
  static const uint8_t filler[RING_BUFFER_CAPACITY_DEFAULT] = {0};
  while (!ring_buffer_overflow(&app.rb)) {
    if (ring_buffer_push(&app.rb, filler, sizeof(filler)) == 0) {
      break;
    }
  }
}

/*
 * Test hook: simulate the backend connection dropping mid-stream while a
 * reply is being downloaded/played (spec sections 8/13/38). Sets the sticky
 * flag the STATE_PLAYING tick checks; the next tick drives PLAYING -> ERROR
 * -> (after acknowledgement) IDLE, mirroring
 * app_test_simulate_ring_overflow() on the RECORDING side.
 */
void app_test_simulate_playback_conn_drop(void) {
  app.playback_conn_dropped = true;
}

/*
 * Test hook: simulate the backend's reply arriving with a malformed/
 * incorrect WAV header (spec sections 8/13/38). Same sticky-flag shape as
 * app_test_simulate_playback_conn_drop() above.
 */
void app_test_simulate_playback_bad_wav_header(void) {
  app.playback_bad_wav_header = true;
}

/*
 * One application tick. Non-blocking: each per-state action performs at most
 * one hardware poll and returns.
 */
void app_tick(void) {
  uint32_t now = hw_clock_ms();
  state_t s = state_machine_get_state(&app.sm);
#ifdef ESP_PLATFORM
  if(s==STATE_PROCESSING && !app.turn_cancel_requested &&
     app.turn_result!=VOICE_TURN_FAILED && !app.turn_storage_failed){
    if(app.turn_audio_started)feedback_request(FEEDBACK_ANSWERING,VOICE_TURN_ERROR_NONE,false);
    else voice_feedback_stage(&feedback,app.turn_client.status);
  }
  feedback_service(now,s);
#endif

  switch (s) {
    case STATE_BOOT:
      if (++app.boot_ticks >= APP_BOOT_TICKS) {
#ifdef ESP_PLATFORM
        if (voice_settings.request_id[0]) {
          if (start_turn_worker(false)) enter_state(STATE_PROCESSING, NULL);
          else enter_state(STATE_ERROR, "could not resume saved voice turn");
        } else {
          enter_state(STATE_IDLE, NULL);
        }
#else
        enter_state(STATE_IDLE, NULL);
#endif
      }
      break;

    case STATE_IDLE: {
      if (app.ignore_button_until_release) {
        if (!hw_button_raw()) {
#ifdef ESP_PLATFORM
          voice_feedback_release_button(&feedback);
#endif
          app.ignore_button_until_release = false;
          button_reset(&app.btn);
        }
        break;
      }
      button_event_t ev = button_poll(&app.btn, hw_button_raw(), now);
#ifdef ESP_PLATFORM
      if(ev==BUTTON_EVENT_RELEASED)voice_feedback_release_button(&feedback);
      bool terminal=voice_feedback_error_pending(&feedback) ||
        (feedback_active && voice_feedback_is_error(feedback_current));
      if(ev==BUTTON_EVENT_PRESSED && terminal){
        voice_feedback_defer_press(&feedback,voice_settings.button_mode==VOICE_BUTTON_HOLD);break;
      }
      if(!terminal && voice_feedback_take_press(&feedback))ev=BUTTON_EVENT_PRESSED;
      if(ev==BUTTON_EVENT_PRESSED && !wake_active){
        feedback_cancel_routine();
        feedback_request(FEEDBACK_CAPTURE,VOICE_TURN_ERROR_NONE,false);
      }
      if(feedback_active || voice_feedback_pending(&feedback))break;
      bool was_capture=wake_active;
      wake_idle_tick(now,ev);
      if(was_capture || wake_active)break;
#endif
      if (ev == BUTTON_EVENT_PRESSED) {
#ifdef ESP_PLATFORM
        if (!board_sticks3_network_ready() || voice_gateway_health_status()==0) {
          wake_stop();feedback_request(FEEDBACK_ERROR,VOICE_TURN_ERROR_CONNECTION,false);
          app.ignore_button_until_release=true;break;
        }
        voice_capture_start_t started=capture_begin(now,NULL,true);
        if(started==VOICE_CAPTURE_RETRY)
          voice_feedback_defer_press(&feedback,voice_settings.button_mode==VOICE_BUTTON_HOLD);
        else if(started!=VOICE_CAPTURE_STARTED)enter_state(STATE_ERROR,"voice capture unavailable");
#else
        if (recording_start()) enter_state(STATE_RECORDING, NULL);
        else enter_state(STATE_ERROR, "voice recording start failed");
#endif
      }
      break;
    }

    case STATE_RECORDING: {
      /*
       * Spec section 10: the capture task pushes into app.rb at the
       * production rate; if the network falls behind, the sticky overflow
       * flag goes up and we must stop recording IMMEDIATELY — not keep
       * silently dropping data.
       */
      if (ring_buffer_overflow(&app.rb)) {
        on_ring_buffer_overflow();
        break;
      }
#ifdef ESP_PLATFORM
      if (app.turn_result == VOICE_TURN_FAILED && !app.turn_task_active) {
        hw_audio_capture_stop();
        voice_diag_event(VOICE_DIAG_TURN_FAILED, now, 0, 0);
        enter_state(STATE_ERROR, "voice upload failed");
        break;
      }
#endif
#ifdef ESP_PLATFORM
      wake_speech=false;
#endif
      recording_capture();
      recording_drain();
      button_event_t ev = button_poll(&app.btn, hw_button_raw(), now);
      bool finished = ev == BUTTON_EVENT_RELEASED || ev == BUTTON_EVENT_MAX_RECORD_TIMEOUT;
#ifdef ESP_PLATFORM
      if(wake_recording) {
        if(!voice_vad_ready()){hw_audio_capture_stop();enter_state(STATE_ERROR,"voice activity detection failed");break;}
        finished=voice_wake_tick(&wake,true,now,wake_speech,
          voice_wake_button_finish(&wake,ev==BUTTON_EVENT_PRESSED,ev==BUTTON_EVENT_RELEASED))==WAKE_FINISH;
        if(finished){wake_recording=false;app.ignore_button_until_release=hw_button_raw();}
      }
#endif
      if (finished) {
        /*
         * Normal finish (release, or the MAX_RECORD_SECONDS auto-finish
         * from spec section 7: the button driver fires
         * MAX_RECORD_TIMEOUT at the configurable limit). Stop the
         * microphone and send the terminal body, closing the session
         * gracefully.
         */
        hw_audio_capture_stop();
#ifndef ESP_PLATFORM
        session_close_or_abort();
#endif
#ifdef ESP_PLATFORM
        {
          app.turn_upload_release_requested = true;
          if (!voice_settings.request_id[0] || !app.turn_task_active) {
            enter_state(STATE_ERROR, "could not resume voice turn");
            break;
          }
        }
#endif
        enter_state(STATE_PROCESSING, NULL);

      }
      break;
    }

    case STATE_PROCESSING:
      /*
       * M1 loopback (see file header): there is no backend turn to wait
       * on yet, so the audio that was just recorded IS the reply. This
       * step is a single, immediate tick — the real "wait for the
       * backend" condition lands with the M2 network wiring.
       */
#ifdef ESP_PLATFORM
      {
        if (app.turn_upload_release_requested && !app.turn_upload_finished) {
          recording_drain();
          if (ring_buffer_empty(&app.rb)) app.turn_upload_finished = true;
        }
        button_event_t event = button_poll(&app.btn, hw_button_raw(), now);
        if (event == BUTTON_EVENT_PRESSED) {
          app.turn_cancel_requested = true;
          feedback_cancel_routine();
        }
        /* A cancelled turn may finish downloading while its routine cue
         * drains. READY is terminal in the worker; do not wait for CANCELLED. */
        if(voice_feedback_cancel_complete(app.turn_cancel_requested,app.turn_task_active,app.turn_storage_failed)){
          feedback_cancel_routine();app.turn_client.follow_up_listen=false;
          app.ignore_button_until_release=true;playback_release_resources();
          enter_state(STATE_IDLE,NULL);break;
        }
        if (app.turn_storage_failed || app.turn_result == VOICE_TURN_FAILED) {
          if (app.turn_task_active) app.turn_cancel_requested = true;
          enter_state(STATE_ERROR, "voice turn failed");
        } else if (app.turn_result == VOICE_TURN_CANCELLED) {
          app.ignore_button_until_release = true;
          playback_release_resources();
          enter_state(STATE_IDLE, NULL);
        } else if (app.turn_audio_started && !app.turn_cancel_requested && !feedback_active &&
                   !voice_feedback_pending(&feedback)) {
          app.playback_position = 0;
          hw_audio_playback_start(NULL, 0);
          enter_state(STATE_PLAYING, NULL);
        }
        break;
      }
#else
      playback_start();
#endif
      enter_state(STATE_PLAYING, NULL);
      break;

    case STATE_PLAYING:
      /*
       * Spec sections 8/13/38: a backend connection drop mid-stream or a
       * malformed WAV header on the reply must be detected during PLAYING
       * and drive the device to ERROR immediately -- not hang waiting for
       * bytes that are never coming, and not silently keep playing
       * corrupted/incomplete audio. Checked before draining so a failure
       * flagged this tick takes effect before any more bytes reach the
       * speaker. Real backend wiring lands with M2 (see http_session.c
       * file header); the flags are set here by
       * app_test_simulate_playback_conn_drop() /
       * app_test_simulate_playback_bad_wav_header() today and, later, by
       * the real M2 download/parsing path signaling the same failures.
       */
      if (app.playback_conn_dropped) {
        on_playback_error("playback backend connection dropped");
        break;
      }
      if (app.playback_bad_wav_header) {
        on_playback_error("playback malformed WAV header");
        break;
      }
#ifdef ESP_PLATFORM
      {
        if(button_poll(&app.btn,hw_button_raw(),now)==BUTTON_EVENT_PRESSED) {
          app.turn_cancel_requested=true;
          app.turn_client.follow_up_listen=false;
          app.ignore_button_until_release=true;
          playback_release_resources();
          enter_state(STATE_IDLE,NULL);
          break;
        }
        if (app.turn_result == VOICE_TURN_FAILED || app.turn_storage_failed) {
          on_playback_error("voice turn failed during audio");
          break;
        }
        if (app.turn_result == VOICE_TURN_CANCELLED) {
          app.ignore_button_until_release = true;
          playback_release_resources();
          enter_state(STATE_IDLE, NULL);
          break;
        }
        if (!turn_playback_drain()) {
          on_playback_error("speaker rejected voice audio");
          break;
        }
        if (app.turn_result == VOICE_TURN_READY &&
            xStreamBufferBytesAvailable(app.turn_audio_stream) == 0) {
          if (app.turn_pending_byte) {
            on_playback_error("odd-length voice audio");
            break;
          }
          if (hw_audio_playback_drained() && !app.turn_task_active) {
            char question_id[VOICE_TURN_ID_CAPACITY];
            bool follow=voice_turn_client_take_follow_up(&app.turn_client,
                app.turn_fresh && !app.turn_cancel_requested && !app.turn_storage_failed,
                question_id,sizeof(question_id));
            playback_release_resources();
            /* Suppress DONE before IDLE so the existing lease transfers directly
             * to listening; never consume follow-up behind a completion cue. */
            idle_followup=follow;enter_state(STATE_IDLE, NULL);idle_followup=false;
            if(follow && capture_begin(now,question_id,false)!=VOICE_CAPTURE_STARTED)
              enter_state(STATE_ERROR,"follow-up capture unavailable");
          }
        }
        break;
      }
#endif
#ifndef ESP_PLATFORM

      /* M1-04: drain the loopback/response buffer to the speaker; wait for the
       * hardware to confirm playback actually finished before IDLE.
       *
       * EOF detection (spec section 8): playback_finished() is robust to
       * whatever the buffer fill level was at EOF -- it doesn't care
       * whether the loopback buffer was full, partially drained, or
       * empty when the last sample was consumed, only that (a) nothing
       * is left queued on this side (ring buffer empty, no pending
       * unwritten chunk) and (b) the hardware confirms it has actually
       * finished playing what was handed to it (hw_audio_playback_drained,
       * not just "queued"). Checked every tick, so the PLAYING -> IDLE
       * transition below fires on the very same tick EOF is confirmed --
       * no multi-tick delay and no dependence on a specific drain
       * sequence (full-buffer and near-empty-buffer EOF both resolve
       * through this one check). */
      playback_drain();
      if (playback_finished()) {
        /* Resource cleanup on IDLE entry (spec section 8): release the
         * ring buffer, pending chunk, position counter, and DMA/I2S
         * peripheral atomically with the state transition -- the same
         * playback_release_resources() the error path above uses, so
         * both PLAYING exits leave identical, fully-cleaned-up state and
         * can never leak a buffer, handle, or dangling position counter
         * into the next playback session. */
        playback_release_resources();
        enter_state(STATE_IDLE, NULL);
      }
      break;
#endif

    case STATE_ERROR: {
      bool raw_pressed = hw_button_raw();
      button_event_t ev = button_poll(&app.btn, raw_pressed, now);
      if (!app.error_ack_ready) {
        if (!raw_pressed && !button_is_pressed(&app.btn))
          app.error_ack_ready = true;
      } else if (ev == BUTTON_EVENT_PRESSED) {
        app.error_ack_pressed = true;
      } else if (ev == BUTTON_EVENT_RELEASED && app.error_ack_pressed) {
#ifdef ESP_PLATFORM
        if (!app.turn_task_active)
          enter_state(STATE_IDLE, NULL);
#else
        enter_state(STATE_IDLE, NULL);
#endif
      }
      break;
    }

    default:
      break;
  }
}

#ifdef VOICE_WITH_MAIN
static void voice_main_loop(void) {
  board_sticks3_log_memory();
  app_init();
  bool error_reported = false;
  for (;;) {
    app_tick();
#ifdef ESP_PLATFORM
    if (app_state() == STATE_ERROR && !error_reported) {
      voice_diag_persist_last_error();
      voice_diag_delivery_request();
      error_reported = true;
    } else if (app_state() != STATE_ERROR) {
      error_reported = false;
    }
    voice_cue_cache_set_idle(app_state() == STATE_IDLE && !app.turn_task_active && !wake_active && !feedback_active && !voice_feedback_pending(&feedback));
    voice_diag_delivery_set_idle(
        (app_state() == STATE_IDLE || app_state() == STATE_ERROR) &&
        !app.turn_task_active && !wake_active && !feedback_active && !voice_feedback_pending(&feedback));
    if ((app_state() == STATE_IDLE || app_state()==STATE_ERROR) && !app.turn_task_active && !wake_active && !feedback_active && !voice_feedback_pending(&feedback))
      voice_feedback_release_gate(&feedback,voice_gate_release,NULL);
#endif
    screen_processing_phase_t phase = SCREEN_PROCESSING_THINKING;
#ifdef ESP_PLATFORM
    if (app.turn_client.status == VOICE_TURN_STATUS_TRANSCRIBING)
      phase = SCREEN_PROCESSING_TRANSCRIBING;
    else if (app.turn_client.status == VOICE_TURN_STATUS_SYNTHESIZING)
      phase = SCREEN_PROCESSING_SYNTHESIZING;
#endif
    screen_recording_timer_t timer = {0};
    if (app_state() == STATE_RECORDING)
      timer = screen_ui_recording_timer(app.btn.press_ms, hw_clock_ms(),
                                        MAX_RECORD_SECONDS_DEFAULT);
    board_sticks3_display_update(app_state(), hw_clock_ms(), phase, timer);
#ifdef ESP_PLATFORM
    if(!wake_start_attempted && !voice_ota_busy() &&
       app_state()==STATE_IDLE && !app.turn_task_active &&
       voice_settings.wake_enabled && board_sticks3_local_self_test()) {
      wake_start_attempted=true;
      if(wake_preroll)(void)voice_wake_detector_start();
    }
    voice_ota_set_application_ready(!voice_settings.wake_enabled || voice_wake_detector_ready());
    voice_ota_confirm_boot();
#endif
    board_sticks3_power_tick(
      (app_state() != STATE_IDLE && app_state() != STATE_ERROR) || app.turn_task_active || wake_active || feedback_active || voice_feedback_pending(&feedback) || voice_ota_storage_busy(),
      hw_clock_ms(), voice_settings.sleep_timeout_seconds * 1000U);
    /* Keep the USB/Wi-Fi/I2S system tasks and watchdog serviced. */
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}
#ifdef ESP_PLATFORM
void app_main(void) { voice_main_loop(); }
#else
int main(void) { voice_main_loop(); return 0; }
#endif
#endif
