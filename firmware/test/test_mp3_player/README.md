# MP3 player host checks

`pio test -d firmware -e native -f test_mp3_player` exercises the production
incremental parser/resampler with a deterministic decoder seam. It checks every
input chunk size, identical PCM across chunk boundaries, 44.1→24 kHz sample count,
1 kHz passband / 20 kHz alias suppression, partial writes, EOF corruption, ID3
bounds/versions, zero-PCM decoder output, OOM and cancellation cleanup.

The decoder instance survives every frame; these host tests do not execute the
Xtensa Espressif decoder. Actual MP3 decode performance, button responsiveness,
heap/stack headroom, speaker quality and underruns require the StickS3.

Xing/LAME delay and padding are parsed but deliberately not subtracted until the
Espressif decoder's synthesis delay and metadata-frame behavior are measured.
There is no silence detection or guessed 529-sample trim. The 32-tap anti-alias
FIR currently retains its short delayed tail rather than appending synthetic
PCM beyond the MP3 EOF. Gapless edge behavior remains a physical release gate.
