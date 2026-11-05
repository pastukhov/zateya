#ifndef SCREEN_RENDERER_H
#define SCREEN_RENDERER_H
#include "screen_ui.h"
#include "screen_orientation.h"
typedef struct {
 screen_ui_view_t view; state_t state; int phase, backend_status, battery_percent;
 bool wifi, usb, charging, setup, hold_mode; unsigned wake_status;
 const char *ssid, *device_id;
 screen_recording_timer_t timer;
} screen_render_model_t;
bool screen_render(uint16_t *pixels, int width, int height, const screen_render_model_t *model);
#endif
