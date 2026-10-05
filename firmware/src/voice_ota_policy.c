#include "voice_ota_policy.h"

voice_ota_decision_t voice_ota_decide(const voice_ota_offer_t *offer) {
  if (!offer || !offer->signed_manifest_valid || !offer->compatible ||
      offer->candidate_seq <= offer->current_seq ||
      offer->candidate_seq <= offer->rejected_seq ||
      offer->image_size == 0 || offer->image_size > offer->slot_size)
    return VOICE_OTA_IGNORE;
  if (!offer->network_ready || !offer->idle || !offer->usb_powered)
    return VOICE_OTA_DEFER;
  return VOICE_OTA_INSTALL;
}
