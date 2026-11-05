# Four-way recorder screen Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** Four stable gravity-selected orientations with adaptive Russian UI.
**Architecture:** Host-testable orientation policy and framebuffer renderer;
bounded BMI270 reads on existing shared I2C bus; board integration transforms
logical framebuffer into the existing physical LCD window without changing audio.
**Tech Stack:** C, ESP-IDF, BMI270, existing screen_font, Unity/PlatformIO.
**Spec:** ../specs/2026-11-05-screen-orientation-design.md

## Constraints and review focus

500-ms stable orientation; flat/invalid samples retain orientation; no blocking
IMU retries in audio/main loop. Preserve QR quiet zone, Russian messages, timer,
OTA/error state priority and power indicators. No secrets or unrelated edits.
Test diagonal jitter, timestamp wrap, missing sensor, every corner transform,
long strings and QR in portrait/landscape. Verify BMI270 initialization against
official driver: chip ID alone is not a functioning accelerometer.

## Tasks

- [x] Add pure `screen_orientation` policy/header and native tests for four
  gravity directions, settling, flat/invalid/motion samples and wraparound.
- [x] Extract reusable status renderer from `board_sticks3.c` into screen UI
  modules with explicit dimensions/layout. Add pixel bounds/corner tests and
  render preview images for recording, error, setup, OTA and idle in all sides.
- [x] Add BMI270 hardware adapter using existing `board_sticks3_i2c_bus`, bounded
  transactions, documented official initialization and sensor axes. Disable
  unused gyro; handle failure without breaking recording or display. Keep
  ESP-only sources guarded/excluded from native as appropriate.
- [x] Integrate policy sampling and rotated flush into board display. Preserve
  fixed physical LCD offsets; avoid concurrent I2C ownership errors, repeated
  allocation and expensive initialization on display refresh.
- [x] Parent reviews diff, runs native suite and target build, inspects actual
  preview images. Fix failures, document hardware-only unknowns in handoff.
- [x] Commit task-only changes and push main. No automatic OTA publication in
  this task; physical orientation validation belongs to ASUS continuation.

Execution is delegated to Sol per AGENTS.md. Parent performs independent review
and verification. Existing USB/server investigation remains open.

Verification evidence and remaining physical checks: `docs/operations/screen-orientation.md`.
