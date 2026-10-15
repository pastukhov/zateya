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

_LOG = logging.getLogger(__name__)
_MAX_BYTES = 240000  # Five seconds of PCM16 mono, 24 kHz.


class CueCache:
    def __init__(self, root: Path, provider, config: TTSConfig):
        self.root = root
        self.provider = provider
        identity = {'text': 'Слушаю.', 'format': 'pcm16le-24000-mono-v1',
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
                if meta['sha256'] != hashlib.sha256(pcm).hexdigest():
                    raise ValueError('Corrupt cache')
                self._publish(pcm)
                return
            except (OSError, ValueError, KeyError, TypeError):
                pass
            with tempfile.TemporaryDirectory(prefix='.cue-', dir=self.root) as folder:
                wav_path = Path(folder) / 'listening.wav'
                self.provider.synthesize('Слушаю.', wav_path)
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
                _LOG.info('Device listening cue ready (bytes=%d)', len(pcm))

    async def run(self) -> None:
        # Cancellation waits for bounded provider I/O before its client is closed.
        while True:
            work = asyncio.create_task(asyncio.to_thread(self.ensure))
            try:
                await asyncio.shield(work)
                return
            except asyncio.CancelledError:
                await asyncio.gather(work, return_exceptions=True)
                raise
            except Exception:
                _LOG.warning('Device listening cue generation failed; retry in 60 seconds')
                await asyncio.sleep(60)


def install_cue_routes(app: FastAPI, cache: CueCache | None,
                       device_tokens: dict[str, str]) -> None:
    def authenticate(request: Request) -> None:
        if not owns_device(request.headers.get('X-Device-Id', ''),
                           request.headers.get('Authorization'), device_tokens):
            raise HTTPException(status_code=401)

    @app.get('/api/device/cues/listening')
    def manifest(request: Request):
        authenticate(request)
        data = cache.manifest() if cache else None
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
