#include "voice_diagnostics.h"

#ifdef ESP_PLATFORM
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "voice_wireguard.h"
#include "voice_gateway_health.h"
#include <stdio.h>

static voice_diag_code_t stored_code;
static uint32_t boot_id;
static uint32_t sequence;
static portMUX_TYPE report_lock = portMUX_INITIALIZER_UNLOCKED;

void voice_diag_load_last_error(void) {
  boot_id = esp_random();
  nvs_handle_t handle;
  if (nvs_open("zateya_diag", NVS_READONLY, &handle) != ESP_OK) return;
  uint8_t code = 0;
  if (nvs_get_u8(handle, "last_error", &code) == ESP_OK) {
    stored_code = (voice_diag_code_t)code;
    voice_diag_restore_last_error(stored_code);
  }
  nvs_close(handle);
}

bool voice_diag_report_json(char *out, size_t capacity) {
  if (!out || !capacity) return false;
  voice_diag_snapshot_t snapshot;
  voice_diag_snapshot(&snapshot);
  char data[4096];
  if (!voice_diag_snapshot_json(&snapshot, data, sizeof(data))) return false;
  wifi_ap_record_t ap = {0};
  bool wifi_connected = esp_wifi_sta_get_ap_info(&ap) == ESP_OK;
  portENTER_CRITICAL(&report_lock);
  uint32_t next_sequence = ++sequence;
  portEXIT_CRITICAL(&report_lock);
  int written = snprintf(out, capacity,
      "{\"boot_id\":%lu,\"sequence\":%lu,\"uptime_ms\":%llu,"
      "\"reset_reason\":%u,\"firmware_revision\":\"%s %s\","
      "\"wifi_connected\":%s,\"wg_status\":\"%s\","
      "\"backend_status\":%d,\"free_heap_bytes\":%lu,"
      "\"recording\":%s}",
      (unsigned long)boot_id, (unsigned long)next_sequence,
      (unsigned long long)(esp_timer_get_time() / 1000),
      (unsigned)esp_reset_reason(), __DATE__, __TIME__,
      wifi_connected ? "true" : "false", voice_wireguard_status(),
      voice_gateway_health_status(), (unsigned long)esp_get_free_heap_size(), data);
  return written > 0 && (size_t)written < capacity;
}

void voice_diag_persist_last_error(void) {
  static voice_diag_snapshot_t snapshot;
  voice_diag_snapshot(&snapshot);
  voice_diag_code_t code = snapshot.last_error_code;
  if (!code || code == stored_code) return;
  nvs_handle_t handle;
  esp_err_t err = nvs_open("zateya_diag", NVS_READWRITE, &handle);
  if (err == ESP_OK) {
    err = nvs_set_u8(handle, "last_error", (uint8_t)code);
    if (err == ESP_OK) err = nvs_commit(handle);
    nvs_close(handle);
  }
  if (err == ESP_OK) {
    stored_code = code;
    ESP_LOGE("voice_diag", "last_error_code=%u captured=%lu sent=%lu ring_peak=%lu upload_peak=%lu write_max_ms=%lu",
             (unsigned)code, (unsigned long)snapshot.captured_bytes,
             (unsigned long)snapshot.sent_bytes,
             (unsigned long)snapshot.ring_high_water_bytes,
             (unsigned long)snapshot.upload_high_water_bytes,
             (unsigned long)snapshot.write_max_ms);
  } else {
    ESP_LOGE("voice_diag", "last_error persistence failed: %s", esp_err_to_name(err));
  }
}
#endif
