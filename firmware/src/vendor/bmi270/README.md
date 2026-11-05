# Bosch BMI270 SensorAPI

Vendored from the official https://github.com/boschsensortec/BMI270_SensorAPI
master snapshot, upstream commit `41129fcfe39c583ee5462d79195741945d51c1fe`
(2026-11-05 retrieval). BSD-3-Clause license is retained in every source header.
Only line endings and trailing whitespace are normalized for repository style;
code and the Bosch BMI270 configuration image are unchanged.

The adapter uses `bmi270_init`: chip ID, soft reset, config-image upload and
internal-status verification. It then configures a 25 Hz, +/-2g accelerometer,
disables gyro and enables accelerometer. Initialization happens once in a
separate FreeRTOS task; periodic display/audio code never waits for upload.
Read/write transactions use the existing shared I2C master bus and 20 ms timeout.
Failure preserves portrait; failed samples preserve the latest orientation.

Retrieved-file SHA256:

- `bmi2.c`: `8d42ba3281b8448f674a4df616a7e176a259ad3c38c53b6d2c49bfdbdb0a82db`
- `bmi2.h`: `a86c53c480974a0c56e24d9d4e736445c61ebc07addec6d3eaceddb8a2c97cd3`
- `bmi270.c`: `f6446867378bbcc90ea97ef6593555de8767ca20b799355c1b37c2cabb7b7b41`
- `bmi270.h`: `7979ec4c943e2825351bd9d3d267b63abc6f8314c1f13f1c37e95cabc3fc82c8`
- `bmi2_defs.h`: `39c2cf19bfbf735cb0ed209efd975a731be50dff71b432b24a6a2625b2b14304`
