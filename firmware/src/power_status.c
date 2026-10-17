#include "power_status.h"
int power_battery_percent(unsigned mv) {
  if (mv < 2500 || mv > 4500) return -1;
  /* Same voltage estimate as M5Unified Power_Class, not a fuel gauge. */
  if (mv <= 3300) return 0;
  if (mv >= 4100) return 100;
  return (int)((mv - 3300) / 8);
}
bool power_battery_charging(bool valid, uint8_t source, uint8_t gpio_input) {
  /* StickS3 PM1 GPIO0 = CHG_STAT, active low; external power required. */
  return valid && (source & 3u) && !(gpio_input & 1u);
}
