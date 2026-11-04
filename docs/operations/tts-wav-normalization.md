# TTS container normalization and playback noise

On4November2026 the user reported short noise/hiss after dynamic spoken answers,
and clicks within or near the end of phrases. The archived answer for turn
`f198a63f-46b2-4cde-a583-6db4a59eebdb` contains a second RIFF header at byte44.
Its outer PCM payload is220828bytes, but the inner WAV's actual audio data is
213120bytes at24kHz mono16-bit (4.44seconds). The excess7708bytes include the
inner WAV header and trailing C2PA provenance metadata. Played as PCM, metadata
produces a loud noise tail. The last200ms of the extracted audio is near silence;
the archived contaminated tail is loud. This is direct source-file evidence,
independent of DMA scheduling hypotheses.

The compatible TTS provider returned a complete WAV despite the request for
`response_format=pcm`. The client trusted the requested format and wrapped the
whole response as raw PCM. An octet-stream/audio-PCM content type did not prevent
this format mismatch.

The backend now checks RIFF containers before raw wrapping. It validates PCM16
mono at supported rates, parses bounded RIFF chunk lengths and word padding,
and writes a canonical WAV containing only the declared audio data. LIST, iXML,
C2PA and other non-audio chunks are excluded by structure, without searching for
ASCII markers inside samples. Truncated containers/chunks, duplicate data/format
chunks and incomplete PCM frames fail before publication. Ordinary raw PCM is
unchanged. Unknown RIFF length is supported; an unknown-length final data chunk
extends to EOF, because its boundary cannot safely be inferred from sample bytes.

Existing cue cache entries are SHA-verified first. If the nominal PCM is itself
a complete finite valid24kHz mono PCM16 RIFF, the backend extracts its audio and
atomically replaces the PCM and metadata files. Write-ahead metadata accepts
exactly the old/new SHA during an interrupted two-file repair, so restart finishes
repair without resynthesis. Non-container PCM is unchanged. Text/config identity
is retained; the content SHA changes. The Opus identity includes source PCM SHA,
so it is re-encoded from repaired PCM automatically. Existing device caches will
receive the new SHA during their normal refresh; offline devices keep their old
cached audio until a successful refresh.

Tests reproduce the provider format mismatch under octet-stream, audio/pcm and
audio/wav types; trailing/leading metadata with odd padding; unknown streaming
lengths; malformed rejection; and cue repair, interruption recovery and unchanged
raw PCM. The actual incident's inner container extracts to exactly213120bytes.
Physical listening after deployment remains required to confirm all reported
noise symptoms are resolved. The separate DMA investigation is deferred and is
not part of this backend correction or a new firmware release.
