#ifndef CONNECTIVITY_POLICY_H
#define CONNECTIVITY_POLICY_H

#include <stdbool.h>
#include <stdint.h>

/* One boot-wide 120-second connection window; Wi-Fi flaps do not restart it. */
#define CONNECTIVITY_BOOT_HOLD_MS 120000u
bool connectivity_sleep_hold(uint32_t started_ms, uint32_t now_ms,
                             bool wifi_configured, bool ready,
                             bool setup_ap_active);

#endif
