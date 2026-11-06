# Home recorder TLS memory failure

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Sol implements; parent independently verifies and releases.

**Goal:** Complete voice-answer downloads on the home StickS3 without AES DMA allocation failure.

**Architecture:** Preserve authenticated HTTPS, PSRAM TLS buffers, codecs and OTA layout. Select software AES for this audio-heavy target so TLS record processing does not require transient internal DMA bounce buffers while the speaker is active. Verify the actual ESP-IDF configuration and hardware performance before declaring the fix successful.

**Tech Stack:** ESP-IDF 5.5.3, PlatformIO, Mbed TLS, ESP32-S3.

**Evidence/spec:** USB `/tmp/zateya-home-serial.log`, second physical trial: `esp-aes: Failed to allocate memory`, TLS -0x0001/-0x7180, audio read failed after19482 bytes, hardware error during audio. Server completed STT/LLM/TTS. ESP-IDF AES DMA implementation allocates internal DMA buffers/descriptors. Device7ce8b1e4b780 installed OTA33 from20. LittleFS mount also fails; this is separately observed and must not be erased as part of this fix.

## Constraints and review focus

- Keep certificate/hostname verification and TLS authentication unchanged.
- Do not erase flash, modify NVS, partitions, device settings or unknown cue-store data.
- Preserve MP3 and legacy WAV support and chosen voice.
- Software AES may cost CPU; measure real download/playback, not only compilation.
- Failed downloads must remain failures; never hide TLS truncation.

## Task1: Remove AES DMA dependency from TLS

Files: `firmware/sdkconfig.defaults`, an appropriate existing configuration check if present, and operation notes. Generated `sdkconfig.sticks3` is not a substitute for defaults used by release builds.

- [ ] Inspect ESP-IDF AES configuration and confirm disabling `CONFIG_MBEDTLS_HARDWARE_AES` selects software AES without disabling AES/GCM/TLS.
- [ ] Add the minimal target default and explain the observed internal DMA allocation failure. Do not patch vendor sources or shrink TLS record limits.
- [ ] Run native firmware tests and target build; inspect generated config to prove hardware AES is off, software AES/GCM and external TLS allocations remain enabled.
- [ ] Parent reviews changes and independently runs relevant tests/build. Commit/push only task files after passing checks.

## Task2: Release and physical verification

- [ ] Build next signed OTA through existing release script, verify signature/hash/size and publish using established procedure, preserving rollback.
- [ ] Confirm installation on device7ce8b1e4b780 by revision/sequence and USB journal.
- [ ] User makes a voice trial; verify completed audio transfer, absence of AES allocation/TLS errors, and audible response. Do not call publication hardware success.
- [ ] Document remaining LittleFS problem separately; its recovery needs inspection of this device's actual flash before any destructive proposal.
