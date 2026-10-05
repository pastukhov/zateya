#include "voice_ota.h"

#ifdef ESP_PLATFORM
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "board_sticks3.h"
#include "cJSON.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include "mbedtls/pk.h"
#include "mbedtls/sha256.h"
#include "nvs.h"
#include "voice_gateway_health.h"
#include "voice_ota_policy.h"
#include "voice_ota_release.h"
#include "voice_wireguard.h"

#define OTA_CHECK_TIMEOUT_MS 5000
#define OTA_DOWNLOAD_LIMIT_MS 600000
#define OTA_MANIFEST_CAP 8192

typedef struct {
  uint32_t sequence;
  size_t size;
  char sha256[65];
  char image_path[128];
} ota_manifest_t;

static const char *TAG = "voice_ota";
/* 0=idle, 1=voice/boot, 2=OTA. Main task and OTA worker use one CAS gate. */
static atomic_int activity = 1;
static atomic_uint progress_percent;
static atomic_bool boot_confirmed;
static atomic_bool updates_disabled;
static char gateway_base[192];
static char device_id[32];
static char authorization[200];
static uint32_t rejected_seq;
static int64_t boot_started_us;
static int64_t last_self_test_us;
static unsigned main_loop_ticks;

bool voice_ota_voice_begin(void) {
  int idle = 0;
  return atomic_compare_exchange_strong(&activity, &idle, 1);
}

void voice_ota_voice_end(void) {
  if (!atomic_load(&boot_confirmed)) return;
  int voice = 1;
  (void)atomic_compare_exchange_strong(&activity, &voice, 0);
}

bool voice_ota_busy(void) { return atomic_load(&activity) == 2; }
bool voice_ota_boot_pending(void) { return !atomic_load(&boot_confirmed); }
unsigned voice_ota_percent(void) { return atomic_load(&progress_percent); }

static bool ota_partition_ready(void) {
  const esp_partition_t *running = esp_ota_get_running_partition();
  const esp_partition_t *next = esp_ota_get_next_update_partition(NULL);
  return running && next && running != next &&
         (running->subtype == ESP_PARTITION_SUBTYPE_APP_OTA_0 ||
          running->subtype == ESP_PARTITION_SUBTYPE_APP_OTA_1) &&
         next->size >= 0x300000;
}

static bool ota_nvs_read(const char *key, uint32_t *value) {
  nvs_handle_t nvs;
  if (nvs_open("zateya_ota", NVS_READWRITE, &nvs) != ESP_OK) return false;
  esp_err_t err = nvs_get_u32(nvs, key, value);
  nvs_close(nvs);
  if (err == ESP_ERR_NVS_NOT_FOUND) {
    *value = 0;
    return true;
  }
  return err == ESP_OK;
}

static bool ota_nvs_write(const char *key, uint32_t value) {
  nvs_handle_t nvs;
  if (nvs_open("zateya_ota", NVS_READWRITE, &nvs) != ESP_OK) return false;
  esp_err_t err = nvs_set_u32(nvs, key, value);
  if (err == ESP_OK) err = nvs_commit(nvs);
  nvs_close(nvs);
  return err == ESP_OK;
}

void voice_ota_confirm_boot(void) {
  if (atomic_load(&boot_confirmed)) return;
  ++main_loop_ticks;
  const esp_partition_t *running = esp_ota_get_running_partition();
  esp_ota_img_states_t state = ESP_OTA_IMG_UNDEFINED;
  bool pending = running &&
      esp_ota_get_state_partition(running, &state) == ESP_OK &&
      state == ESP_OTA_IMG_PENDING_VERIFY;
  if (pending && esp_timer_get_time() - boot_started_us > 30000000LL) {
    ESP_LOGE(TAG, "new image was not confirmed within 30 seconds");
    esp_restart();
  }
  uint32_t attempted = 0;
  if (!ota_nvs_read("attempted", &attempted) ||
      !ota_nvs_read("rejected", &rejected_seq)) {
    if (!pending) {
      atomic_store(&updates_disabled, true);
      atomic_store(&boot_confirmed, true);
    }
    return;
  }
  if (pending) {
    /* Check that the main loop has continued after initialization. */
    if (main_loop_ticks < 3) return;
    int64_t now = esp_timer_get_time();
    if (last_self_test_us && now - last_self_test_us < 1000000LL) return;
    last_self_test_us = now;
    if (!board_sticks3_local_self_test()) {
      return;
    }
    if (esp_ota_mark_app_valid_cancel_rollback() != ESP_OK) return;
    ESP_LOGI(TAG, "new image confirmed by local self-test");
  } else if (attempted > VOICE_OTA_RELEASE_SEQ) {
    rejected_seq = attempted;
    if (!ota_nvs_write("rejected", rejected_seq)) {
      atomic_store(&updates_disabled, true);
      atomic_store(&boot_confirmed, true);
      return;
    }
    ESP_LOGW(TAG, "release %lu rejected after rollback", (unsigned long)attempted);
  }
  if (attempted && !ota_nvs_write("attempted", 0))
    atomic_store(&updates_disabled, true);
  atomic_store(&boot_confirmed, true);
}

