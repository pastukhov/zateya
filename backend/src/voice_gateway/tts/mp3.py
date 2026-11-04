"""Bounded structural MPEG Layer III parser; compressed bytes are never recoded.

Only complete frames are returned. This validates framing and the transport
profile, not the psychoacoustic payload: target decoder tests remain necessary.
ID3v2 is accepted only at the beginning, with a 64 KiB metadata budget.
"""
from backend.src.voice_gateway.tts.base import TTSProviderError

MAX_METADATA_BYTES = 65536
MAX_MP3_BYTES = 16 * 1024 * 1024


class MP3Parser:
    def __init__(self):
        self.buffer = bytearray()
        self.total = 0
        self.frames = 0
        self.samples = 0
        self.sample_rate = 0
        self.channels = 0
        self.metadata_bytes = 0
        self._start = True
        self._tag_size = None
        self._metadata = b''
        self._profile = None

    def feed(self, block: bytes) -> bytes:
        self.total += len(block)
        if self.total > MAX_MP3_BYTES:
            raise TTSProviderError('tts MP3 exceeds size limit')
        # Callers read at most 4 KiB. Enforce a bound even for other consumers.
        if len(block) > 4096:
            output = bytearray()
            self.total -= len(block)
            for offset in range(0, len(block), 4096):
                output.extend(self.feed(block[offset:offset + 4096]))
            return bytes(output)
        self.buffer.extend(block)
        output = bytearray()
        if self._start:
            if len(self.buffer) < 3:
                return b''
            if self.buffer[:3] == b'ID3':
                if len(self.buffer) < 10:
                    return b''
                header = self.buffer[:10]
                if header[3] not in (3, 4) or header[4] == 255 or any(v & 128 for v in header[6:10]):
                    raise TTSProviderError('tts returned invalid ID3 header')
                if header[5] & (0x0f if header[3] == 4 else 0x1f):
                    raise TTSProviderError('tts returned unsupported ID3 flags')
                size = 10 + sum(v << (7 * (3-i)) for i, v in enumerate(header[6:10]))
                if header[3] == 4 and header[5] & 16:
                    size += 10
                if size > MAX_METADATA_BYTES:
                    raise TTSProviderError('tts MP3 metadata exceeds limit')
                self._tag_size = size
                if len(self.buffer) < size:
                    return b''
                self._metadata = bytes(self.buffer[:size])
                del self.buffer[:size]
                self.metadata_bytes = size
            self._start = False
        while len(self.buffer) >= 4:
            a, b, c, d = self.buffer[:4]
            version = (b >> 3) & 3
            bitrate_index = c >> 4
            rate_index = (c >> 2) & 3
            if (a != 255 or b & 224 != 224 or version == 1 or (b >> 1) & 3 != 1
                    or bitrate_index in (0, 15) or rate_index == 3 or d & 3 == 2):
                raise TTSProviderError('tts returned invalid MPEG Layer III header')
            rates = (44100, 48000, 32000)
            sample_rate = rates[rate_index] // (1 if version == 3 else 2 if version == 2 else 4)
            if sample_rate < 16000:
                raise TTSProviderError('tts MP3 sample rate below supported range')
            channels = 1 if d >> 6 == 3 else 2
            profile = (version, sample_rate, channels)
            if self._profile is not None and self._profile != profile:
                raise TTSProviderError('tts MP3 profile changed within response')
            bitrates = ((0,32,40,48,56,64,80,96,112,128,160,192,224,256,320)
                        if version == 3 else (0,8,16,24,32,40,48,56,64,80,96,112,128,144,160))
            length = (144 if version == 3 else 72) * bitrates[bitrate_index] * 1000 // sample_rate + ((c >> 1) & 1)
            if len(self.buffer) < length:
                break
            self._profile = profile
            self.sample_rate = sample_rate
            self.channels = channels
            self.frames += 1
            self.samples += 1152 if version == 3 else 576
            if self._metadata:
                output.extend(self._metadata)
                self._metadata = b''
            output.extend(self.buffer[:length])
            del self.buffer[:length]
        return bytes(output)

    def finish(self):
        if not self.frames or self.buffer or self._start:
            raise TTSProviderError('tts returned incomplete MP3')
