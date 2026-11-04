#include <unity.h>
#include "voice_ota_policy.h"

static voice_ota_offer_t valid_offer(void) {
  return (voice_ota_offer_t){
    .current_seq = 1, .rejected_seq = 0, .candidate_seq = 2,
    .image_size = 1200000, .slot_size = 0x300000,
    .network_ready = true, .idle = true, .usb_powered = true,
    .signed_manifest_valid = true, .compatible = true,
  };
}

static void test_ota_only_accepts_new_signed_compatible_release(void) {
  voice_ota_offer_t offer = valid_offer();
  TEST_ASSERT_EQUAL(VOICE_OTA_INSTALL, voice_ota_decide(&offer));
  offer.signed_manifest_valid = false;
  TEST_ASSERT_EQUAL(VOICE_OTA_IGNORE, voice_ota_decide(&offer));
  offer = valid_offer(); offer.compatible = false;
  TEST_ASSERT_EQUAL(VOICE_OTA_IGNORE, voice_ota_decide(&offer));
  offer = valid_offer(); offer.candidate_seq = 1;
  TEST_ASSERT_EQUAL(VOICE_OTA_IGNORE, voice_ota_decide(&offer));
  offer = valid_offer(); offer.rejected_seq = 2;
  TEST_ASSERT_EQUAL(VOICE_OTA_IGNORE, voice_ota_decide(&offer));
  offer = valid_offer(); offer.image_size = 0;
  TEST_ASSERT_EQUAL(VOICE_OTA_IGNORE, voice_ota_decide(&offer));
  offer = valid_offer(); offer.image_size = offer.slot_size + 1;
  TEST_ASSERT_EQUAL(VOICE_OTA_IGNORE, voice_ota_decide(&offer));
}

static void test_ota_defers_when_network_voice_or_power_is_not_safe(void) {
  voice_ota_offer_t offer = valid_offer();
  offer.network_ready = false;
  TEST_ASSERT_EQUAL(VOICE_OTA_DEFER, voice_ota_decide(&offer));
  offer = valid_offer(); offer.idle = false;
  TEST_ASSERT_EQUAL(VOICE_OTA_DEFER, voice_ota_decide(&offer));
  offer = valid_offer(); offer.usb_powered = false;
  TEST_ASSERT_EQUAL(VOICE_OTA_DEFER, voice_ota_decide(&offer));
}

static void test_successful_manifest_checks_poll_slower_than_transient_failures(void) {
  TEST_ASSERT_EQUAL_UINT32(300000u, voice_ota_check_interval_ms(true));
  TEST_ASSERT_EQUAL_UINT32(60000u, voice_ota_check_interval_ms(false));
}

int main(void) {
  UNITY_BEGIN();
  RUN_TEST(test_ota_only_accepts_new_signed_compatible_release);
  RUN_TEST(test_ota_defers_when_network_voice_or_power_is_not_safe);
  RUN_TEST(test_successful_manifest_checks_poll_slower_than_transient_failures);
  return UNITY_END();
}
