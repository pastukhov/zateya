#ifndef VOICE_CAPTURE_STORAGE_H
#define VOICE_CAPTURE_STORAGE_H
#include "ring_buffer.h"
#include <string.h>

typedef uint8_t *(*voice_capture_allocate_fn)(size_t bytes);
/* Caller owns lifetime storage. Reinitialization resets the ring but reuses
 * successful allocation. Failure clears ring control; no fallback allocation. */
static inline bool voice_capture_storage_init(ring_buffer_t *ring, uint8_t **storage,
                                               voice_capture_allocate_fn allocate) {
  if (!ring || !storage) return false;
  if (!*storage && allocate) *storage = allocate(RING_BUFFER_CAPACITY_DEFAULT);
  if (!*storage) {
    memset(ring, 0, sizeof(*ring));
    return false;
  }
  return ring_buffer_init(ring, *storage, RING_BUFFER_CAPACITY_DEFAULT);
}
#endif
