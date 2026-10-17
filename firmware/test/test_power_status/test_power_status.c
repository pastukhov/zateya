#include <unity.h>
#include "power_status.h"
#include "screen_ui.h"
#include "../test_main/fakes/hw_fakes.c"
void setUp(void) {}
void tearDown(void) {}
void test_voltage(void) {
 TEST_ASSERT_EQUAL(-1,power_battery_percent(0));
 TEST_ASSERT_EQUAL(-1,power_battery_percent(5000));
 TEST_ASSERT_EQUAL(0,power_battery_percent(3200));
 TEST_ASSERT_EQUAL(50,power_battery_percent(3700));
 TEST_ASSERT_EQUAL(100,power_battery_percent(4200));
}
void test_charge(void) {
 TEST_ASSERT_TRUE(power_battery_charging(true,5,0));
 TEST_ASSERT_FALSE(power_battery_charging(true,5,1));
 TEST_ASSERT_FALSE(power_battery_charging(true,4,0));
 TEST_ASSERT_FALSE(power_battery_charging(false,5,0));
}
void test_header_bounds(void) {
 uint16_t pixels[135*32]={0};
 TEST_ASSERT_TRUE(screen_ui_draw_power(pixels,135,32,100,true,true));
 for(int y=0;y<32;y++) for(int x=0;x<135;x++)
  if(x<61 || y<12 || y>=28) TEST_ASSERT_EQUAL(0,pixels[y*135+x]);
 TEST_ASSERT_FALSE(screen_ui_draw_power(pixels,100,32,100,true,true));
}
int main(void) { UNITY_BEGIN(); RUN_TEST(test_voltage); RUN_TEST(test_charge);RUN_TEST(test_header_bounds);return UNITY_END(); }
