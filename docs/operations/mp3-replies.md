# MP3 replies and complete cue generations

Status: implementation and independent host verification complete; production
has not yet switched.

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

The measured choice is `elevenlabs/eleven-flash-v2.5` with female Talia voice
`OZ0L6eISlOejga3XjDFt`; see [measurements](mp3-tts-benchmark.md). Cues currently
require mono 44.1 kHz, 128 kbps MP3, at most six seconds per cue and 600 KB for
all fourteen. A different model must satisfy this validated profile before
activation. The device decodes and resamples to its existing 24 kHz output.
The server preserves provider MP3 bytes for storage and delivery.

A change to the configured model, voice, instructions or cue texts creates a
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
