# Complete cue generation transaction checks

`pio test -d firmware -e native -f test_cue_generation` checks all 14 staging
steps, unchanged active pointer before complete commit, atomic pointer replacement,
SHA failure, candidate temporary-file space reservation and cleanup ownership.

For full JSON parsing and offline preload, compile the same test with
`-DVOICE_CUE_HOST_JSON` and ESP-IDF's `components/json/cJSON/cJSON.c` / include
folder. Link `voice_cue_generation.c`, `voice_cue_store.c`, `voice_cue_cache.c`,
`voice_cue_opus.c`, `voice_mp3_player.c`, Unity and `-lm`. The test supplies the
MP3 decoder seam itself; do not link `voice_mp3_player_esp.c` in this variant.
This additionally verifies all-or-nothing preload and rejects a corrupt cue.

POSIX fsync/rename tests establish the transaction structure. LittleFS power-cut
behavior, storage headroom with the existing device cache and decoder output
remain hardware checks. A failed/incomplete candidate cannot replace the durable
active manifest, and the worker retries in idle after one minute.
