# Persistent recorder cue cache implementation plan

**Goal:** Keep downloaded spoken cues across power loss/reboots, load them without
network at startup, and only download changed audio. User explicitly requested a
minimal filesystem and file persistence. Sol implements; parent reviews/tests and
publishes the verified OTA. Existing server speech generation remains authoritative.

**Architecture:** LittleFS (`joltwallet/littlefs` pinned to 1.23.1) on the otherwise
unallocated tail of the existing 8-MiB OTA layout. Keep existing PSRAM playback
leases: flash is persistent backing storage; no filesystem reads in audio ticks.
Current 14 PCM cues total 1146604 bytes and fit. Persist the current PCM format;
keep an explicit on-disk format version so a later codec migration is possible.

**Evidence:** ota_0 = [0x20000,0x320000), ota_1 = [0x320000,0x620000),
remaining range [0x620000,0x800000) = 0x1e0000 bytes. Installed ESP-IDF's
`esp_partition_register_external(NULL,...)` registers a RAM partition descriptor
on internal flash and rejects overlaps; it does NOT rewrite the flash partition
table. LittleFS supports an explicit esp_partition_t pointer. No bootloader,
partition table, NVS or OTA-slot migration is needed.

## Safety and behaviour

- Check the ACTUAL runtime flash size, expected two OTA slot bounds, alignment,
  and every existing partition for overlap before using the fixed cache range.
  Unknown/factory/different layouts fail closed to RAM+network cache. Never use
  unused bytes INSIDE an OTA slot. Do not edit either CSV partition table.
- Runtime-register only this validated tail as data/littlefs, label voice_cues.
  Mount without format-on-failure. First format is allowed only after proving
  the entire reserved range is erased (all 0xff). Do not erase unknown contents
  or silently reformat a corrupt existing filesystem. Failed mount keeps normal
  RAM/fallback functionality; log a fixed nonsecret reason.
- Load and validate cached files before initial ready/listening playback and
  independently of Wi-Fi/backend availability. Startup mount/load runs while
  the boot activity guard still excludes OTA and before user capture can start.
- Store one bounded versioned record per fixed cue name: format, cue identity,
  byte count, SHA256 and PCM. Reject malformed/truncated/oversized/wrong-cue/
  wrong-format/hash-mismatched files; never trust filesystem lengths for malloc.
- Verified replacement: temporary file, checked writes, flush/fsync/close,
  atomic rename over old file. Old valid record survives interrupted download,
  write/close/rename failure and ENOSPC. Clean only owned temporary files.
- Bound committed cache data to 1536 KiB with room for a <=240000-byte temporary
  replacement plus LittleFS metadata. If a future catalog does not fit, keep
  playback in RAM and preserve previous valid files. Do not turn cache failure
  into user recording failure. Do not repeatedly write unchanged files.
- On boot preload current_sha with the actual cached audio hash. Network manifest
  checks retain current interval; matching hash does not download PCM or write
  flash. Track pending disk persistence separately from RAM publication so a
  temporary busy/space/write failure does not silently mark it persisted.
- Flash mutation must not overlap voice capture, playback or OTA. Extend the
  shared activity gate with an explicit storage owner, with tested acquire/
  release policy. A cache worker must never impersonate the app's voice lease.
  Guard the whole filesystem mutation, recheck idle after acquisition, release
  on every outcome. Active voice and OTA win; pending input must be deferred,
  not turned into ERROR or lost when it races a short cache write. Hold release
  cancels a deferred hold; toggle press remains pending. Existing auto follow-up
  already retains the voice lease and must remain uninterrupted.
- Read-only startup is bounded; background filesystem work never runs inside
  audio callback/tick. No user speech, tokens, Wi-Fi credentials or notes are
  stored in this cache. No embedded speech asset is introduced.

## Sol implementation

- [ ] Add pure layout/record validation and testable persistent store logic in
  `firmware/include/voice_cue_store.h`, `firmware/src/voice_cue_store.c`, and
  ESP adapter `firmware/src/voice_cue_store_esp.c` (adjust focused names if useful).
  Tests cover supported layout, small flash, overlapping/unknown partitions,
  corruption/truncation, bad digest/version/name/size, restart/offline read,
  failed replacement preserving old data, same-hash no-write, and full cache.
- [ ] Add managed LittleFS dependency and explicit CMake requirement; pin lock
  through target build. Keep native tests independent of ESP-only headers.
- [ ] Extend activity gate in `voice_ota_esp.c`/`voice_ota.h` as needed and test
  storage/voice/OTA exclusion, boot lease, manual input races and every release.
  Update `main.c` input handling narrowly; preserve feedback queue priority.
- [ ] Integrate local startup load and deferred persistence in
  `voice_cue_cache_esp.c`, retaining existing server auth/hash checks and leases.
  Cache failures are nonfatal and observable; no unconditional downloads on boot.
- [ ] Document storage layout/format, replacement protocol, limits, fallback and
  how to verify offline reboot on real hardware. No compression implementation
  is required for this cache feature.

## Parent verification and release

- [ ] Independently review flash-range guards, blank-only format, crash/ENOSPC
  handling, persistence retries, audio/OTA exclusion and input race handling.
- [ ] Run full native suite and StickS3 build; exercise restart/offline persistence
  in host tests and real LittleFS emulator if feasible. Run relevant release/
  dependency checks. Do not claim host tests validate physical flash/power cuts.
- [ ] Commit/push scoped changes after checks. Build/sign next OTA using existing
  key in a staging copy; preserve current partition table, bootloader and NVS.
  Publish and verify full external HTTPS image/hash/signature.
- [ ] Check available device evidence. User's USB is a charger, not a data cable;
  no direct serial access currently exists. Report installation and physical
  offline reboot/power-loss tests as separate acceptance requirements.

References: ESP-IDF local components/esp_partition/partition.c and official
https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/storage/partition.html
https://github.com/joltwallet/esp_littlefs (explicit partition pointer, LittleFS)
