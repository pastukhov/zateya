#include "voice_tls.h"
#ifdef ESP_PLATFORM
#include "esp_sntp.h"
#include <time.h>
#include <string.h>
esp_http_client_handle_t voice_tls_client_init(const esp_http_client_config_t *config) {
  if (!config || !config->url || strncmp(config->url,"https://",8) || !voice_tls_ready()) return NULL;
  esp_http_client_config_t secure=*config;
  secure.crt_bundle_attach=esp_crt_bundle_attach;
  secure.skip_cert_common_name_check=false;
  secure.disable_auto_redirect=true;
  return esp_http_client_init(&secure);
}
void voice_tls_start(void) {
  if (esp_sntp_enabled()) return;
  esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
  esp_sntp_setservername(0, "pool.ntp.org");
  esp_sntp_setservername(1, "time.cloudflare.com");
  esp_sntp_init();
}
bool voice_tls_ready(void) { return time(NULL) > 1767225600; }
#else
void voice_tls_start(void) {}
bool voice_tls_ready(void) { return true; }
#endif
