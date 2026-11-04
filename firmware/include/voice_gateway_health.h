#ifndef VOICE_GATEWAY_HEALTH_H
#define VOICE_GATEWAY_HEALTH_H

#include <stdbool.h>

/* HTTP status: -2 waiting for clock, -1 pending, 0 unreachable. */
#define VOICE_GATEWAY_WAITING_TIME (-2)
bool voice_gateway_health_start(const char *gateway_base);
int voice_gateway_health_status(void);

#endif
