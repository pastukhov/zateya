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

- [x] Inspect ESP-IDF AES configuration and confirm disabling `CONFIG_MBEDTLS_HARDWARE_AES` selects software AES without disabling AES/GCM/TLS.
- [x] Add the minimal target default and explain the observed internal DMA allocation failure. Do not patch vendor sources or shrink TLS record limits.
- [x] Run native firmware tests and target build; inspect generated config to prove hardware AES is off, software AES/GCM and external TLS allocations remain enabled.
- [x] Parent reviews changes and independently runs relevant tests/build. Commit/push only task files after passing checks.

## Task2: Release and physical verification

- [x] Build next signed OTA through existing release script, verify signature/hash/size and publish using established procedure, preserving rollback.
- [x] Confirm installation on device7ce8b1e4b780 by revision/sequence and USB journal.
- [ ] User makes a voice trial; verify completed audio transfer, absence of AES allocation/TLS errors, and audible response. Do not call publication hardware success.
- [ ] Document remaining LittleFS problem separately; its recovery needs inspection of this device's actual flash before any destructive proposal.

## Verification checkpoint

Sol implemented the configuration change; parent independently reviewed it,
passed160/160 native tests and the StickS3 build. Commit `f60621a` is pushed.
A separate clean225-file snapshot produced signed OTA34,1697568 bytes, SHA256
`a1df444f756437fa373a76f4141640353e64afffba3910e4da22ee3b13a1e8ef`.
Generated release configuration confirms software AES/GCM, external TLS memory,
CA bundle, rollback and two SNTP servers. External HTTPS signature/hash/full-image
verification passed; current34 returns204. Stable-pointer read permission was
corrected before the successful update check.

USB `/tmp/zateya-home-ota34-install.log` records release34 installed at18494ms,
new build `Nov 6 2026 22:29:47`, and local self-test confirmation at2405ms.
The separate LittleFS mount
failure remains; no flash cache or settings were erased.

## Physical acceptance

After OTA34 the user reported “вроде вс норм сейчас” following the requested
voice-answer trial. Server turn `faec4fc3-ec90-46cd-8874-0eb341c29ce0`
on2026-11-06 at19:40UTC completed processing and synthesis (2.47s); audio GET
returned200. Live device diagnostics show boot_id1982328223, recording1,
348928 captured /358528 queued and sent bytes, upload202, and no new failure
event. Persisted last_error_code9 remains from earlier failures; it is not a
new event. The timed USB capture ended before this trial, so complete-transfer
and error-free TLS claims are not inferred from that log. Successful audible
behavior is user-confirmed for this trial, not a long-running stability test.

LittleFS recovery remains separate and unperformed. No flash cache/settings
were erased. No further firmware change is needed for this acceptance result.
