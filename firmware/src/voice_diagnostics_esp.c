#include "voice_diagnostics.h"

#ifdef ESP_PLATFORM
#include "esp_log.h"
#include "nvs.h"

static voice_diag_code_t stored_code;

void voice_diag_load_last_error(void) {
  nvs_handle_t handle;
  if (nvs_open("zateya_diag", NVS_READONLY, &handle) != ESP_OK) return;
  uint8_t code = 0;
  if (nvs_get_u8(handle, "last_error", &code) == ESP_OK) {
    stored_code = (voice_diag_code_t)code;
    voice_diag_restore_last_error(stored_code);
  }
  nvs_close(handle);
}

void voice_diag_persist_last_error(void) {
  voice_diag_snapshot_t snapshot;
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
