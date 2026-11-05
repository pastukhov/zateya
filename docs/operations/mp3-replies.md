# MP3 replies and complete cue generations

Status: compatible backend deployed and signed OTA 28 published on 2026-11-05.
Installation and listening acceptance on the actual recorder remain unconfirmed.

Verification: 859 backend/deployment tests passed, 137 native firmware tests
passed, and the StickS3 target build succeeded. Additional real TCP tests
confirmed prompt cancellation during silent headers and silent audio bodies,
one-shot playback and successful delivery across final-file rename.
A later response after cancellation cannot publish audio; cancellation does
not guarantee that the provider stops generation or billing.

The optional MP3 profile is separate from the existing `TTS_*` profile during
migration. `TTS_*` continues to serve firmware that expects WAV and its legacy
cues. Set `MP3_TTS_MODEL`, `MP3_TTS_VOICE`, `MP3_TTS_INSTRUCTIONS` and
`MP3_TTS_TIMEOUT` in the deployment environment. The MP3 profile inherits the
configured LLM endpoint and API key and always requests `response_format=mp3`.
Never copy credentials into reports or Git.

`MP3_TTS_LANGUAGE_CODE` optionally supplies a two-letter language code, such as
`ru`, for RouterAI `elevenlabs/*` models. It is sent as
`provider.options.elevenlabs.language_code`; the legacy profile has its own
`TTS_LANGUAGE_CODE`, which MP3 never inherits. Codes are stripped and lowercased;
malformed values and nonempty language settings on other provider models fail
configuration. Empty settings keep existing request payloads and cache identities
unchanged. Existing speaking instructions are still sent for compatibility;
RouterAI's ElevenLabs transport ignores that top-level field.

A nonempty language is part of the cue generation and legacy cue cache identity.
Historical generation profiles without this field still resolve with an empty
language, and retained profiles preserve their original language. A replacement
generation becomes active only after all fourteen cues pass validation. Provider
acceptance of `ru` does not establish pronunciation quality: the initial same-voice
Talia samples with `ru` still had the reported accent when the user listened.
Voice selection and deployment therefore remain subject to listening acceptance.

The measured choice is `elevenlabs/eleven-flash-v2.5` with female Talia voice
`OZ0L6eISlOejga3XjDFt`; see [measurements](mp3-tts-benchmark.md). Cues currently
require mono 44.1 kHz, 128 kbps MP3, at most six seconds per cue and 600 KB for
all fourteen. A different model must satisfy this validated profile before
activation. The device decodes and resamples to its existing 24 kHz output.
The server preserves provider MP3 bytes for storage and delivery.

A change to the configured model, voice, instructions, language or cue texts creates a
new generation. The server validates the entire catalog before publishing its
manifest. Strict FFmpeg decoding validates cues without saving decoded audio.
Successful staging files survive retries and restarts. Each generation has at
most five attempts, recorded before paid calls; exhaustion is visible in the
manifest update status and a new configuration starts a new generation. The recorder
validates and stores the complete replacement set in LittleFS, then changes
its active manifest while idle. Requests carry its active generation, so its
answers use the same profile as its locally active cues. Unknown old
generations require a cache update instead of silently choosing another voice.

The transition release retains legacy codecs for rollback. Removing Opus and
legacy WAV delivery is a separate release after real device acceptance.
Microphone recording and historical archives are outside this migration.

## Release checks

Before deployment, run backend tests, native firmware tests, the target build
and the real TCP streaming checks. Preserve the current backend image, deploy
the compatible backend, generate and verify all fourteen cues, then publish a
signed OTA candidate. Set public release directory/file modes before replacing
`stable.json`; verify its signature and firmware hash through external HTTPS.

Verify installed firmware diagnostics separately from OTA publication. On the
actual recorder check short and long replies, all cues, both button modes,
wake word, cancellation, follow-up listening, weak network and offline reboot.
Listen specifically for clicks and end-of-phrase hiss. Measure audible start
latency separately from HTTP first-frame timings. Encoder delay/padding is not
trimmed until the actual decoder behavior is established; host tests cannot
prove speaker quality or device heap/stack margins.

## Release 28 evidence

Implementation commit: `eb57f477cd336cea1a93d1f65cdca4941169ff3e`.
Backend health is healthy; the previous image is retained as
`zateya-voice-gateway:before-mp3-20261105`. Deployment environment backup:
`/opt/zateya/.env.before-mp3-20261105` (private; contains credentials).

Active server generation:
`81042c98c112af01d967432c9ad20c1740a99dd69b5f72f31dd8cf239af2f5fd`.
All 14 MP3 cues were fetched through external authenticated HTTPS, checked
against SHA-256, and strictly decoded: total 246773 bytes. Unauthorized access
was rejected and the legacy Opus cue route remained available.

A controlled delayed producer through external HTTPS delivered the first MP3
prefix in 0.018 seconds, before producer completion; all 14253 fixture bytes
matched exactly. Both streamed and plain replay attempts were rejected. This
is a transport check, not a TTS speed or speaker latency measurement.

OTA image: 1669168 bytes, SHA-256
`871bd0afe08583c87b9d76b0cf00277e811e094faf16ea380c4e2d6004bcf948`.
The published envelope signature and downloaded image hash were independently
verified via external HTTPS; current sequence 28 receives no newer release.
The latest available recorder diagnostic still reports an earlier build, so
publication does not establish installation or physical audio quality.

Additional final regressions passed: 9 streaming/negotiation tests, 2 real TCP
silent-server cancellation tests and the proxy allowlist integration check.
FIR tail flushing and gapless trimming remain disabled pending physical decoder
validation; legacy removal remains gated by that acceptance.
