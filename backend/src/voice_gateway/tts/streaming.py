"""Bounded incremental finite RIFF extraction; no metadata enters the PCM sink."""
import struct
from pathlib import Path
from backend.src.voice_gateway.tts.base import TTSProviderError
from backend.src.voice_gateway.tts.wav import pcm_wav

MAX_TTS_BYTES=16*1024*1024


class FiniteWavWriter:
    def __init__(self,path: Path,ready):
        self.path=path;self.ready=ready;self.buffer=bytearray();self.state='riff'
        self.total=0;self.end=None;self.remaining=0;self.fmt=False;self.data=False
        self.fallback=False;self.file=None;self.carry=b'';self.expected=0;self.pad=False

    def feed(self,block: bytes):
        if self.fallback:return
        self.total+=len(block)
        if self.end is not None and self.total>self.end:raise TTSProviderError('tts returned trailing WAV bytes')
        offset=0
        while offset<len(block):
            if self.state in ('riff','chunk','fmt'):
                need={'riff':12,'chunk':8,'fmt':16}[self.state]
                take=min(need-len(self.buffer),len(block)-offset)
                self.buffer.extend(block[offset:offset+take]);offset+=take
                if len(self.buffer)<need:return
                header=bytes(self.buffer);self.buffer.clear()
                if self.state=='riff':
                    if header[:4]!=b'RIFF' or header[8:]!=b'WAVE' or header[4:8]==b'\xff'*4:
                        self.fallback=True;return
                    self.end=int.from_bytes(header[4:8],'little')+8
                    if self.end<12 or self.end>MAX_TTS_BYTES or self.total>self.end:raise TTSProviderError('tts returned invalid WAV bounds')
                    self.state='chunk'
                elif self.state=='fmt':
                    if struct.unpack('<HHIIHH',header)!=(1,1,24000,48000,2,16):
                        self.fallback=True;return
                    self.fmt=True;self.state='chunk'
                else:
                    tag=header[:4];length=int.from_bytes(header[4:],'little')
                    position=self.total-(len(block)-offset)
                    if length==0xffffffff and tag==b'data' and not self.data:
                        self.fallback=True;return
                    if position+length+(length&1)>self.end:raise TTSProviderError('tts returned invalid WAV chunk bounds')
                    if tag==b'fmt ':
                        if self.fmt or self.data:raise TTSProviderError('tts returned duplicate WAV format')
                        if length!=16:self.fallback=True;return
                        self.state='fmt'
                    elif tag==b'data':
                        if not self.fmt or self.data or not length or length&1:raise TTSProviderError('tts returned invalid PCM data')
                        self.data=True;self.remaining=length;self.expected=44+length;self.state='data'
                    else:
                        self.remaining=length+(length&1);self.state='skip' if self.remaining else 'chunk'
            else:
                take=min(self.remaining,len(block)-offset)
                payload=block[offset:offset+take];offset+=take;self.remaining-=take
                if self.state=='data':
                    payload=self.carry+payload;self.carry=payload[-1:] if len(payload)&1 else b''
                    if self.carry:payload=payload[:-1]
                    if payload:
                        first=self.file is None
                        if first:
                            self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open('wb')
                            header=bytearray(pcm_wav(b'',24000));header[4:8]=(self.expected-8).to_bytes(4,'little');header[40:44]=(self.expected-44).to_bytes(4,'little')
                            self.file.write(header)
                        self.file.write(payload);self.file.flush()
                        if first:self.ready(self.expected)
                if not self.remaining:self.state='chunk'

    def finish(self):
        if self.fallback:return False
        if self.end!=self.total or self.state!='chunk' or self.buffer or not self.data or self.carry:
            raise TTSProviderError('tts returned an incomplete streaming WAV')
        if self.file:self.file.close();self.file=None
        return True

    def abort(self):
        if self.file:self.file.close();self.file=None
        self.path.unlink(missing_ok=True)
