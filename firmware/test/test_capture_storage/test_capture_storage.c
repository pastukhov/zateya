#include <string.h>
#include <unity.h>
#include "voice_capture_storage.h"

static uint8_t arena[32768], input[30000], output[32768];
static unsigned allocations;
static size_t requested;
static bool fail_allocation;

static uint8_t *allocate(size_t size) {
  ++allocations;
  requested = size;
  return fail_allocation ? NULL : arena;
}

void setUp(void) {
  allocations = 0;
  requested = 0;
  fail_allocation = false;
}
void tearDown(void) {}

static void allocation_failure_leaves_no_capture_buffer(void) {
  ring_buffer_t ring;
  memset(&ring, 0xa5, sizeof(ring));
  uint8_t *storage = NULL;
  fail_allocation = true;
  TEST_ASSERT_FALSE(voice_capture_storage_init(&ring, &storage, allocate));
  TEST_ASSERT_EQUAL(1, allocations);
  TEST_ASSERT_EQUAL(32768, requested);
  TEST_ASSERT_NULL(storage);
  TEST_ASSERT_NULL(ring.data);
  TEST_ASSERT_EQUAL(0, ring_buffer_capacity(&ring));
  TEST_ASSERT_EQUAL(0, ring_buffer_count(&ring));
  TEST_ASSERT_FALSE(ring_buffer_overflow(&ring));
  /* Recovery can retry the allocation, without an internal-memory fallback. */
  fail_allocation = false;
  TEST_ASSERT_TRUE(voice_capture_storage_init(&ring, &storage, allocate));
  TEST_ASSERT_EQUAL(2, allocations);
  TEST_ASSERT_EQUAL_PTR(arena, ring.data);
}

static void reinitialization_reuses_lifetime_storage_and_clears_state(void) {
  ring_buffer_t ring = {0};
  uint8_t *storage = NULL;
  TEST_ASSERT_TRUE(voice_capture_storage_init(&ring, &storage, allocate));
  TEST_ASSERT_EQUAL(30000, ring_buffer_push(&ring, input, 30000));
  TEST_ASSERT_EQUAL(2768, ring_buffer_push(&ring, input, 2768));
  TEST_ASSERT_EQUAL(0, ring_buffer_push(&ring, input, 1));
  TEST_ASSERT_TRUE(ring_buffer_overflow(&ring));
  fail_allocation = true;
  TEST_ASSERT_TRUE(voice_capture_storage_init(&ring, &storage, allocate));
  TEST_ASSERT_EQUAL(1, allocations);
  TEST_ASSERT_EQUAL_PTR(arena, storage);
  TEST_ASSERT_EQUAL_PTR(arena, ring.data);
  TEST_ASSERT_EQUAL(32768, ring_buffer_capacity(&ring));
  TEST_ASSERT_EQUAL(0, ring_buffer_count(&ring));
  TEST_ASSERT_FALSE(ring_buffer_overflow(&ring));
}

static void allocated_capture_ring_preserves_order_across_wrap(void) {
  ring_buffer_t ring = {0};
  uint8_t *storage = NULL;
  TEST_ASSERT_TRUE(voice_capture_storage_init(&ring, &storage, allocate));
  for (size_t i = 0; i < sizeof(input); ++i) input[i] = (uint8_t)(i * 17u + 3u);
  TEST_ASSERT_EQUAL(30000, ring_buffer_push(&ring, input, 30000));
  TEST_ASSERT_EQUAL(25000, ring_buffer_pop(&ring, output, 25000));
  TEST_ASSERT_EQUAL_MEMORY(input, output, 25000);
  TEST_ASSERT_EQUAL(20000, ring_buffer_push(&ring, input, 20000));
  TEST_ASSERT_EQUAL(25000, ring_buffer_pop(&ring, output, sizeof(output)));
  TEST_ASSERT_EQUAL_MEMORY(input + 25000, output, 5000);
  TEST_ASSERT_EQUAL_MEMORY(input, output + 5000, 20000);
  TEST_ASSERT_TRUE(ring_buffer_empty(&ring));
  TEST_ASSERT_FALSE(ring_buffer_overflow(&ring));
}

int main(void) {
  UNITY_BEGIN();
  RUN_TEST(allocation_failure_leaves_no_capture_buffer);
  RUN_TEST(reinitialization_reuses_lifetime_storage_and_clears_state);
  RUN_TEST(allocated_capture_ring_preserves_order_across_wrap);
  return UNITY_END();
}