static bool make_url(const char *path, char *out, size_t capacity) {
  size_t length = strlen(gateway_base);
  while (length && gateway_base[length - 1] == '/') length--;
  int n = snprintf(out, capacity, "%.*s%s", (int)length, gateway_base, path);
  return n > 0 && (size_t)n < capacity;
}

static esp_http_client_handle_t open_get(const char *path, int *status,
                                         int64_t *content_length) {
  char url[320];
  if (!board_sticks3_network_ready() || !make_url(path, url, sizeof(url)))
    return NULL;
  esp_http_client_config_t config = {
    .url = url, .if_name = voice_wireguard_interface(),
    .timeout_ms = OTA_CHECK_TIMEOUT_MS, .disable_auto_redirect = true,
  };
  esp_http_client_handle_t client = esp_http_client_init(&config);
  if (!client) return NULL;
  if (esp_http_client_set_header(client, "X-Device-Id", device_id) != ESP_OK ||
      esp_http_client_set_header(client, "Authorization", authorization) != ESP_OK ||
      esp_http_client_open(client, 0) != ESP_OK) {
    esp_http_client_cleanup(client);
    return NULL;
  }
  *content_length = esp_http_client_fetch_headers(client);
  *status = esp_http_client_get_status_code(client);
  if (*content_length < 0) {
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return NULL;
  }
  return client;
}

static void close_get(esp_http_client_handle_t client) {
  if (!client) return;
  esp_http_client_close(client);
  esp_http_client_cleanup(client);
}

static bool hex_digest(const char *value) {
  if (!value || strlen(value) != 64) return false;
  for (size_t i = 0; i < 64; ++i)
    if (!((value[i] >= '0' && value[i] <= '9') ||
          (value[i] >= 'a' && value[i] <= 'f'))) return false;
  return true;
}

