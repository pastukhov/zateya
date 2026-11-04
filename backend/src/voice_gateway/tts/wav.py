"""Read RIFF chunk boundaries before publishing PCM; metadata is never audio."""
from io import BytesIO
import wave

from backend.src.voice_gateway.tts.base import TTSProviderError


def wav_pcm(body: bytes, *, finite: bool = False) -> tuple[bytes, int]:
    if len(body)<12 or body[:4]!=b'RIFF' or body[8:12]!=b'WAVE':
        raise TTSProviderError('tts returned an invalid WAV container')
    declared=int.from_bytes(body[4:8],'little')
    if declared==0xffffffff:
        if finite:raise TTSProviderError('tts returned an unbounded WAV container')
        end=len(body)
    else:
        end=declared+8
        if end!=len(body):raise TTSProviderError('tts returned a truncated or trailing WAV container')
    try:
        with wave.open(BytesIO(body),'rb') as wav:
            channels,width,rate=wav.getnchannels(),wav.getsampwidth(),wav.getframerate()
    except (wave.Error,EOFError) as exc:
        raise TTSProviderError('tts returned an invalid WAV response') from exc
    if channels!=1 or width!=2:
        raise TTSProviderError(f'tts returned a WAV that is not PCM16 mono (channels={channels}, sample_width={width})')
    if rate not in (16000,24000):
        raise TTSProviderError(f'tts returned an unsupported sample rate: {rate}')
    position=12;pcm=None;fmt_seen=False
    while position<end:
        if end-position<8:raise TTSProviderError('tts returned a truncated WAV chunk')
        tag=body[position:position+4];size=int.from_bytes(body[position+4:position+8],'little');start=position+8
        if size==0xffffffff:
            if finite or tag!=b'data' or declared!=0xffffffff:
                raise TTSProviderError('tts returned an unsupported unbounded WAV chunk')
            # An unknown-length streaming data chunk extends to EOF. No scan
            # for ASCII markers inside PCM can safely identify its boundary.
            size=end-start
        stop=start+size
        if stop>end:raise TTSProviderError('tts returned a truncated WAV chunk')
        if tag==b'fmt ':
            if fmt_seen or pcm is not None:raise TTSProviderError('tts returned ambiguous WAV format chunks')
            fmt_seen=True
        elif tag==b'data':
            if not fmt_seen or pcm is not None or size%2:
                raise TTSProviderError('tts returned ambiguous or incomplete PCM frames')
            pcm=body[start:stop]
        position=stop+(size&1)
        if position>end:raise TTSProviderError('tts returned a missing WAV chunk pad')
    if pcm is None:raise TTSProviderError('tts returned a WAV without audio')
    return pcm,rate


def pcm_wav(pcm: bytes,rate: int) -> bytes:
    output=BytesIO()
    with wave.open(output,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(pcm)
    return output.getvalue()


def normalize_wav(body: bytes) -> bytes:
    pcm,rate=wav_pcm(body)
    return pcm_wav(pcm,rate)
