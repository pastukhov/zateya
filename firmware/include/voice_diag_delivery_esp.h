#ifndef VOICE_DIAG_DELIVERY_ESP_H
#define VOICE_DIAG_DELIVERY_ESP_H

#include <stdbool.h>

#ifdef ESP_PLATFORM
bool voice_diag_delivery_start(const char *gateway_base, const char *device_id,
                               const char *device_token);
void voice_diag_delivery_request(void);
void voice_diag_delivery_set_idle(bool idle);
bool voice_diag_delivery_busy(void);
#endif

#endif
