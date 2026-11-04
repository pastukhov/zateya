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
