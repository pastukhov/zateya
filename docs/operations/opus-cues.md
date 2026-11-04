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


## Production rollout — OTA26

Implementation commit `061f3432e92ccf9d309c0af76602525965337e9b` was pushed.
Backend deployed as server cherry-pick5821c54 with libopus0 and authenticated
nginx `.vop` allowlist. Rollback image:
`zateya-voice-gateway:before-opus-20261104`.

External HTTPS checks covered all14 PCM and Opus manifests/bodies, unauthorized401,
SHA256, lengths, metadata and real decoded sample counts. Production total:
1146604 PCM bytes →77337 VCOPUS1 bytes (14.83x). The3-byte difference from host
fixtures reflects the different libopus build, which is included in cache identity.
Reloading a fresh cache instance from production disk with a provider that rejects
TTS calls succeeded for all14, with no file modification timestamps changing.

Signed OTA26:1606256 bytes; SHA256
`d81550f456913b781be50730379fdc7bb37b493b6963a88c8658452ea12f6a99`.
External HTTPS verified ECDSA signature, committed revision, complete image size
and hash; current_seq26 returns204 and missing authorization401. Staging build
confirmed main stack24576. Bootloader, partition table and NVS were not flashed.

Publication is verified; installation, Opus playback quality/latency, decoder
stack/heap high-water marks and offline reboot on the physical recorder are not.
The recorder is powered from a charger, without serial access. Reboot on USB power
with Wi-Fi available to discover OTA, allow cues to download while idle, then
check spoken states and a subsequent offline power cycle. Old PCM records remain
for rollback; they are not deleted by this release.
