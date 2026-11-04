# Early WAV reply playback

Dynamic answers remain WAV/PCM. Fixed Opus cues are unchanged. Updated firmware
can receive validated TTS audio while the provider response is still arriving;
old firmware retains the existing ready-only download path.

## Provider and archive

Recorder synthesis uses httpx streaming. A finite RIFF with a supported PCM fmt
(mono 16-bit 24 kHz) and finite nonempty even data length can be published early.
The incremental parser stages small headers and at most one odd sample byte,
writes a canonical 44-byte finite WAV header, and appends only data samples.
Leading/trailing metadata is skipped by chunk length and word padding. Duplicate,
truncated or out-of-bounds chunks fail, including failures after all audio samples
but before metadata/provider EOF. No ASCII metadata guessing is used.

The growing `reply.wav.part` is flushed before `reply-stream.json` advertises its
expected canonical length. The pipeline validates the complete result and
atomically renames it to `reply.wav`; only then can the worker mark the job ready.
Cancellation sets a producer stop event and invalidates availability. A blocked
provider read remains bounded by its existing HTTP timeout; terminal database
status prevents late thread writes from reviving a stream. Restart marks active
jobs interrupted, so stale partial archive files are never eligible for delivery.

Raw PCM, unknown-length RIFF/data and otherwise unsupported early formats retain
complete normalization before availability. Upstream response size is capped at
16 MiB. A 64 KiB spooled temporary buffer spills to disk; complete fallback parsing
can read at most the 16 MiB cap into memory. Early delivery never requires the whole
PCM response in RAM. The existing single synthesis worker bounds concurrency.

## Delivery and completion

Status adds optional root booleans `audio_stream_ready` and
`audio_stream_consumed`, keeping the existing status vocabulary and768-byte
firmware JSON bound. Availability is separate from terminal ready.

New firmware opts in with `GET /api/voice/turns/{id}/audio?stream=1`. Authentication
and device ownership apply before file access. The backend tails the growing
canonical file in 4 KiB blocks, with a 180-second deadline and periodic terminal
status checks. It retains an open descriptor across rename. It closes the HTTP
stream successfully only after the job is ready and the exact canonical byte
count has been delivered. Failure/cancellation aborts the HTTP response instead
of pretending that EOF was successful. The proxy disables response buffering;
responses are private/no-store and carry X-Accel-Buffering:no.

A durable SQLite claim is recorded before sending any bytes. Only one opt-in
request can claim a turn, including complete-file fallback. Disconnecting before
receiving audio can therefore forfeit that playback; this conservative choice
prevents automatic prefix replay after a lost connection or device reboot. Old
clients using plain `/audio` still receive the complete ready WAV as before.

The firmware retains its existing 8192-byte PCM stream buffer and WAV parser.
After download it requires both complete HTTP framing and complete WAV data.
An early download then waits for a fresh terminal status: it never downloads a
second time. A consumed turn seen after reboot fails closed. Final follow-up
metadata is taken only from ready, and automatic listening still waits for all
PCM, speaker drainage and worker completion. A synthesis/transport error after
partial speech stops playback without retrying its prefix. Cancellation remains
available during download and final-status polling. The HTTP loop also enforces
the existing turn deadline.

## Verification and limits

Focused TTS tests cover fragmented headers, odd sample splits, metadata exclusion,
raw/unknown fallback, size bounds, cancellation and failures after partial or full
PCM. Native client tests cover root-only strict booleans, final confirmation,
follow-up, no second download and consumed-turn reboot protection. Actual TCP
integration with a deliberately delayed provider proves first PCM arrives before
provider EOF, and tests ownership, legacy behaviour, failure, cancellation and a
claim surviving store reopen. Parent verification runs the full suites, target
build and proxy checks separately.

A live provider baseline returned headers at 3.228 s, first bytes at 3.229 s and all
643228 bytes at 3.292 s: only 63 ms of possible overlap in that request. The new path
removes the server's full-file barrier; it cannot reduce upstream initial latency
or guarantee that the provider streams progressively. The existing one-second
status poll may miss a short availability window and simply use the completed
file. Device installation and audible playback/cancellation still require
physical acceptance after release.

Parent verification before release: 634 backend/deployment tests passed, then
8 focused streaming TTS tests passed after the final filesystem-error handling
change. Native firmware: 123 tests passed. StickS3 target build succeeded.
Independent review found and verified the cancellation fix (including connection
setup failures) and inner-loop deadline guard. Actual archived noisy WAV was
split at nine chunk sizes, including individual bytes: extracted PCM was exact.

## Production rollout

Backend `d691c4e` deployed on 2026-11-04 with rollback image
`zateya-voice-gateway:before-streaming-20261104`. External HTTPS test delivered
first PCM in 0.132 seconds while a synthetic producer was still blocked; exact
24000 samples, legacy download and replay rejection passed. Probe data was
removed. A real provider call advertised audio at 1.456 seconds and completed at
1.478 seconds, with a valid canonical 24 kHz WAV.

OTA 27: 1607280 bytes, SHA-256
`58904f74ce3f968ab8b1da85ce758b98659777f8a7b07c63f8bd17ea14372d50`.
Signed candidate and copied image were verified. Public release files require
read permissions for the backend UID; these were applied before final external
manifest/signature/image verification. Physical installation and audible
acceptance remain unconfirmed.

Exploratory TTS comparison used identical Russian text, one request per model:
Gemini 3.8 Flash Lite TTS first bytes 2.137 seconds, Grok Voice TTS 1.0 first bytes
1.791 seconds. These are single observations, not a reliable latency ranking or
a voice-quality evaluation. Production model and dynamic audio format unchanged.
