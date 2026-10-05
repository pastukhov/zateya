#include "voice_diag_delivery_policy.h"

#include <string.h>

void voice_diag_delivery_reset(voice_diag_delivery_t *delivery) {
  if (delivery) memset(delivery, 0, sizeof(*delivery));
}

bool voice_diag_delivery_due(const voice_diag_delivery_t *delivery,
                             uint32_t now_ms, bool network_ready,
                             bool device_idle) {
  if (!delivery || !network_ready || !device_idle || delivery->attempts >= 3)
    return false;
  static const uint32_t delay_ms[] = {0, 5000, 15000};
  return delivery->attempts == 0 ||
         (uint32_t)(now_ms - delivery->last_attempt_ms) >= delay_ms[delivery->attempts];
}

void voice_diag_delivery_attempted(voice_diag_delivery_t *delivery,
                                   uint32_t now_ms) {
  if (!delivery || delivery->attempts >= 3) return;
  delivery->attempts++;
  delivery->last_attempt_ms = now_ms;
}
