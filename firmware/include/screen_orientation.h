#ifndef SCREEN_ORIENTATION_H
#define SCREEN_ORIENTATION_H
#include <stdbool.h>
#include <stdint.h>
typedef enum { SCREEN_ROTATION_0, SCREEN_ROTATION_90, SCREEN_ROTATION_180, SCREEN_ROTATION_270 } screen_rotation_t;
typedef struct { screen_rotation_t rotation, candidate; uint32_t since; bool pending; } screen_orientation_t;
bool screen_orientation_sample(screen_orientation_t *s, float x, float y, float z, bool valid, uint32_t now);
/* Official StickS3 BMI270 mounting: board X=raw Y, Y=-raw X, Z=raw Z. */
bool screen_orientation_sample_sticks3(screen_orientation_t *s, float raw_x, float raw_y, float raw_z, bool valid, uint32_t now);
int screen_orientation_width(screen_rotation_t r);
int screen_orientation_height(screen_rotation_t r);
/* Index into logical framebuffer for a physical panel pixel. */
int screen_orientation_index(screen_rotation_t r, int x, int y);
#endif
