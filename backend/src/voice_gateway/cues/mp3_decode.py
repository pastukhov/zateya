"""Bounded strict decode validation; no PCM is persisted or transported."""
import subprocess

from backend.src.voice_gateway.tts.mp3 import MP3Parser

MAX_CUE_BYTES = 160000
MAX_CUE_SECONDS = 6


def validate_mp3(data: bytes) -> dict:
    if not 0 < len(data) <= MAX_CUE_BYTES:
        raise ValueError('Invalid MP3 cue size')
    parser = MP3Parser()
    parser.feed(data)
    parser.finish()
    if (parser.sample_rate, parser.channels) != (44100, 1):
        raise ValueError('Unsupported MP3 cue profile')
    offset = parser.metadata_bytes
    while offset < len(data):
        header = data[offset:offset + 4]
        if header[2] >> 4 != 9:
            raise ValueError('MP3 cues require 128 kbps')
        offset += 144 * 128000 // 44100 + ((header[2] >> 1) & 1)
    duration_ms = parser.samples * 1000 // parser.sample_rate
    if not 0 < duration_ms <= MAX_CUE_SECONDS * 1000:
        raise ValueError('Invalid MP3 cue duration')
    # libmpg123 deliberately conceals malformed Layer III payloads and can
    # report decoded PCM even after invalid Huffman/side-information errors.
    # FFmpeg's strict error mode makes those errors fatal. No decoded audio is
    # saved or sent: this is validation only, with bounded input and deadline.
    try:
        result = subprocess.run(
            ['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'error',
             '-max_alloc', '8388608', '-threads', '1', '-err_detect', 'explode',
             '-xerror', '-f', 'mp3', '-i', 'pipe:0', '-map', '0:a:0',
             '-threads', '1', '-f', 'null', '-'],
            input=data, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Strict MP3 decoder unavailable or timed out') from exc
    if result.returncode or result.stderr:
        raise ValueError('MP3 payload decode failed')
    return {'sample_rate': 44100, 'channels': 1, 'duration_ms': duration_ms}