static bool decode_signed_manifest(const char *envelope_json,
                                   ota_manifest_t *manifest) {
  bool valid = false;
  cJSON *envelope = cJSON_Parse(envelope_json);
  if (!envelope) return false;
  const cJSON *raw_b64 = cJSON_GetObjectItemCaseSensitive(envelope, "manifest_b64");
  const cJSON *sig_b64 = cJSON_GetObjectItemCaseSensitive(envelope, "signature_b64");
  if (!cJSON_IsString(raw_b64) || !cJSON_IsString(sig_b64) ||
      strlen(raw_b64->valuestring) > 6000 || strlen(sig_b64->valuestring) > 256)
    goto done;
  unsigned char raw[4096], signature[128], hash[32];
  size_t raw_length = 0, signature_length = 0;
  if (mbedtls_base64_decode(raw, sizeof(raw) - 1, &raw_length,
                            (const unsigned char *)raw_b64->valuestring,
                            strlen(raw_b64->valuestring)) != 0 ||
      mbedtls_base64_decode(signature, sizeof(signature), &signature_length,
                            (const unsigned char *)sig_b64->valuestring,
                            strlen(sig_b64->valuestring)) != 0 ||
      !raw_length || !signature_length ||
      mbedtls_sha256(raw, raw_length, hash, 0) != 0) goto done;
  mbedtls_pk_context key;
  mbedtls_pk_init(&key);
  int key_status = mbedtls_pk_parse_public_key(&key,
      (const unsigned char *)VOICE_OTA_PUBLIC_KEY_PEM,
      sizeof(VOICE_OTA_PUBLIC_KEY_PEM));
  int signature_status = key_status == 0 ? mbedtls_pk_verify(
      &key, MBEDTLS_MD_SHA256, hash, sizeof(hash), signature, signature_length) : -1;
  mbedtls_pk_free(&key);
  if (signature_status != 0) goto done;
  raw[raw_length] = '\0';
  cJSON *body = cJSON_Parse((const char *)raw);
  if (!body) goto done;
  const cJSON *schema = cJSON_GetObjectItemCaseSensitive(body, "schema");
  const cJSON *board = cJSON_GetObjectItemCaseSensitive(body, "board");
  const cJSON *layout = cJSON_GetObjectItemCaseSensitive(body, "layout");
  const cJSON *sequence = cJSON_GetObjectItemCaseSensitive(body, "release_seq");
  const cJSON *size = cJSON_GetObjectItemCaseSensitive(body, "size");
  const cJSON *digest = cJSON_GetObjectItemCaseSensitive(body, "sha256");
  const cJSON *path = cJSON_GetObjectItemCaseSensitive(body, "image_path");
  const cJSON *key_id = cJSON_GetObjectItemCaseSensitive(body, "key_id");
  const cJSON *revision = cJSON_GetObjectItemCaseSensitive(body, "git_revision");
  if (cJSON_IsNumber(schema) && schema->valuedouble == 1 &&
      cJSON_IsString(board) && strcmp(board->valuestring, "sticks3") == 0 &&
      cJSON_IsString(layout) && strcmp(layout->valuestring, "ota-v1") == 0 &&
      cJSON_IsNumber(sequence) && sequence->valuedouble > 0 &&
      sequence->valuedouble <= UINT32_MAX &&
      sequence->valuedouble == (uint32_t)sequence->valuedouble &&
      cJSON_IsNumber(size) && size->valuedouble > 0 &&
      size->valuedouble <= 0x300000 &&
      size->valuedouble == (uint32_t)size->valuedouble &&
      cJSON_IsString(digest) && hex_digest(digest->valuestring) &&
      cJSON_IsString(key_id) &&
      strcmp(key_id->valuestring, VOICE_OTA_KEY_ID) == 0 &&
      cJSON_IsString(revision) && strlen(revision->valuestring) == 40 &&
      cJSON_IsString(path)) {
    char expected_path[128];
    snprintf(expected_path, sizeof(expected_path),
             "/api/firmware/images/%s.bin", digest->valuestring);
    if (strcmp(path->valuestring, expected_path) == 0) {
      manifest->sequence = (uint32_t)sequence->valuedouble;
      manifest->size = (size_t)size->valuedouble;
      snprintf(manifest->sha256, sizeof(manifest->sha256), "%s", digest->valuestring);
      snprintf(manifest->image_path, sizeof(manifest->image_path), "%s", expected_path);
      valid = true;
    }
  }
  cJSON_Delete(body);
done:
  cJSON_Delete(envelope);
  return valid;
}

static bool fetch_manifest(ota_manifest_t *manifest) {
  char path[128];
  snprintf(path, sizeof(path),
      "/api/firmware/manifest?board=sticks3&layout=ota-v1&current_seq=%lu",
      (unsigned long)VOICE_OTA_RELEASE_SEQ);
  int status = 0;
  int64_t length = 0;
  esp_http_client_handle_t client = open_get(path, &status, &length);
  if (!client) return false;
  if (status != 200 || length <= 0 || length >= OTA_MANIFEST_CAP) {
    close_get(client);
    return false;
  }
  char *body = malloc(OTA_MANIFEST_CAP);
  if (!body) {
    close_get(client);
    return false;
  }
  size_t used = 0;
  while (used < (size_t)length) {
    int n = esp_http_client_read(client, body + used, (int)(length - used));
    if (n <= 0) break;
    used += (size_t)n;
  }
  close_get(client);
  if (used != (size_t)length) {
    free(body);
    return false;
  }
  body[used] = '\0';
  bool valid = decode_signed_manifest(body, manifest);
  free(body);
  return valid;
}

