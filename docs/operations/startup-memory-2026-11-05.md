# Two-minute startup stall: internal memory exhaustion

USB diagnostics on 2026-11-05 identified the installed image as OTA26 by exact
SHA256 (`d81550f456913b781be50730379fdc7bb37b493b6963a88c8658452ea12f6a99`,1606256 bytes), not its compilation timestamp. Active slot was ota_0 at0x20000.
The user explicitly declined a full-flash backup. Only metadata and an in-memory
image hash were read; no copy of the installed image was saved. Settings,
partition table, bootloader, inactive slot and cue storage were not flashed.

## Controlled comparison

Times below use serial-log boot timestamps. Numeric heap sampling uses
esp_timer uptime, which starts approximately1.28 seconds later in these logs.

| Run | Change | First backend HTTP200 |
| --- | --- | --- |
| Original26 | None, first captured boot |136.415s|
| Original26 repeat | None |128.130s|
| DiagnosticA | Numeric heap instrumentation, original OTA worker |137.371s|
| DiagnosticB | Same image except runtime flag suppressing OTA worker creation |5.016s|
| DiagnosticC | OTA worker restored, unused native playback ring omitted on ESP |5.080s|

Wi-Fi obtained DHCP in approximately3 seconds. During the stall the device's
local HTTP endpoint and ping also failed, while laptop requests to the external
server succeeded. `wifi:m f null` and `wifi:mem fail` were observed; clock
synchronization alone does not explain this incident.

In A, sampled DMA-capable free memory reached371 bytes and internal minimum
free memory reached515 bytes before the worker exited. At log123.021s the OTA
worker logged exit with9291 internal/2795 DMA bytes free. The next main sample
showed26035/19539 bytes: **16744 bytes reclaimed**. The old readiness timeout
therefore both freed enough internal memory for connectivity and ended the only
OTA attempt before the server became reachable.

A/B allocated ELF section layouts and every function/object address/size were
identical. Parent independently verified the sole allocated-content difference:
one initialized switch byte2→3. SDK configuration was identical. Both used a
shared diagnostic guard before fetching an OTA manifest after readiness; it
prevented unattended upgrades but retained A's failing120-second wait. These
builds do not exercise OTA download/write resource peaks.

C keeps the original OTA worker and removes only the unused native playback
ring. It reached HTTP200 before the shared guard ended the worker at6.020s.
Internal minimum before exit was32103 bytes, and no Wi-Fi allocation warnings
were observed during the90-second capture. This validates a memory correction
with the worker present, not a production policy of disabling OTA.

## Production correction

`firmware/src/main.c` compiles the legacy loopback playback storage/ring only
for non-ESP targets, including its initialization, reset sites and native test
hook. ESP playback already uses its streaming path. The active32KB recording
ring retains its capacity; the extended correction places its CPU-only data in
PSRAM. Ring control, hardware DMA buffers, task stacks and current OTA retry logic
remain unchanged.
Parent ELF comparison confirms **32792 bytes** removed from internal.bss and
the app structure (32768-byte buffer plus24-byte ring metadata).

Native regression tests preserve the host loopback behavior. Parent independently
ran119/119 tests on the OTA26 diagnostic source and149/149 on current source,
and rebuilt diagnosticA successfully. Independent source reviews found no
blocking issues in either instrumentation or the production guards.

Current-main target passed and reached HTTP200 at4.724s with the persistent OTA worker. However, physical recording failed twice before capturing any audio: the largest internal block was7168 bytes, smaller than the8192-byte voice-turn stack. The user heard the error cue. The32KB-only candidate is rejected for release. The correction is being extended to place the active CPU capture ring in PSRAM with explicit allocation-failure handling; further acceptance and release remain pending.
The existing LittleFS mount failure remains a separate finding. No formatting,
cache deletion or audio-storage repair is included in this change.

## Recording acceptance extension

