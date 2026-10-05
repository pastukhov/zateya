#ifndef VOICE_DIAG_DELIVERY_POLICY_H
#define VOICE_DIAG_DELIVERY_POLICY_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
  uint8_t attempts;
  uint32_t last_attempt_ms;
} voice_diag_delivery_t;

void voice_diag_delivery_reset(voice_diag_delivery_t *delivery);
bool voice_diag_delivery_due(const voice_diag_delivery_t *delivery,
                             uint32_t now_ms, bool network_ready,
                             bool device_idle);
void voice_diag_delivery_attempted(voice_diag_delivery_t *delivery,
                                   uint32_t now_ms);

#endif
