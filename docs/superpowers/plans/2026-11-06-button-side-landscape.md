# Button-side landscape implementation plan

> Sol implements the single change; parent independently reviews, tests, commits/pushes and publishes the signed OTA under the existing release authorization.

**Goal:** Place landscape button guidance and indicators next to the physical front button in both horizontal orientations.
**Architecture:** Pass the existing rotation into the render model. Translate the two columns as intact groups for button-left orientation; never reflect glyphs or icons. Keep portrait and setup QR pixels unchanged.
**Tech stack:** Existing C renderer, Unity native tests, production preview tool, ESP-IDF/PlatformIO, signed OTA.
**Spec:** `docs/operations/recorder-handoff-2026-11-06-vector.md`, remaining screen correction, and the user's instruction to work on the screen.

## Constraints and review focus

- Establish button-left enum from the physical panel coordinate transform and hardware placement, documenting evidence rather than guessing the IMU sign.
- Preserve all four rotations, toggle/hold/wake copy, recording timer/warnings, selected network/error/diagnostic/OTA views and QR setup.
- No audio, sensor, storage, signing-key, server configuration or memory-allocation changes.
- Keep current 142px state column and indicator geometry; translate column origins without mirroring content.
- Existing untracked user files are outside this task. Work in the current checkout under repository instructions; no separate worktree is needed for this narrow correction.

## Task 1 — Sol implementation

Files: `firmware/include/screen_renderer.h`, `firmware/src/screen_renderer.c`, `firmware/src/board_sticks3.c`, `firmware/tools/screen-preview.c`, renderer/orientation tests as needed.

- [x] Verify/document physical button side for 90/270 from panel mapping and hardware evidence.
- [x] Add regression coverage that fails on current code: guidance on button side, complete translated state/indicator content, unmirrored text, bounds, both landscape rotations and selected overrides.
- [x] Pass rotation from board and preview into model; minimally translate the layout for button-left orientation. Retain legacy zero-initialized model behavior.
- [x] Run focused native tests and production previews. Report files, test results and unresolved hardware boundary. Do not commit, push, publish or spawn agents.

## Task 2 — Parent verification and release

- [x] Independently inspect diff and production previews for both sides, ready toggle/hold/wake, timer, error/OTA and setup.
- [x] Run full native suite and target release build; compare portrait and QR frames to pre-change baseline and verify all physical inverse transforms.
- [x] Commit/push only task files. Check current stable sequence and existing signing key; build/freeze and publish the next signed release using existing procedure. Preserve device NVS/cue cache and server runtime.
- [x] Verify external signature/image/hash and no-update behavior. Confirm installation only if fresh device diagnostics/logs prove it; obtain physical layout feedback after delivery.
- [x] Update handoff/operations with evidence and remaining physical-verification boundary; commit/push documentation.

## Verification before release

Parent independently passed160 native cases and32 preview inverse transforms.
All64 baseline frames compared:50 identical; only14 non-setup270-degree frames
changed. Clean StickS3 OTA33 target build passed;222 tracked snapshot files
matched reviewed sources, with only release trust/config/partition substitutions.
Rollback, PSRAM and two SNTP slots verified. Astra final source/preview review
found no actionable issues. Physical button-side acceptance remains pending.

Panel evidence: MADCTL=0 and native portrait front button beyond y239;
90 maps that edge to logical x239,270 to x0. Official hardware image:
https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1207/IMU-StickS3.jpg

Release33 published and externally verified; new build boot observed in device
diagnostics (boot127471008, backend6118ms). Physical layout feedback remains
pending; no USB/self-test log available. See operations/screen-orientation.md.
