#pragma once
#include <stdbool.h>
#ifdef ESP_PLATFORM
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
esp_http_client_handle_t voice_tls_client_init(const esp_http_client_config_t *config);
#endif
void voice_tls_start(void);
bool voice_tls_ready(void);
