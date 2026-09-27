#ifndef VOICE_GATEWAY_HEALTH_H
#define VOICE_GATEWAY_HEALTH_H

#include <stdbool.h>

/* HTTP status of the latest /health/ready probe: -1 pending, 0 unreachable. */
bool voice_gateway_health_start(const char *gateway_base);
int voice_gateway_health_status(void);

#endif
