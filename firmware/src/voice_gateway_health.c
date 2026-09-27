#include "voice_gateway_health.h"

#ifdef ESP_PLATFORM

#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "board_sticks3.h"
#include "voice_wireguard.h"

#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

static char s_health_url[256];
static _Atomic int s_health_status = -1;

static void health_task(void *arg) {
  (void)arg;
  for (;;) {
    if (!board_sticks3_network_ready()) {
      atomic_store(&s_health_status, 0);
      vTaskDelay(pdMS_TO_TICKS(1000));
      continue;
    }
    esp_http_client_config_t config = {
      .url = s_health_url,
      .if_name = voice_wireguard_interface(),
      .timeout_ms = 2500,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    int status = 0;
    if (client) {
      if (esp_http_client_perform(client) == ESP_OK)
        status = esp_http_client_get_status_code(client);
      esp_http_client_cleanup(client);
    }
    int previous = atomic_exchange(&s_health_status, status);
    if (previous != status)
      ESP_LOGI("gateway_health", "readiness HTTP status: %d", status);
    vTaskDelay(pdMS_TO_TICKS(15000));
  }
}

bool voice_gateway_health_start(const char *gateway_base) {
  if (!gateway_base || !gateway_base[0]) return false;
  size_t length = strlen(gateway_base);
  while (length && gateway_base[length - 1] == '/') --length;
  int written = snprintf(s_health_url, sizeof(s_health_url), "%.*s/health/ready",
                         (int)length, gateway_base);
  if (written <= 0 || (size_t)written >= sizeof(s_health_url)) return false;
  return xTaskCreate(health_task, "gateway_health", 4096, NULL, 3, NULL) == pdPASS;
}

int voice_gateway_health_status(void) {
  if (!board_sticks3_network_ready()) {
    atomic_store(&s_health_status, 0);
    return 0;
  }
  return atomic_load(&s_health_status);
}

#else

bool voice_gateway_health_start(const char *gateway_base) {
  (void)gateway_base;
  return false;
}

int voice_gateway_health_status(void) { return -1; }

#endif
