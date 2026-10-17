#pragma once
#include <stdbool.h>
#include <stdint.h>
/* -1 means unavailable. Percentage is an estimate from battery voltage. */
int power_battery_percent(unsigned millivolts);
bool power_battery_charging(bool valid, uint8_t source, uint8_t gpio_input);