The actual current-main voice attempt reached recording initialization twice and
failed before any audio was captured. Dynamic task stacks require internal RAM;
the fragmented7168-byte maximum block could not supply the8192-byte voice-turn
stack. The final patch allocates the capture ring explicitly from SPIRAM|8BIT,
with no internal fallback, and reuses that storage for the application lifetime.
A small shared helper is exercised by allocation failure/retry, reinitialization
and data-order/wraparound tests. Manual/wake/follow-up capture is gated on
successful allocation, and pending-OTA application readiness is withheld if it
fails. Existing valid firmware can still expose settings/network for recovery.

The builder and parent independently passed152 native tests. Final source review
found no blocking defects. Parent target builds passed for telemetry and the
diagnostic-free candidate, and production source parity was checked. Renewed
physical recording acceptance is still pending. The earlier32KB-only production candidate
is not eligible for publication.

## Revised candidate on device

The corrected current-main telemetry candidate reached HTTP200 at5.373s; capture
allocation succeeded. Internal minimum remained32759 bytes during startup and
background cue work, with a19456-byte largest block observed. The next physical
recording created its voice task successfully, captured157952 bytes and
queued/sent167552 bytes including the existing preroll; the server accepted202.
Upload high-water was45696 bytes and maximum write duration1357ms.

This attempt then failed on the server with `agent_invalid_response`, after a
bounded repair for `invalid_json_contract`. It is distinct from the earlier
firmware allocation failure. A read-only model probe with the archived transcript
and knowledge context returned schema-valid JSON; the original invalid response
was not archived, so its exact defect is not established. At that point no backend behavior change was made. A fresh physical
response/playback check is pending before publication.

The diagnostic-free candidate31 builds successfully and matches all124 production
source/header files (generated OTA trust header excepted). Parent independently
ran152 native tests, target builds, image validation and source parity checks.
Artifact:1691856 bytes, SHA256
`e7f4a5cc5169ae1f6bcc9858189b8c035f7f3c46bc8184a1377753a98001239a`.
RAM reported by the target build is85948 bytes. The existing signing key was
supplied by the user and its public key matches the recorder; it is not in Git.
No signed publication or over-the-air installation is claimed yet.

## Server diagnosis after the second recording

The second physical recording (job `969b826f-4a4a-4830-877c-dc7b0d67fcf2`)
captured142592 bytes and sent152192 including preroll; accepted202, then the same
server failure. Both archived model inputs match the session input hashes exactly;
committed history has not changed. Multiple read-only replays pass, so neither
a specific model-output defect nor a prompt correction is yet established.

Main commit `067290c` adds bounded safe JSON/schema failure metadata for initial
and repair phases, preserving validation, prompts, repair budget and fallback.
No raw model/user text, arbitrary extra-field names, values or keys enter those
logs. Parent reviewed the changes independently: full local backend/deploy suite
had869 passing tests and13 MP3 failures from missing ffmpeg. All55 tests in the
MP3 generation and modified validator/client files then passed in an isolated
container with server dependencies, network disabled.

The exact patch was applied on top of the diverged server history without reset:
server commit `00b7505ae0f1fb28e86c27a7c4e1d2be47645c59`. Deployed image
`77f0d6423f9f8ccfa083b56e9c29e088c577d82aa062eae79e77678f7f79a309`
is the previous immutable image plus the two changed runtime modules. Its running
image ID and module hashes were checked; container healthy and external readiness
HTTP200. Previous image `81c3005aab0b1fbfab4b2ff3a3b9e6ecdf1b8b55c1d82374d2ffcdd2641e7953`
is retained as `zateya-voice-gateway:diagnostics-base-81c3005`. A temporary full
rebuild raced on the same candidate tag; the image mismatch was detected and
corrected by immutable ID before asking for a user test. No voice jobs arrived
during deployment. Use immutable IDs for future checks.

Firmware fix is committed/pushed as `efee4b6`. Candidate31 is signed locally in
`data/firmware/releases/31`, but stable remains30. The device still runs telemetry31;
final production installation and end-to-end voice acceptance are not confirmed.
Next: one physical recording with safe server diagnostics, resolve the observed
error, then publish signed31 and test actual OTA using the otherwise identical
corrected seq30 test image. Keep USB connected until that acceptance finishes.
