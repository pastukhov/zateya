#include "pmic_setup.h"

static bool update(const pmic_setup_io_t *io, uint8_t reg,
                   uint8_t mask, uint8_t value) {
  uint8_t old;
  return io->read(io->context, reg, &old) &&
      io->write(io->context, reg, (old & ~mask) | (value & mask));
}

bool pmic_setup_run(const pmic_setup_io_t *io) {
  if (!io || !io->read || !io->write || !io->delay_ms) return false;
  for (unsigned attempt = 0; attempt < 3; ++attempt) {
    uint8_t id;
    bool ready = io->read(io->context, 0x00, &id) &&
        io->write(io->context, 0x09, 0) &&
        update(io, 0x06, 0x10, 0) &&
        update(io, 0x16, 0xf0, 0) &&
        update(io, 0x13, 0x0c, 0) &&
        update(io, 0x10, 0x0c, 0x0c) &&
        update(io, 0x11, 0x0c, 0x04);
    if (ready) return true;
    if (attempt < 2) io->delay_ms(io->context, 2);
  }
  return false;
}
