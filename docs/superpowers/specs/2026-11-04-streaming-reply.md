# Early WAV reply playback

The recorder should receive speech as soon as the TTS provider supplies usable
PCM, without waiting for the complete provider response. Keep WAV/PCM; dynamic
Opus is explicitly out of scope. Preserve fixed Opus cues and the recent fix
that excludes WAV headers and trailing metadata from audible samples.

Use incremental validated extraction for finite PCM16 mono 24 kHz WAV data.
The provider currently returns this container even with response_format=pcm.
Publish a canonical WAV header with its declared data length and only audio
bytes as they arrive. Continue structural validation through provider EOF.
Unsupported early-stream cases (raw PCM or unknown data length) retain the
existing complete-file path; never invent a length or scan audio for markers.

Keep job ready meaning fully successful, validated and archived. Advertise
stream availability separately; old clients keep waiting for ready. Updated
firmware consumes the early stream, then obtains final job status/follow-up
without replaying audio. Failure/cancellation after partial playback stops it
and cannot automatically repeat the spoken prefix. Unauthorized clients and
other devices cannot access partial audio. Bounded buffers, explicit timeouts,
restart cleanup and proxy buffering disabled are required.

A live baseline on 2026-11-04 received first provider bytes at 3.229 seconds and
all 643228 bytes at 3.292 seconds. This request offers only 63 ms of overlap;
implementation cannot reduce the provider's initial latency. Measure early
client bytes against deliberately delayed upstream completion and report actual
provider measurements separately from physical-device observations.
