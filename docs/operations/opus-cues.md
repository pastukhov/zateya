# Compressed local spoken cues

The fourteen fixed server cues use Opus at 24 kHz mono, 24 kbit/s VBR,
20 ms frames. The backend encodes its existing verified PCM cache using libopus;
this does not call TTS again. Legacy PCM manifests and `.pcm` audio remain
unchanged. New clients explicitly request `?codec=opus-v1` and download the
SHA256-addressed `.vop` response. Encoding failure preserves PCM and retries later.

## Wire format

`vcopus1` is a bounded raw-packet container, not Ogg. Its 32-byte little-endian
header has fields: magic `VCOPUS1\0` (8 bytes), version=1 (u16), channels=1
(u16), sample_rate=24000 (u32), original_samples (u32), preskip (u16),
frame_samples=480 (u16), packet_count (u16), reserved=0 (u16), bitrate=24000
(u32). Each packet follows as u16 byte length then raw Opus bytes. There is no
trailing data. The container is at most 65536 bytes, each packet 2..1275 bytes,
original_samples 1..120000, preskip 0..960 and packet_count 1..252, exactly
ceil((original_samples+preskip)/480). Every packet must decode to 480 samples.
Preskip is queried from the encoder in 24 kHz sample units; zero padding covers
encoder delay and final frame rounding. Playback discards preskip and emits
exactly original_samples. Manifest metadata must match the parsed body.

## Device storage and playback

LittleFS stores compressed records separately as `.vopus` (`VCUEOPU1`, version2).
The existing `.vcue` PCM records remain intact for rollback. The shared capacity
budget counts both formats. Boot prefers a verified, decodable compressed record,
then tries legacy PCM. Each RAM slot retains encoded bytes with a reader lease;
playback opens one decoder and retains only one 960-byte decoded frame. Partial
and zero speaker writes preserve queued samples; completion waits for DMA drain.
Decoder failure or cancellation closes the decoder and returns the lease.
Decoder allocation failure uses the existing short PCM fallback tone.

Downloaded data must pass SHA, bounds, duration metadata and actual decoder
validation before replacing a playable slot. Validation holds the shared storage
activity gate, yields each frame, and abandons work when deferred manual/wake
input makes the cache non-idle. Flash persistence retains its independent pending
flag and retry backoff. Storage writes, dictation/playback and OTA remain mutually
exclusive; background wake monitoring is still subject to flash latency.

Direct Espressif Opus decoder APIs from pinned esp_audio_codec2.3.0 are used;
other codec registries are disabled. Main and cache worker stacks are24KiB;
actual hardware stack high-water marks remain to be measured.

## Verification boundary

Fourteen real cached cues total 1146604 PCM bytes and 77334 container bytes
(14.83 times smaller). Real libopus host decode preserved exact sample counts
and measured correlation lag0. Production C parsing passed217334 sanitizer cases;
production playback matched trimmed reference PCM for all14 cues with partial/
zero writes, delayed drain and280 cancellation cases. These are host checks,
not evidence of physical speaker quality or installed firmware. Audible quality,
latency, memory high-water marks and offline reboot on the recorder still need
physical acceptance. User recordings and dynamic answers retain their existing
formats.

Parent validation:608 backend/deploy tests and119 native cases passed. StickS3
build succeeded with1597889 reported flash bytes and143204 static RAM bytes.
Generated sdkconfig.h confirms CONFIG_ESP_MAIN_TASK_STACK_SIZE=24576. Link map
contains Opus decoder components and no MP3/AAC/FLAC/AMR/ALAC or encoder objects.
Host library validation does not execute Espressif's precompiled decoder.