static bool install_image(const ota_manifest_t *manifest,
                          const esp_partition_t *partition) {
  int status = 0;
  int64_t length = 0;
  esp_http_client_handle_t client = open_get(manifest->image_path, &status, &length);
  if (!client) return false;
  if (status != 200 || length != (int64_t)manifest->size) {
    close_get(client);
    return false;
  }
  esp_ota_handle_t handle;
  if (esp_ota_begin(partition, manifest->size, &handle) != ESP_OK) {
    close_get(client);
    return false;
  }
  mbedtls_sha256_context sha;
  mbedtls_sha256_init(&sha);
  bool ok = mbedtls_sha256_starts(&sha, 0) == 0;
  uint8_t chunk[4096];
  size_t received = 0;
  int64_t started = esp_timer_get_time();
  while (ok && received < manifest->size) {
    if (!board_sticks3_network_ready() || !board_sticks3_usb_powered() ||
        esp_timer_get_time() - started > OTA_DOWNLOAD_LIMIT_MS * 1000LL) {
      ok = false;
      break;
    }
    size_t remaining = manifest->size - received;
    int n = esp_http_client_read(client, (char *)chunk,
        (int)(remaining < sizeof(chunk) ? remaining : sizeof(chunk)));
    if (n <= 0 || esp_ota_write(handle, chunk, (size_t)n) != ESP_OK ||
        mbedtls_sha256_update(&sha, chunk, (size_t)n) != 0) {
      ok = false;
      break;
    }
    received += (size_t)n;
    atomic_store(&progress_percent, (unsigned)(received * 100u / manifest->size));
  }
  close_get(client);
  unsigned char digest[32];
  if (!ok || received != manifest->size || mbedtls_sha256_finish(&sha, digest) != 0)
    ok = false;
  mbedtls_sha256_free(&sha);
  if (ok) {
    char digest_hex[65];
    for (size_t i = 0; i < sizeof(digest); ++i)
      snprintf(digest_hex + i * 2, 3, "%02x", digest[i]);
    ok = strcmp(digest_hex, manifest->sha256) == 0;
  }
  if (ok) ok = esp_ota_end(handle) == ESP_OK;
  else (void)esp_ota_abort(handle);
  if (!ok || esp_ota_set_boot_partition(partition) != ESP_OK) return false;
  if (!ota_nvs_write("attempted", manifest->sequence)) {
    /* The image must not boot without a persisted rollback marker. */
    const esp_partition_t *running = esp_ota_get_running_partition();
    if (running) (void)esp_ota_set_boot_partition(running);
    return false;
  }
  ESP_LOGI(TAG, "release %lu installed; rebooting", (unsigned long)manifest->sequence);
  esp_restart();
  return true;
}

static void ota_task(void *arg) {
  (void)arg;
  const int64_t deadline = esp_timer_get_time() + 120000000LL;
  while (esp_timer_get_time() < deadline) {
    if (atomic_load(&boot_confirmed) && board_sticks3_network_ready() &&
        voice_gateway_health_status() == 200) break;
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
  if (!atomic_load(&boot_confirmed) || atomic_load(&updates_disabled) ||
      !board_sticks3_network_ready() ||
      voice_gateway_health_status() != 200) goto done;
  ota_manifest_t manifest = {0};
  if (!fetch_manifest(&manifest)) goto done;
  const esp_partition_t *next = esp_ota_get_next_update_partition(NULL);
  if (!next) goto done;
  const int64_t deferred_deadline = esp_timer_get_time() + 600000000LL;
  for (;;) {
    voice_ota_offer_t offer = {
      .current_seq = VOICE_OTA_RELEASE_SEQ, .rejected_seq = rejected_seq,
      .candidate_seq = manifest.sequence, .image_size = manifest.size,
      .slot_size = next->size, .network_ready = board_sticks3_network_ready(),
      .idle = atomic_load(&activity) == 0,
      .usb_powered = board_sticks3_usb_powered(),
      .signed_manifest_valid = true, .compatible = true,
    };
    voice_ota_decision_t decision = voice_ota_decide(&offer);
    if (decision == VOICE_OTA_IGNORE || esp_timer_get_time() > deferred_deadline)
      goto done;
    if (decision == VOICE_OTA_INSTALL) {
      int idle = 0;
      if (atomic_compare_exchange_strong(&activity, &idle, 2)) break;
    }
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
  atomic_store(&progress_percent, 0);
  if (!install_image(&manifest, next))
    ESP_LOGW(TAG, "update deferred after download/write failure");
  atomic_store(&activity, 0);
done:
  vTaskDelete(NULL);
}

bool voice_ota_start(const char *gateway, const char *device,
                     const char *token) {
  boot_started_us = esp_timer_get_time();
  if (!VOICE_OTA_PUBLIC_KEY_PEM[0] || VOICE_OTA_RELEASE_SEQ == 0 ||
      !ota_partition_ready()) {
    atomic_store(&boot_confirmed, true);
    return false;
  }
  if (!gateway || !device || !token || !*token) return false;
  if (snprintf(gateway_base, sizeof(gateway_base), "%s", gateway) >= sizeof(gateway_base) ||
      snprintf(device_id, sizeof(device_id), "%s", device) >= sizeof(device_id) ||
      snprintf(authorization, sizeof(authorization), "Bearer %s", token) >= sizeof(authorization))
    return false;
  return xTaskCreate(ota_task, "ota_pull", 16384, NULL, 2, NULL) == pdPASS;
}
#endif
