#include "connectivity_policy.h"

bool connectivity_sleep_hold(uint32_t started_ms, uint32_t now_ms,
                             bool wifi_configured, bool ready,
                             bool setup_ap_active) {
  return wifi_configured && !ready && !setup_ap_active &&
         (uint32_t)(now_ms - started_ms) < CONNECTIVITY_BOOT_HOLD_MS;
}

bool connectivity_retry_due(connectivity_retry_t *retry, uint32_t now_ms,
                            bool ready, uint32_t interval_ms) {
  if (!ready || (retry->attempted &&
                 (uint32_t)(now_ms - retry->last_attempt_ms) < interval_ms))
    return false;
  retry->attempted = true;
  retry->last_attempt_ms = now_ms;
  return true;
}
