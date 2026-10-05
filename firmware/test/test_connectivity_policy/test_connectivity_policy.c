#include <unity.h>

#include "connectivity_policy.h"
#include "screen_ui.h"

static void test_connection_hold_is_bounded_and_wrap_safe(void) {
  uint32_t start = UINT32_MAX - 1000u;
  TEST_ASSERT_TRUE(connectivity_sleep_hold(start, start + 30000u, true, false, false));
  TEST_ASSERT_TRUE(connectivity_sleep_hold(start, start + 119999u, true, false, false));
  TEST_ASSERT_FALSE(connectivity_sleep_hold(start, start + 120000u, true, false, false));
  TEST_ASSERT_FALSE(connectivity_sleep_hold(start, start + 5000u, true, true, false));
  TEST_ASSERT_FALSE(connectivity_sleep_hold(start, start + 5000u, true, false, true));
}

static void test_wireguard_icon_waits_for_wifi(void) {
  TEST_ASSERT_EQUAL_HEX16(0x74B3, screen_ui_wireguard_color("wifi", false, 4));
  TEST_ASSERT_EQUAL_HEX16(0x74B3, screen_ui_wireguard_color("connecting", false, 4));
  TEST_ASSERT_EQUAL_HEX16(0x74B3, screen_ui_wireguard_color("connected", false, 4));
  TEST_ASSERT_EQUAL_HEX16(0x74B3, screen_ui_wireguard_color("disabled", true, 4));
  TEST_ASSERT_EQUAL_HEX16(0xFD20, screen_ui_wireguard_color("time", true, 4));
  TEST_ASSERT_EQUAL_HEX16(0x74B3, screen_ui_wireguard_color("time", true, 0));
  TEST_ASSERT_EQUAL_HEX16(0x07E0, screen_ui_wireguard_color("connected", true, 4));
  TEST_ASSERT_EQUAL_HEX16(0xF800, screen_ui_wireguard_color("error", true, 4));
}

static void test_vpn_wait_has_specific_screen_copy(void) {
  screen_ui_view_t view = screen_ui_view_with_connection(STATE_IDLE,
      SCREEN_PROCESSING_THINKING, true, "time", false, 0);
  TEST_ASSERT_EQUAL_STRING("СИНХРОНИЗАЦИЯ\nВРЕМЕНИ", view.hint);
  view = screen_ui_view_with_connection(STATE_IDLE,
      SCREEN_PROCESSING_THINKING, true, "connecting", false, 0);
  TEST_ASSERT_EQUAL_STRING("ПОДКЛЮЧАЮ VPN", view.hint);
  view = screen_ui_view_with_connection(STATE_IDLE,
      SCREEN_PROCESSING_THINKING, false, "connecting", false, 0);
  TEST_ASSERT_EQUAL_STRING("ОЖИДАЮ WI-FI", view.hint);
}

int main(void) {
  UNITY_BEGIN();
  RUN_TEST(test_connection_hold_is_bounded_and_wrap_safe);
  RUN_TEST(test_wireguard_icon_waits_for_wifi);
  RUN_TEST(test_vpn_wait_has_specific_screen_copy);
  return UNITY_END();
}
