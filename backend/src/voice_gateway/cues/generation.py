"""Complete, durable MP3 cue generations and bounded historical voice profiles."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import threading
import time

from backend.src.voice_gateway.cues.cache import CUE_TEXTS, _atomic_cache_bytes
from backend.src.voice_gateway.cues.mp3_decode import MAX_CUE_BYTES, validate_mp3
from backend.src.voice_gateway.tts.config import TTSConfig

_LOG = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
MAX_GENERATION_BYTES = 600000  # Two generations fit the 1.5 MiB device cache budget.


class UnknownCueGeneration(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


class MP3CueGenerations:
    def __init__(self, root: Path, provider, config: TTSConfig, *, provider_factory=None,
                 retained: int = 3, texts=None, clock=time.time):
        if config.response_format != 'mp3':
            raise ValueError('MP3 cues require MP3 TTS')
        self.root, self.provider, self.config = Path(root), provider, config
        self.texts = dict(CUE_TEXTS if texts is None else texts)
        if set(self.texts) != set(CUE_TEXTS):
            raise ValueError('MP3 generation requires the complete cue catalog')
        profile = asdict(config)
        profile.pop('api_key')
        if not config.language_code:
            profile.pop('language_code')  # Preserve every pre-language generation ID.
        self.identity = {'profile': profile, 'texts': self.texts,
                         'format': 'mpeg1-layer3-44100-mono-v1', 'version': 1}
        self.generation_id = hashlib.sha256(_json(self.identity)).hexdigest()
        self._factory = provider_factory or type(provider)
        self._retained = max(2, retained)
        self._clock = clock
        self._lock = threading.Lock()
        self._generations = {}
        self._providers = {self.generation_id: provider}
        self._active = None
        self._attempts = 0
        self._next_retry = 0
        self._error = False
        self.root.mkdir(parents=True, exist_ok=True)
        self._load()
        for stale in self.root.glob('.staging-*'):
            if stale.name != '.staging-' + self.generation_id and stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)

    def _load_generation(self, folder):
        manifest = json.loads((folder / 'manifest.json').read_text())
        identity = json.loads((folder / 'profile.json').read_text())
        generation = hashlib.sha256(_json(identity)).hexdigest()
        if generation != folder.name or manifest['generation_id'] != generation:
            raise ValueError('Invalid generation identity')
        if set(manifest['items']) != set(identity['texts']):
            raise ValueError('Incomplete generation')
        if sum(item['size'] for item in manifest['items'].values()) > MAX_GENERATION_BYTES:
            raise ValueError('Oversized MP3 generation')
        for name, item in manifest['items'].items():
            if name not in CUE_TEXTS or not isinstance(item['size'], int) or not 0 < item['size'] <= MAX_CUE_BYTES:
                raise ValueError('Invalid cue metadata')
            path = folder / (name + '.mp3')
            if path.stat().st_size != item['size']:
                raise ValueError('Invalid cue size')
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('Invalid cue digest')
            try:
                decoded = validate_mp3(data)
            except Exception as exc:
                raise ValueError('Invalid MP3 cue') from exc
            if any(item[key] != value for key, value in decoded.items()):
                raise ValueError('Invalid cue profile')
        return manifest, identity

    def _load(self):
        folders = sorted((p for p in self.root.iterdir() if p.is_dir() and len(p.name) == 64),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for folder in folders[:self._retained]:
            try:
                manifest, identity = self._load_generation(folder)
                self._generations[folder.name] = (manifest, identity)
            except (OSError, ValueError, KeyError, TypeError):
                _LOG.warning('Invalid MP3 cue generation ignored')
        try:
            active = json.loads((self.root / 'active.json').read_text())['generation_id']
            if active in self._generations:
                self._active = active
        except (OSError, ValueError, KeyError, TypeError):
            pass
        try:
            retry = json.loads((self.root / 'retry.json').read_text())
            if retry['generation_id'] == self.generation_id:
                self._attempts = min(10, max(0, int(retry['attempts'])))
                self._next_retry = min(float(retry['next_retry']), self._clock() + 3600)
                self._error = self._attempts > 0
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def manifest(self, generation_id=None):
        generation = generation_id or self._active
        item = self._generations.get(generation)
        return json.loads(_json(item[0])) if item else None

    def status(self):
        return {'generation_id': self.generation_id, 'active_generation_id': self._active,
                'status': 'ready' if self._active == self.generation_id else 'exhausted' if self._attempts >= MAX_ATTEMPTS else 'error' if self._error else 'preparing',
                'attempts': self._attempts, 'next_retry': self._next_retry}

    def audio(self, generation_id, name):
        manifest = self.manifest(generation_id)
        if not manifest or name not in manifest['items']:
            return None
        try:
            data = (self.root / generation_id / (name + '.mp3')).read_bytes()
            item = manifest['items'][name]
            if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                return None
            return data
        except OSError:
            return None

    def resolve_mp3_profile(self, generation_id):
        generation_id = generation_id or self._active
        if generation_id not in self._generations:
            raise UnknownCueGeneration('cue_generation_update_required')
        if generation_id not in self._providers:
            profile = self._generations[generation_id][1]['profile']
            config = TTSConfig(**profile, api_key=self.config.api_key)
            self._providers[generation_id] = self._factory(config)
        return self._providers[generation_id]

    def ensure_all(self):
        with self._lock:
            if self._active == self.generation_id:
                return True
            if self._attempts >= MAX_ATTEMPTS or self._clock() < self._next_retry:
                return False
            # Reserve this attempt durably before any provider call. A process
            # death consumes the attempt and preserves backoff across restart.
            self._attempts += 1
            self._next_retry = self._clock() + min(3600, 60 * 2 ** (self._attempts - 1))
            self._persist_retry()
            try:
                # A crash after directory rename but before active pointer needs no paid calls.
                destination = self.root / self.generation_id
                if self.generation_id not in self._generations:
                    if destination.exists():
                        try:
                            self._generations[self.generation_id] = self._load_generation(destination)
                        except (OSError, ValueError, KeyError, TypeError):
                            shutil.rmtree(destination)
                    if self.generation_id not in self._generations:
                        folder = self.root / ('.staging-' + self.generation_id)
                        folder.mkdir(exist_ok=True)
                        items = {}
                        total_bytes = 0
                        for name, text in self.texts.items():
                            path = folder / (name + '.mp3')
                            try:
                                if path.stat().st_size > MAX_CUE_BYTES:
                                    raise ValueError('Oversized MP3 cue')
                                cached = path.read_bytes()
                                metadata = json.loads(path.with_suffix('.json').read_text())
                                if hashlib.sha256(cached).hexdigest() != metadata['sha256']:
                                    raise ValueError('Invalid staged cue hash')
                                validate_mp3(cached)
                            except Exception:
                                path.unlink(missing_ok=True)
                                self.provider.synthesize(text, path)
                            if path.stat().st_size > MAX_CUE_BYTES:
                                raise ValueError('Oversized MP3 cue')
                            data = path.read_bytes()
                            total_bytes += len(data)
                            if total_bytes > MAX_GENERATION_BYTES:
                                raise ValueError('Oversized MP3 generation')
                            decoded = validate_mp3(data)
                            items[name] = dict(sha256=hashlib.sha256(data).hexdigest(), size=len(data),
                                              url=f'/api/device/cues/mp3/{self.generation_id}/{name}.mp3', **decoded)
                            with path.open('rb') as audio:
                                os.fsync(audio.fileno())
                            _atomic_cache_bytes(path.with_suffix('.json'), _json({'sha256': items[name]['sha256']}))
                            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
                            try:
                                os.fsync(fd)
                            finally:
                                os.close(fd)
                        manifest = dict(generation_id=self.generation_id, codec='mp3', status='ready', items=items)
                        _atomic_cache_bytes(folder / 'profile.json', _json(self.identity))
                        _atomic_cache_bytes(folder / 'manifest.json', _json(manifest))
                        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                        os.replace(folder, destination)
                        self._sync_root()
                        self._generations[self.generation_id] = (manifest, self.identity)
                _atomic_cache_bytes(self.root / 'active.json', _json({'generation_id': self.generation_id}))
                self._sync_root()
                self._active = self.generation_id
                self._error = False
                self._attempts = 0
                self._next_retry = 0
                self._persist_retry()
                self._prune()
                return True
            except Exception:
                self._error = True
                self._persist_retry()
                _LOG.warning('MP3 cue generation failed; retry deferred (attempt=%d)', self._attempts)
                return False

    def _persist_retry(self):
        _atomic_cache_bytes(self.root / 'retry.json', _json(dict(
            generation_id=self.generation_id, attempts=self._attempts,
            next_retry=self._next_retry)))
        self._sync_root()

    def _sync_root(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _prune(self):
        old = sorted((key for key in self._generations if key != self._active),
                     key=lambda key: (self.root / key).stat().st_mtime, reverse=True)
        for key in old[self._retained - 1:]:
            self._generations.pop(key, None)
            provider = self._providers.pop(key, None)
            if provider is not None and provider is not self.provider and hasattr(provider, 'close'):
                provider.close()
            shutil.rmtree(self.root / key, ignore_errors=True)

    async def run(self):
        while True:
            work = asyncio.create_task(asyncio.to_thread(self.ensure_all))
            try:
                if await asyncio.shield(work) or self._attempts >= MAX_ATTEMPTS:
                    return
            except asyncio.CancelledError:
                await asyncio.gather(work, return_exceptions=True)
                raise
            await asyncio.sleep(max(1, self._next_retry - self._clock()))
