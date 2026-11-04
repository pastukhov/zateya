# LittleFS replacement power-cut check

This host harness exercises the pinned LittleFS source with the recorder cache
geometry (0x1e0000 bytes, 4096-byte erase blocks), 14 representative PCM cue sizes,
and a maximum-size replacement. Each flash program/erase is interrupted halfway
in turn; remount must retain either the complete old or the complete new file.
It is an independent check of the temporary-file/sync/close/rename pattern, not
an ESP VFS adapter test or a physical flash/power-loss validation.

Resolve the pinned managed component first:

```sh
pio run -d firmware -e sticks3 -t compiledb
```

From repository root, compile and run (exit zero means every assertion passed):

```sh
cc -O2 -DLFS_NO_DEBUG -DLFS_NO_WARN -DLFS_NO_ERROR \
  -Ifirmware/managed_components/joltwallet__littlefs/src/littlefs \
  firmware/test_support/littlefs_powercut.c \
  firmware/managed_components/joltwallet__littlefs/src/littlefs/lfs.c \
  firmware/managed_components/joltwallet__littlefs/src/littlefs/lfs_util.c \
  -o /tmp/zateya-littlefs-powercut
/tmp/zateya-littlefs-powercut
```

The harness never accesses a hardware device or filesystem partition; its flash
image and simulated reboot state exist only in process memory.


# Opus parser and real-decoder player checks

`opus_parser_fuzz.c` exercises every truncation and 10000 deterministic mutations
per supplied VCOPUS1 file. `opus_player_check.c` links the production C player
with host libopus: output must match direct decoding with pre-skip/final trimming,
including zero/partial output writes, delayed drain, and cancellation cleanup.
These check the production parser/player, not the precompiled ESP decoder or I2S.

Generate `.vop` fixtures from PCM using
`backend.src.voice_gateway.cues.opus.encode_pcm`, then run from repository root:

```sh
cc -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
  -Ifirmware/include firmware/test_support/opus_parser_fuzz.c \
  firmware/src/voice_cue_opus.c -o /tmp/opus-parser-fuzz
/tmp/opus-parser-fuzz /path/to/fixtures/*.vop
cc -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
  -Ifirmware/include firmware/test_support/opus_player_check.c \
  firmware/src/voice_cue_opus.c firmware/src/voice_listening_cue.c \
  -Wl,-l:libopus.so.0 -o /tmp/opus-player-check
/tmp/opus-player-check /path/to/fixtures/*.vop
```

The host needs libopus0 and GCC sanitizers. LeakSanitizer requires a host without
ptrace sandboxing. No hardware or network is accessed by either executable.
