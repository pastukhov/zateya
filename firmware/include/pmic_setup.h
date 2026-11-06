#ifndef PMIC_SETUP_H
#define PMIC_SETUP_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
  bool (*read)(void *context, uint8_t reg, uint8_t *value);
  bool (*write)(void *context, uint8_t reg, uint8_t value);
  void (*delay_ms)(void *context, unsigned ms);
  void *context;
} pmic_setup_io_t;

bool pmic_setup_run(const pmic_setup_io_t *io);

#endif
