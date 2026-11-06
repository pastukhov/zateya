#include <unity.h>
#include "pmic_setup.h"
#include "../test_main/fakes/hw_fakes.c"

typedef struct {
  uint8_t regs[256];
  unsigned reads;
  unsigned writes;
  unsigned delays;
  unsigned fail_read_at;
  unsigned fail_write_at;
  bool fail_all;
} fake_t;

static bool read_reg(void *context, uint8_t reg, uint8_t *value) {
  fake_t *f = context;
  ++f->reads;
  if (f->fail_all || f->reads == f->fail_read_at) return false;
  *value = f->regs[reg];
  return true;
}

static bool write_reg(void *context, uint8_t reg, uint8_t value) {
  fake_t *f = context;
  ++f->writes;
  if (f->fail_all || f->writes == f->fail_write_at) return false;
  f->regs[reg] = value;
  return true;
}

static void delay_ms(void *context, unsigned ms) {
  fake_t *f = context;
  f->delays += ms;
}

static pmic_setup_io_t io_for(fake_t *f) {
  return (pmic_setup_io_t){read_reg, write_reg, delay_ms, f};
}

void setUp(void) {}
void tearDown(void) {}

static void test_first_probe_nack_then_setup_succeeds(void) {
  fake_t f = {.fail_read_at = 1};
  pmic_setup_io_t io = io_for(&f);
  TEST_ASSERT_TRUE(pmic_setup_run(&io));
  TEST_ASSERT_EQUAL_HEX8(0x0c, f.regs[0x10] & 0x0c);
  TEST_ASSERT_EQUAL_HEX8(0x04, f.regs[0x11] & 0x0c);
  TEST_ASSERT_GREATER_OR_EQUAL(1, f.delays);
}

static void test_persistent_failure_is_bounded(void) {
  fake_t f = {.fail_all = true};
  pmic_setup_io_t io = io_for(&f);
  TEST_ASSERT_FALSE(pmic_setup_run(&io));
  TEST_ASSERT_EQUAL_UINT(0, f.writes);
  TEST_ASSERT_LESS_OR_EQUAL(3, f.reads);
}

static void test_failed_mid_sequence_restarts_and_preserves_bits(void) {
  fake_t f = {.fail_write_at = 3};
  f.regs[0x06] = 0xa5;
  f.regs[0x16] = 0x5a;
  f.regs[0x13] = 0xf3;
  f.regs[0x10] = 0x91;
  f.regs[0x11] = 0xe3;
  pmic_setup_io_t io = io_for(&f);
  TEST_ASSERT_TRUE(pmic_setup_run(&io));
  TEST_ASSERT_EQUAL_HEX8(0xa5 & ~0x10, f.regs[0x06]);
  TEST_ASSERT_EQUAL_HEX8(0x5a & ~0xf0, f.regs[0x16]);
  TEST_ASSERT_EQUAL_HEX8(0xf3 & ~0x0c, f.regs[0x13]);
  TEST_ASSERT_EQUAL_HEX8(0x91 | 0x0c, f.regs[0x10]);
  TEST_ASSERT_EQUAL_HEX8((0xe3 & ~0x0c) | 0x04, f.regs[0x11]);
  TEST_ASSERT_GREATER_OR_EQUAL(1, f.delays);
}

int main(void) {
  UNITY_BEGIN();
  RUN_TEST(test_first_probe_nack_then_setup_succeeds);
  RUN_TEST(test_persistent_failure_is_bounded);
  RUN_TEST(test_failed_mid_sequence_restarts_and_preserves_bits);
  return UNITY_END();
}
