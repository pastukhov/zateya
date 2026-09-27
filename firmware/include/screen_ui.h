#ifndef SCREEN_UI_H
#define SCREEN_UI_H

#include <stdint.h>
#include <stdbool.h>
#include "state_machine.h"

typedef enum {
  SCREEN_ICON_IDLE,
  SCREEN_ICON_LISTENING,
  SCREEN_ICON_THINKING,
  SCREEN_ICON_SPEAKING,
  SCREEN_ICON_ERROR
} screen_icon_t;

typedef enum {
  SCREEN_PROCESSING_TRANSCRIBING,
  SCREEN_PROCESSING_THINKING,
  SCREEN_PROCESSING_SYNTHESIZING,
} screen_processing_phase_t;

typedef struct {
  const char *title;
  const char *hint;
  uint16_t accent;
  screen_icon_t icon;
} screen_ui_view_t;

typedef enum {
  SCREEN_RECORDING_NORMAL,
  SCREEN_RECORDING_TEN_SECONDS,
  SCREEN_RECORDING_FIVE_SECONDS,
} screen_recording_warning_t;

typedef struct {
  char text[6];
  screen_recording_warning_t warning;
} screen_recording_timer_t;

#define SCREEN_STATUS_SERVER_X 23
#define SCREEN_STATUS_WIFI_X 67
#define SCREEN_STATUS_WG_X 111

/* -1: pending; 0: unreachable; positive: /health/ready HTTP result. */
uint16_t screen_ui_backend_color(int http_status);
bool screen_ui_draw_server_icon(uint16_t *pixels, int width, int height,
                                int center_x, uint16_t color);

screen_recording_timer_t screen_ui_recording_timer(uint32_t start_ms,
                                                   uint32_t now_ms,
                                                   uint32_t limit_seconds);

bool screen_ui_draw_setup(uint16_t *pixels, int width, int height, const char *ssid);

screen_ui_view_t screen_ui_view(state_t state);
screen_ui_view_t screen_ui_view_with_network(state_t state, screen_processing_phase_t phase,
                                             bool wifi_connected, bool vpn_ready);
screen_ui_view_t screen_ui_view_with_phase(state_t state,
                                           screen_processing_phase_t phase);

#endif
