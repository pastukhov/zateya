#ifndef VOICE_OTA_H
#define VOICE_OTA_H

#include <stdbool.h>

/* A voice turn and a flash update share one activity gate. */
bool voice_ota_voice_begin(void);
void voice_ota_voice_end(void);
bool voice_ota_busy(void);
bool voice_ota_boot_pending(void);
unsigned voice_ota_percent(void);
bool voice_ota_start(const char *gateway, const char *device_id,
                     const char *device_token);
void voice_ota_confirm_boot(void);

#endif
