#include "connectivity_policy.h"

bool connectivity_sleep_hold(uint32_t started_ms, uint32_t now_ms,
                             bool wifi_configured, bool ready,
                             bool setup_ap_active) {
  return wifi_configured && !ready && !setup_ap_active &&
         (uint32_t)(now_ms - started_ms) < CONNECTIVITY_BOOT_HOLD_MS;
}
