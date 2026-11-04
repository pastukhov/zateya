"""Versioned private device prompts, synthesized off the request path."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import wave
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from backend.src.voice_gateway.jobs.auth import owns_device
from backend.src.voice_gateway.tts.config import TTSConfig
from backend.src.voice_gateway.tts.base import TTSProviderError
from backend.src.voice_gateway.tts.wav import wav_pcm
from backend.src.voice_gateway.cues import opus

_LOG = logging.getLogger(__name__)
_MAX_BYTES = 240000  # Five seconds of PCM16 mono, 24 kHz.


CUE_TEXTS = {
    'listening': 'Слушаю.', 'processing': 'Обрабатываю.', 'offline': 'Нет связи.',
    'ready': 'Готова к записи.', 'done': 'Готово.', 'cancelled': 'Отменено.',
    'transcribing': 'Распознаю.', 'thinking': 'Думаю.', 'synthesizing': 'Готовлю ответ.',
    'answering': 'Отвечаю.', 'error': 'Произошла ошибка.',
    'timeout': 'Не дождалась ответа.', 'recognition_error': 'Не удалось распознать речь.',
    'synthesis_error': 'Не удалось озвучить ответ.',
}


def _atomic_cache_bytes(path: Path, data: bytes) -> None:
    with tempfile.NamedTemporaryFile(prefix='.cue-repair-',dir=path.parent,delete=False) as file:
        temporary=Path(file.name)
        try:
            file.write(data);file.flush();os.fsync(file.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True);raise
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def _repair_cache(pcm_path: Path,meta_path: Path,pcm: bytes,meta: dict) -> bytes:
    repaired=pcm
    if pcm.startswith(b'RIFF'):
        try:
            candidate,rate=wav_pcm(pcm,finite=True)
            if rate==24000 and candidate and len(candidate)<=_MAX_BYTES:
                repaired=candidate
        except TTSProviderError:
            pass  # Bare PCM is changed only after a complete container validates.
    digest=hashlib.sha256(repaired).hexdigest()
    if repaired!=pcm:
        # Two file names cannot be replaced in one rename. Write-ahead metadata
        # accepts exactly the verified old/new digests across an interrupted
        # repair; restart completes it without synthesizing again.
        intent={'sha256':hashlib.sha256(pcm).hexdigest(),'repair_sha256':digest}
        try:
            _atomic_cache_bytes(meta_path,json.dumps(intent).encode())
            _atomic_cache_bytes(pcm_path,repaired)
            _atomic_cache_bytes(meta_path,json.dumps({'sha256':digest}).encode())
        except OSError:
            _LOG.warning('Cue cache repair persistence deferred')
    elif 'repair_sha256' in meta:
        try:_atomic_cache_bytes(meta_path,json.dumps({'sha256':digest}).encode())
        except OSError:_LOG.warning('Cue cache repair metadata deferred')
    return repaired


class _Cue:
    def __init__(self, root: Path, provider, config: TTSConfig, text: str):
        self.root = root
        self.text = text
        self.provider = provider
        identity = {'text': text, 'format': 'pcm16le-24000-mono-v1',
                    'endpoint': config.base_url, 'model': config.model,
                    'voice': config.voice, 'instructions': config.instructions,
                    'response_format': config.response_format}
        self.version = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self._lock = threading.Lock()
        self._pcm: bytes | None = None
        self._manifest: dict | None = None

    def manifest(self) -> dict | None:
        return dict(self._manifest) if self._manifest is not None else None

    def audio(self, digest: str) -> bytes | None:
        manifest = self._manifest
        return self._pcm if manifest and digest == manifest['sha256'] else None

    def _publish(self, pcm: bytes) -> None:
        if not pcm or len(pcm) > _MAX_BYTES or len(pcm) % 2:
            raise ValueError('Invalid cue length')
        self._pcm = pcm
        self._manifest = {'version': self.version, 'sha256': hashlib.sha256(pcm).hexdigest(),
                          'size': len(pcm), 'sample_rate': 24000, 'channels': 1,
                          'bits_per_sample': 16}

    def ensure(self) -> None:
        # One production cache instance per backend process; threads share this lock.
        with self._lock:
            if self._manifest is not None:
                return
            self.root.mkdir(parents=True, exist_ok=True)
            pcm_path = self.root / f'{self.version}.pcm'
            meta_path = self.root / f'{self.version}.json'
            try:
                if pcm_path.stat().st_size > _MAX_BYTES:
                    raise ValueError('Oversized cache')
                pcm = pcm_path.read_bytes()
                meta = json.loads(meta_path.read_text())
                if hashlib.sha256(pcm).hexdigest() not in (meta['sha256'],meta.get('repair_sha256')):
                    raise ValueError('Corrupt cache')
                pcm=_repair_cache(pcm_path,meta_path,pcm,meta)
                self._publish(pcm)
                return
            except (OSError, ValueError, KeyError, TypeError):
                pass
            with tempfile.TemporaryDirectory(prefix='.cue-', dir=self.root) as folder:
                wav_path = Path(folder) / 'listening.wav'
                self.provider.synthesize(self.text, wav_path)
                with wave.open(str(wav_path), 'rb') as wav:
                    if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 24000, 'NONE'):
                        raise ValueError('Unsupported cue format')
                    frames = wav.getnframes()
                    if not 0 < frames <= _MAX_BYTES // 2:
                        raise ValueError('Invalid cue duration')
                    pcm = wav.readframes(frames)
                    if len(pcm) != frames * 2:
                        raise ValueError('Truncated cue')
                digest = hashlib.sha256(pcm).hexdigest()
                audio_tmp = Path(folder) / 'cue.pcm'
                meta_tmp = Path(folder) / 'cue.json'
                audio_tmp.write_bytes(pcm)
                meta_tmp.write_text(json.dumps({'sha256': digest}))
                os.replace(audio_tmp, pcm_path)
                os.replace(meta_tmp, meta_path)
                self._publish(pcm)
                _LOG.info('Device cue ready (bytes=%d)', len(pcm))

class CueCache:
    """Fixed independent catalog; provider access is serialized off HTTP paths.

    Legacy methods default to listening and its config/text digest is unchanged.
    Persistent entries share a directory but each has its own content identity.
    """
    def __init__(self, root: Path, provider, config: TTSConfig):
        self._cues = {name: _Cue(root, provider, config, text) for name, text in CUE_TEXTS.items()}
        self._provider_lock = threading.Lock()
        self.version = self._cues['listening'].version
        self._opus = {}

    def manifest(self, name: str = 'listening', *, codec: str = 'pcm') -> dict | None:
        if codec=='opus-v1':
            item=self._opus.get(name)
            return dict(item[0]) if item else None
        cue = self._cues.get(name)
        return cue.manifest() if cue else None

    def audio(self, digest: str) -> bytes | None:
        for cue in self._cues.values():
            pcm = cue.audio(digest)
            if pcm is not None:
                return pcm
        return None

    def ensure(self, name: str = 'listening') -> None:
        # TTS providers need not support overlapping synchronous calls.
        with self._provider_lock:
            self._cues[name].ensure()

    def ensure_opus(self,name: str) -> None:
        self.ensure(name)
        with self._provider_lock:
            if name in self._opus:return
            cue=self._cues[name];pcm=cue._pcm
            source=hashlib.sha256(pcm).hexdigest()
            identity=dict(pcm_version=cue.version,source_sha256=source,codec='opus-v1',
                          rate=24000,channels=1,bitrate=24000,frame=480,complexity=5,
                          encoder=opus.library().opus_get_version_string().decode())
            version=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            audio_path=cue.root/(version+'.vop');meta_path=cue.root/(version+'.opus.json')
            try:
                if audio_path.stat().st_size>opus.MAX_BYTES:raise ValueError('Oversized Opus')
                encoded=audio_path.read_bytes();stored=json.loads(meta_path.read_text())
                if stored['sha256']!=hashlib.sha256(encoded).hexdigest():raise ValueError('Corrupt Opus')
                opus.decode_container(encoded)
                metadata,_=opus.parse_container(encoded)
                if metadata['samples']!=len(pcm)//2:raise ValueError('Wrong Opus duration')
            except (OSError,ValueError,KeyError,TypeError):
                encoded=opus.encode_pcm(pcm);metadata,_=opus.parse_container(encoded)
                # No TTS call: compression is derived from verified cached PCM.
                opus.decode_container(encoded)
                with tempfile.TemporaryDirectory(prefix='.opus-',dir=cue.root) as folder:
                    audio_tmp=Path(folder)/'cue.vop';meta_tmp=Path(folder)/'cue.json'
                    audio_tmp.write_bytes(encoded)
                    meta_tmp.write_text(json.dumps({'sha256':hashlib.sha256(encoded).hexdigest()}))
                    os.replace(audio_tmp,audio_path);os.replace(meta_tmp,meta_path)
            manifest=dict(version=version,sha256=hashlib.sha256(encoded).hexdigest(),size=len(encoded),
                          codec='opus-v1',container='vcopus1',sample_rate=24000,channels=1,
                          bits_per_sample=16,bitrate=24000,**metadata)
            self._opus[name]=(manifest,encoded)

    def opus_audio(self,digest):
        return next((data for manifest,data in self._opus.copy().values() if manifest['sha256']==digest),None)

    def ensure_all(self) -> bool:
        complete = True
        for name in self._cues:
            try:
                self.ensure(name)
                self.ensure_opus(name)
            except Exception:
                complete = False
                _LOG.warning('Device %s cue generation failed; retry in 60 seconds', name)
        return complete

    async def run(self) -> None:
        while True:
            work = asyncio.create_task(asyncio.to_thread(self.ensure_all))
            try:
                complete = await asyncio.shield(work)
            except asyncio.CancelledError:
                # Wait for bounded synthesis before app closes the shared client.
                await asyncio.gather(work, return_exceptions=True)
                raise
            if complete:
                return
            await asyncio.sleep(60)


def install_cue_routes(app: FastAPI, cache: CueCache | None,
                       device_tokens: dict[str, str]) -> None:
    def authenticate(request: Request) -> None:
        if not owns_device(request.headers.get('X-Device-Id', ''),
                           request.headers.get('Authorization'), device_tokens):
            raise HTTPException(status_code=401)

    @app.get('/api/device/cues/{name}')
    def manifest(request: Request, name: str, codec: str = 'pcm'):
        authenticate(request)
        if name not in CUE_TEXTS:
            raise HTTPException(status_code=404)
        if codec not in {'pcm','opus-v1'}:
            raise HTTPException(status_code=400)
        data = cache.manifest(name,codec=codec) if cache else None
        if data is None:
            return Response(status_code=503, headers={'Retry-After': '60'})
        return data

    @app.get('/api/device/cues/audio/{digest}.pcm')
    def audio(request: Request, digest: str):
        authenticate(request)
        data = cache.audio(digest) if cache and re.fullmatch('[0-9a-f]{64}', digest) else None
        if data is None:
            raise HTTPException(status_code=404)
        return Response(data, media_type='application/octet-stream',
                        headers={'ETag': f'"{digest}"', 'Cache-Control': 'private, no-store'})

    @app.get('/api/device/cues/audio/{digest}.vop')
    def opus_audio(request: Request,digest: str):
        authenticate(request)
        data=cache.opus_audio(digest) if cache and re.fullmatch('[0-9a-f]{64}',digest) else None
        if data is None:raise HTTPException(status_code=404)
        return Response(data,media_type='application/vnd.zateya.vcopus',
                        headers={'ETag':f'"{digest}"','Cache-Control':'private, no-store'})
