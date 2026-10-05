#ifndef VOICE_OTA_POLICY_H
#define VOICE_OTA_POLICY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
  uint32_t current_seq;
  uint32_t rejected_seq;
  uint32_t candidate_seq;
  size_t image_size;
  size_t slot_size;
  bool network_ready;
  bool idle;
  bool usb_powered;
  bool signed_manifest_valid;
  bool compatible;
} voice_ota_offer_t;

typedef enum {
  VOICE_OTA_IGNORE = 0,
  VOICE_OTA_DEFER = 1,
  VOICE_OTA_INSTALL = 2,
} voice_ota_decision_t;

voice_ota_decision_t voice_ota_decide(const voice_ota_offer_t *offer);

#endif
