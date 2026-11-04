# MP3 TTS selection, 2026-11-04

Live sequential requests were made from the production backend host through the
configured RouterAI endpoint, without changing the production profile. Five
identical Russian inputs per candidate covered a short cue, travel names, date
and amount, a clarification, and a longer answer. Measurements start before the
HTTP request and end at the first complete MPEG Layer III frame. They are not
speaker latency, quality ratings, p95 estimates or a universal speed ranking.

| Model | Voice | Median first frame | Maximum | Successful |
| --- | --- | ---: | ---: | ---: |
| x-ai/grok-voice-tts-1.0 | eve | 2.214 s | 2.649 s | 5/5 |
| elevenlabs/eleven-flash-v2.5 | George/Eldrin ID JBFqnCBsd6RMkjVDRZzb | 0.431 s | 0.734 s | 5/5 |
| microsoft/mai-voice-2.1-flash | en-US-Harper:MAI-Voice-2 | 1.526 s | 1.924 s | 5/5 |

User explicitly requested retaining a female voice. Selected candidate:
`elevenlabs/eleven-flash-v2.5`, female Talia voice `OZ0L6eISlOejga3XjDFt`.
Five additional identical inputs succeeded: first-frame times 0.701, 0.442,
0.472, 0.875, 0.612 seconds; median 0.612 seconds, maximum 0.875 seconds.
All return `audio/mpeg`, mono 44.1 kHz, 128 kbps MPEG Layer III, with a leading
44-byte ID3 region. Grok returns mono 24 kHz/128 kbps; MAI mono 24 kHz/160 kbps.
The selected profile therefore requires verified device-side resampling to the
existing 24 kHz PCM output; there is no server audio transcoding in production.

All 20 files (15 initial and 5 selected female voice samples) decode through
ffmpeg without errors. The incremental
backend parser preserves their bytes exactly when fed 511-byte chunks. Real
Espressif decoder behavior, resampler quality, heap/stack and physical listening
remain separate release checks. Temporary ffmpeg conversions used for analysis
are not part of the delivery architecture.

Two selected female samples were decoded locally and sent to the existing STT
for a language/content sanity check. Date and amount returned correctly as
12 January 2027 and 125000 rubles. The longer sample was recognized in Russian
and preserved the message; recognition produced spelling variants for Yunnan
and Raja Ampat. This cannot establish whether variation comes from synthesis or
recognition, and does not replace listening acceptance.

Per-request timing, size, profile and SHA-256 are in
[the measurement record](benchmarks/2026-11-04-mp3-tts.json). Inputs are neutral
synthetic test text. No credentials or personal note contents are included.
Provider voice reference:
https://elevenlabs.io/docs/help-center/product/voices/my-voices/what-are-default-voices
