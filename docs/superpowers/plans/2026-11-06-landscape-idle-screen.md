# Landscape idle screen correction implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Sol implements; parent reviews, verifies, commits/pushes and releases per AGENTS.md. Existing authorization persists.

**Goal:** Restore the missing ready-state icon and remove ambiguous/redundant button instructions from landscape, matching the user's device photo.
**Architecture:** Narrow renderer/layout correction on the existing four-orientation/two-column design. No sensor, audio, button behavior or configuration changes.
**Tech Stack:** C framebuffer renderer, native Unity/PlatformIO tests, production preview tool, signed StickS3 OTA.
**Spec:** User's screenshot/report and existing 2026-11-05-screen-orientation-design.md. Parent's concrete UI choice below has been stated to user; retain prior two-column agreement.

## Evidence and design

`screen_renderer.c` sets long_hint when there is a newline OR UTF-8 byte length exceeds24; then it hides the icon. Normal ready hint «НАЖМИТЕ ДЛЯ\nСТАРТА» always matches. Right column displays bare «НАЖАТИЕ» without describing the action. User reports both problems.

For normal ready landscape (state IDLE with selected ready view, not overridden by network/OTA/diagnostics/wake-listening): show the existing large icon centered in left column and «ГОТОВА» below; omit redundant left hint. Right column retains server/Wi-Fi/power and ID, but uses explicit two/three-line action copy: toggle «КНОПКА:\nСТАРТ / СТОП», hold «ДЕРЖИТЕ\nКНОПКУ». If wake enabled, keep its actual invocation visible as «СКАЖИТЕ\nЗАТЕЯ» plus concise button alternative in left available space or right column, with no overlap. Settle geometry in production previews. Do not show ready action over OTA/error/network views. For non-ready states preserve existing selected title/hint and timer; right mode label should be explicitly a mode (e.g. «КНОПКА:\nНАЖАТИЕ» / «КНОПКА:\nУДЕРЖАНИЕ») rather than a false instruction while busy.

Portrait and QR behavior must remain unchanged. No global redesign, no new per-frame framebuffer allocation. Ready detection must not override synthetic views just because state remains IDLE: board chooses overrides before rendering. No strlen threshold change for other states in this narrow fix.

## Review focus

- Normal toggle/hold/wake-ready landscape icon always visible, meaningful mode copy and no duplicated vague prompt.
- Board overrides (OTA, pending self-test, diagnostic upload, network, wake listening) remain visible as selected.
- Timer and long errors still fit; QR quiet zone and four orientation transforms preserved.
- No new stack/internal-memory pressure or audio changes; restored startup-memory fix remains in release.
- Tests must demonstrate previous missing icon and visually verify actual production rendering, not just function return value.

## Task 1 — Sol implementation

- [ ] Add failing renderer regression for landscape ready: icon-colored pixels in its region for toggle/hold/wake and meaningful copy via rendering/helper as appropriate; ensure overrides not replaced. Keep portrait frame compatibility where possible.
- [ ] Implement minimal renderer adjustment and explicit landscape ready mode copy. Preserve all actual button/wake semantics.
- [ ] Extend production preview scenes to show real toggle default (photo scenario), hold and wake ready plus existing recording/error/setup/OTA. Current preview wrongly tests only wake-ready with generic view hint, unlike board. Match actual board inputs in fixtures. Keep preview geometry/font readability and no overlap.
- [ ] Run focused screen tests/preview smoke. Report changed files and checks; no commit/publish from implementer.

## Task 2 — Parent verification and release

- [ ] Review diff, inspect production PNG previews at native/expanded sizes; four rotations and toggle/hold/wake/overrides, scan all QR previews if tooling available.
- [ ] Run full native suite and clean isolated StickS3 release32 build; validate signing public key and no private files in Git.
- [ ] Commit/push task files, freeze signed release32 artifacts with source SHA. Publish authenticated OTA using existing signing key and updater; do not flash USB or erase storage. Preserve approved Marina/Multilingual v2 cue generation667fadd41d6b…728cf and server configuration. User's playback interference diagnosis remains open awaiting audio.
- [ ] Observe actual OTA install/boot confirmation, backend connection and persistent cues. Distinguish published from installed. Request physical layout feedback after concrete preview/update, without re-requesting authorization.
- [ ] Update operations/handoff with checks and hardware acceptance boundary; commit/push docs.
