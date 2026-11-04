#include "voice_tls.h"
#ifdef ESP_PLATFORM
#include "esp_sntp.h"
#include "esp_timer.h"
#include "board_sticks3.h"
#include "connectivity_policy.h"
#include "sdkconfig.h"
#if CONFIG_LWIP_SNTP_MAX_SERVERS < 2
#error "TLS time synchronization requires two SNTP servers"
#endif
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
  /* Called by the health task only, after DHCP; retry failed sync at most
     once a minute, including across reconnects. A valid clock needs no reset. */
  static connectivity_retry_t retry;
  uint32_t now_ms = (uint32_t)(esp_timer_get_time() / 1000);
  if (!connectivity_retry_due(&retry, now_ms,
                             board_sticks3_ip_ready() &&
                             (!esp_sntp_enabled() || !voice_tls_ready()),
                             60000u)) return;
  if (esp_sntp_enabled()) esp_sntp_stop();
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
