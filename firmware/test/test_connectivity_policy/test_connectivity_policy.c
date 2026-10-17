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

int main(void) {
  UNITY_BEGIN();
  RUN_TEST(test_connection_hold_is_bounded_and_wrap_safe);
  return UNITY_END();
}
