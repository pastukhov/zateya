# Recover StickS3 peripheral power after an initial PMIC timeout

**Goal:** Restore screen/button/audio operation when the first M5PM1 transaction fails.

**Evidence:** Home device7ce8b1e4b780 is alive on Wi-Fi/USB but screen is black. Controlled reset log `/tmp/zateya-black-screen-restart.log`: M5PM1 setup timeout at1833ms, LCD marked ready despite failure, repeated ES8311 I2C failures. Earlier OTA34 fixes AES memory only. M5Unified `src/utility/power/M5PM1_Class.inl` explicitly retries the first device-ID transfer because the first access after idle can be NACKed; local file `/tmp/zateya-M5PM1_Class.inl`.

**Scope:** Preserve register masks/values, TLS fix, settings, flash layout and cue-store contents. Do not erase data. Sol implements; parent independently reviews/tests/builds and publishes next signed OTA after passing checks.

- [x] Add a bounded PMIC wake/probe and retry of the existing setup sequence, with a small delay between attempts. Preserve unrelated register bits and do not report ready on partial setup.
- [x] Make initialization failure recoverable: return success/failure from power/LCD setup; only initialize/flush LCD after power succeeds. Ensure display cached-state shortcut cannot prevent later retries. Rate-limit retry after exhaustion and avoid duplicate SPI/LEDC initialization.
- [x] Gate audio readiness and OTA self-test on successful peripheral setup as appropriate to existing call order; don't repeatedly toggle speaker power after successful setup.
- [x] Add native regression tests using a small injectable setup helper if necessary: first transfer failure then success, persistent failure, failure mid-sequence and successful retry, unrelated bits preserved. Keep board glue minimal.
- [x] Parent independently runs native tests and target build, reviews diff; commit/push task changes.
- [x] Build next signed OTA from clean committed source; verify configuration/signature/hash and externally served image, publish readable stable pointer atomically. Confirm actual installation/self-test and USB logs show rails enabled/audio initialized.
- [ ] User checks visible screen and front button, then one voice trial; record physical result separately from compilation and OTA publication. If power remains unavailable, do not falsely mark image self-test successful.

## Primary reference and observed limits

M5Unified PMIC startup reference:
https://github.com/m5stack/M5Unified/blob/96576a14247ddc935149145aa6b51943464120f1/src/utility/power/M5PM1_Class.inl
The driver's begin() performs up to three device-ID reads before disabling I2C
idle sleep; its comment describes the first idle transfer being NACKed.
The local failure is ESP_ERR_TIMEOUT, so the reference supports bounded wake
retries but does not prove the underlying electrical reason for this timeout.
Post-reset battery reads work, while ES8311 repeatedly fails I2C initialization.
No USB disconnect, firmware replacement or erased settings preceded the
controlled restart during this investigation.

## Release and runtime evidence

Implementation `589ed12` pushed. Parent reviewed masks, readiness gating and
retry scheduling; corrected sub-tick delay to at least one FreeRTOS tick.
Independent native tests163/163 and target build pass. Clean committed228-file
snapshot built signed OTA35,1698048 bytes, SHA256
`49bce43a7cf1dd844cd5d4d07099a0bcb61e404dac2bfa652bd1c0f3c0d0a741`.
Software AES from OTA34, external TLS allocation, certificate bundle, rollback
and two SNTP slots remain enabled. External HTTPS envelope signature/full-image
hash and current35 no-update204 verified; stable pointer is readable by backend.

USB `/tmp/zateya-pmic-ota35-install.log` contains old34 PMIC timeout at1843ms,
then release35 installation at29403ms and reboot. New35 reports M5PM1 rails
enabled1645ms, backlight60% at2025ms, ES8311 ready2375ms, local image confirmed
2505ms. Device boot_id2598667485; new build Nov6 23:06:00 (diagnostic timestamp
23:05:59). No repeated ES8311 initialization failure in this new boot.
Physical screen/button/voice acceptance requested and still pending.
No configuration, NVS, partition table or cue-store data was erased.
