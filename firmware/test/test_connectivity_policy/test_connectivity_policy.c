#include <unity.h>

#include "connectivity_policy.h"
#include "screen_ui.h"
#include "voice_diagnostics.h"

static void test_connection_hold_is_bounded_and_wrap_safe(void) {
  uint32_t start = UINT32_MAX - 1000u;
  TEST_ASSERT_TRUE(connectivity_sleep_hold(start, start + 30000u, true, false, false));
  TEST_ASSERT_TRUE(connectivity_sleep_hold(start, start + 119999u, true, false, false));
  TEST_ASSERT_FALSE(connectivity_sleep_hold(start, start + 120000u, true, false, false));
  TEST_ASSERT_FALSE(connectivity_sleep_hold(start, start + 5000u, true, true, false));
  TEST_ASSERT_FALSE(connectivity_sleep_hold(start, start + 5000u, true, false, true));
}

static void test_retry_waits_for_network_and_recovers_after_late_dhcp(void) {
  connectivity_retry_t retry = {0};
  TEST_ASSERT_FALSE(connectivity_retry_due(&retry, 0, false, 60000));
  TEST_ASSERT_FALSE(connectivity_retry_due(&retry, 120000, false, 60000));
  TEST_ASSERT_TRUE(connectivity_retry_due(&retry, 180000, true, 60000));
  TEST_ASSERT_FALSE(connectivity_retry_due(&retry, 181000, true, 60000));
  TEST_ASSERT_FALSE(connectivity_retry_due(&retry, 190000, false, 60000));
  TEST_ASSERT_FALSE(connectivity_retry_due(&retry, 200000, true, 60000));
  TEST_ASSERT_TRUE(connectivity_retry_due(&retry, 240000, true, 60000));
}

static void test_retry_cadence_wraps_and_remains_live_after_many_checks(void) {
  connectivity_retry_t retry = {0};
  uint32_t start = UINT32_MAX - 1000u;
  TEST_ASSERT_TRUE(connectivity_retry_due(&retry, start, true, 60000));
  TEST_ASSERT_FALSE(connectivity_retry_due(&retry, start + 59999u, true, 60000));
  TEST_ASSERT_TRUE(connectivity_retry_due(&retry, start + 60000u, true, 60000));
  for (uint32_t i = 2; i < 20; ++i)
    TEST_ASSERT_TRUE(connectivity_retry_due(&retry, start + i * 60000u, true, 60000));
}

static void test_first_boot_readiness_survives_turn_reset_and_reconnect(void) {
  TEST_ASSERT_EQUAL_UINT32(0, voice_diag_ready_ms(VOICE_DIAG_WIFI_READY));
  voice_diag_mark_ready(VOICE_DIAG_WIFI_READY, 2400);
  voice_diag_mark_ready(VOICE_DIAG_TLS_READY, 9800);
  voice_diag_mark_ready(VOICE_DIAG_BACKEND_READY, 12000);
  voice_diag_reset();
  voice_diag_mark_ready(VOICE_DIAG_WIFI_READY, 90000);
  TEST_ASSERT_EQUAL_UINT32(2400, voice_diag_ready_ms(VOICE_DIAG_WIFI_READY));
  TEST_ASSERT_EQUAL_UINT32(9800, voice_diag_ready_ms(VOICE_DIAG_TLS_READY));
  TEST_ASSERT_EQUAL_UINT32(12000, voice_diag_ready_ms(VOICE_DIAG_BACKEND_READY));
}

int main(void) {
  UNITY_BEGIN();
  RUN_TEST(test_connection_hold_is_bounded_and_wrap_safe);
  RUN_TEST(test_retry_waits_for_network_and_recovers_after_late_dhcp);
  RUN_TEST(test_retry_cadence_wraps_and_remains_live_after_many_checks);
  RUN_TEST(test_first_boot_readiness_survives_turn_reset_and_reconnect);
  return UNITY_END();
}
