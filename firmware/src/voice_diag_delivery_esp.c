#include "voice_diag_delivery_esp.h"

#ifdef ESP_PLATFORM
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#include "board_sticks3.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "voice_diag_delivery_policy.h"
#include "voice_diagnostics.h"
#include "voice_gateway_health.h"
#include "voice_wireguard.h"

static char url[256];
static char device[32];
static char authorization[200];
static char report[4608];
static atomic_uint pending_revision;
static atomic_bool idle_allowed;
static atomic_bool delivery_busy;
static const char *TAG = "voice_diag_delivery";

static bool post_report(void) {
  esp_http_client_config_t config = {
    .url = url,
    .if_name = voice_wireguard_interface(),
    .timeout_ms = 5000,
    .disable_auto_redirect = true,
  };
  esp_http_client_handle_t client = esp_http_client_init(&config);
  if (!client) return false;
  esp_http_client_set_method(client, HTTP_METHOD_POST);
  esp_http_client_set_header(client, "Content-Type", "application/json");
  esp_http_client_set_header(client, "X-Device-Id", device);
  esp_http_client_set_header(client, "Authorization", authorization);
  esp_http_client_set_post_field(client, report, (int)strlen(report));
  esp_err_t err = esp_http_client_perform(client);
  int status = err == ESP_OK ? esp_http_client_get_status_code(client) : 0;
  esp_http_client_cleanup(client);
  ESP_LOGI(TAG, "report HTTP status=%d", status);
  return status == 202;
}

static void delivery_task(void *arg) {
  (void)arg;
  voice_diag_delivery_t policy = {0};
  unsigned active_revision = 0;
  unsigned sent_revision = 0;
  for (;;) {
    unsigned requested = atomic_load(&pending_revision);
    if (requested != active_revision) {
      active_revision = requested;
      voice_diag_delivery_reset(&policy);
      report[0] = '\0';
    }
    bool network_ready = board_sticks3_network_ready() &&
                         voice_gateway_health_status() == 200;
    if (active_revision && active_revision != sent_revision &&
        voice_diag_delivery_due(&policy,
            (uint32_t)(esp_timer_get_time() / 1000), network_ready,
            atomic_load(&idle_allowed))) {
      if (!report[0] && !voice_diag_report_json(report, sizeof(report))) {
        ESP_LOGE(TAG, "report serialization failed");
        sent_revision = active_revision;
        continue;
      }
      atomic_store(&delivery_busy, true);
      bool sent = post_report();
      atomic_store(&delivery_busy, false);
      voice_diag_delivery_attempted(&policy, (uint32_t)(esp_timer_get_time() / 1000));
      if (sent) sent_revision = active_revision;
    }
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}

bool voice_diag_delivery_start(const char *gateway_base, const char *device_id,
                               const char *device_token) {
  if (!gateway_base || !device_id || !device_token || !*device_token) return false;
  size_t length = strlen(gateway_base);
  while (length && gateway_base[length - 1] == '/') length--;
  int n = snprintf(url, sizeof(url), "%.*s/api/devices/diagnostics",
                   (int)length, gateway_base);
  if (n <= 0 || (size_t)n >= sizeof(url)) return false;
  n = snprintf(device, sizeof(device), "%s", device_id);
  if (n <= 0 || (size_t)n >= sizeof(device)) return false;
  n = snprintf(authorization, sizeof(authorization), "Bearer %s", device_token);
  if (n <= 0 || (size_t)n >= sizeof(authorization)) return false;
  return xTaskCreate(delivery_task, "diag_delivery", 10240, NULL, 2, NULL) == pdPASS;
}

void voice_diag_delivery_request(void) { atomic_fetch_add(&pending_revision, 1); }
void voice_diag_delivery_set_idle(bool idle) { atomic_store(&idle_allowed, idle); }
bool voice_diag_delivery_busy(void) { return atomic_load(&delivery_busy); }
#endif
