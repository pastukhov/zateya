# Playback tail noise investigation and fix

User confirms silence is quiet; clicks/noise occur within and at end of spoken phrases, and short hiss almost always follows dynamic answers. This affects the shared speaker path, not only Opus cues. Prior source/host checks did not validate physical I2S drainage.

- [x] Sol inspect actual pinned ESP-IDF/esp_codec_dev DMA and ES8311 start/stop, reproduce a concrete failure in a host test of the relevant control logic before changing behavior.
- [x] Focus on audio_sticks3.c wall-clock s_play_until_us: its estimate ignores DMA startup/reconfiguration and cannot prove which samples reached DAC. Inspect TX clearing, partial writes, mono slot size, hardware drain observability and codec/amp mute ordering. Do not call the cause confirmed from a timing approximation alone.
- [x] Implement smallest evidence-backed correction shared by dynamic responses and fixed cues. Preserve full tail and150ms microphone settling, cancellation responsiveness, codec format, volume, flash/storage/OTA gates. Avoid changing compression bitrate or adding arbitrary sleeps as a substitute for drainage.
- [x] Add bounded nonsecret playback diagnostic evidence if physical root cause cannot be settled offline: actual completion/underruns/write delays, with bounded report/logging; no audio or credentials.
- [ ] Parent independently reviews/tests native and target; separate reviewer checks DMA/ISR lifetime and mute/error handling. Do not claim physical noise eliminated until device check.
- [ ] Commit/push scoped changes after checks; if justified fix exists publish next signed OTA27 and verify signature/image. Keep server protocol compatible and don't deploy unrelated changes.

Unrelated attachments, get_ya_id.py and PNG stay untouched. User device powered from charger; direct serial is not currently available. User authorized action repeatedly; no further design approval needed. Prior timing harness showed normal20ms/tick steady state sufficient, so do not assume starvation solely from frame size.

Implementation and verification boundary: [playback-tail-noise operations](../../operations/playback-tail-noise.md). Focused production-helper native tests:3 passed. No physical noise-elimination claim.

## Confirmed cause: PCM request returned a WAV container

Actual archived answer f198a63f-46b2-4cde-a583-6db4a59eebdb/reply.wav contains a second RIFF at byte44. Its inner data is213120 bytes; outer PCM is220828 bytes including WAV headers and trailing C2PA metadata. Last200ms of bad PCM is-7dBFS; corrected inner PCM preserves speech and removes metadata.13of14 cached cue PCM files have the same nested container, except listening.

Superseding noise-fix scope:
- [ ] Detect and validate actual RIFF/WAVE response before wrapping requested raw PCM; normalize only declared audio data, never heuristic speech trimming.
- [ ] Repair verified existing cue PCM cache by extracting valid embedded WAV data, atomically updating PCM/hash without TTS. Opus identity already includes source SHA and will regenerate.
- [ ] Tests: mislabeledWAV underPCMrequest, trailingmetadata, rawPCMunchanged, malformedcontainer rejects, existingcuecachemigration/noTTS, all14productioncuehashes and real audio tail.
- [ ] Deploy compatible backend only; device updates changed cues whileidle. No OTA27 is needed for this root cause. Keep DMA work separate and uncommitted until independently justified/compiled/reviewed.
