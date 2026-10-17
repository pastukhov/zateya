#include "voice_config_httpd.h"
#include <stdio.h>

// Never serialize server values: only an explicit allowlist of presence flags.
bool voice_config_public_status(const voice_settings_t *s, char *out, size_t capacity) {
  if (!s || !out || !capacity) return false;
  int length = snprintf(out, capacity,
      "{\"gateway_url_set\":%s,\"device_token_set\":%s,\"sleep_timeout_seconds\":%lu,\"wake_enabled\":%s,\"wake_pause_seconds\":%lu}",
      s->gateway_url[0] ? "true" : "false",
      s->device_token[0] ? "true" : "false",
      (unsigned long)s->sleep_timeout_seconds, s->wake_enabled ? "true" : "false",
      (unsigned long)(s->wake_pause_ms/1000));
  if (length < 0 || (size_t)length >= capacity) { out[0] = 0; return false; }
  return true;
}
