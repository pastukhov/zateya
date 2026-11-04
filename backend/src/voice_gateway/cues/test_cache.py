import hashlib
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.voice_gateway.tts.config import TTSConfig
from backend.src.voice_gateway.cues.cache import CueCache, install_cue_routes

CONFIG = TTSConfig(base_url='https://secret-provider/audio/speech', model='m', voice='v', api_key='secret')

class Synth:
    calls = 0
    bad = False
    def synthesize(self, text, out_path):
        self.calls += 1
        assert text == 'Слушаю.'
        if self.bad:
            raise RuntimeError('secret provider error')
        with wave.open(str(out_path), 'wb') as f:
            f.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            f.writeframes(b'\x01\x00' * 2400)


def test_singleflight_restart_and_voice_change(tmp_path):
    synth = Synth()
    cache = CueCache(tmp_path, synth, CONFIG)
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: cache.ensure(), range(4)))
    assert synth.calls == 1
    manifest = cache.manifest()
    assert manifest['size'] == 4800
    assert manifest['sha256'] == hashlib.sha256(cache.audio(manifest['sha256'])).hexdigest()
    assert 'secret' not in str(manifest)
    CueCache(tmp_path, synth, CONFIG).ensure()
    assert synth.calls == 1
    changed = CueCache(tmp_path, synth, replace(CONFIG, voice='new'))
    changed.ensure()
    assert synth.calls == 2
    assert changed.version != cache.version


def test_corruption_regenerated_and_failure_not_published(tmp_path):
    synth = Synth()
    cache = CueCache(tmp_path, synth, CONFIG)
    cache.ensure()
    for p in tmp_path.glob('*.pcm'):
        p.write_bytes(b'broken')
    restarted = CueCache(tmp_path, synth, CONFIG)
    restarted.ensure()
    assert synth.calls == 2
    synth.bad = True
    changed = CueCache(tmp_path, synth, replace(CONFIG, voice='new'))
    with pytest.raises(RuntimeError):
        changed.ensure()
    assert changed.manifest() is None
    assert cache.manifest() is not None


def test_routes_private_pending_immutable_and_no_synthesis(tmp_path):
    synth = Synth()
    cache = CueCache(tmp_path, synth, CONFIG)
    app = FastAPI()
    install_cue_routes(app, cache, {'device': 'token'})
    with TestClient(app) as client:
        headers = {'X-Device-Id': 'device', 'Authorization': 'Bearer token'}
        assert client.get('/api/device/cues/listening').status_code == 401
        assert client.get('/api/device/cues/listening', headers=headers).status_code == 503
        assert synth.calls == 0
        cache.ensure()
        response = client.get('/api/device/cues/listening', headers=headers)
        assert response.status_code == 200
        path = '/api/device/cues/audio/' + response.json()['sha256'] + '.pcm'
        assert client.get(path).status_code == 401
        assert client.get(path, headers=headers).content == b'\x01\x00' * 2400
        assert client.get('/api/device/cues/audio/' + '0' * 64 + '.pcm', headers=headers).status_code == 404
        assert synth.calls == 1


@pytest.mark.parametrize('rate,channels,size', [(16000,1,20),(24000,2,20),(24000,1,0),(24000,1,240002)])
def test_reject_bad_audio(tmp_path, rate, channels, size):
    class Bad:
        def synthesize(self, text, out_path):
            with wave.open(str(out_path), 'wb') as f:
                f.setparams((channels,2,rate,0,'NONE','not compressed'))
                f.writeframes(b'\0' * size)
    cache = CueCache(tmp_path, Bad(), CONFIG)
    with pytest.raises(ValueError):
        cache.ensure()
    assert cache.manifest() is None


class CatalogSynth:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def synthesize(self, text, out_path):
        self.calls.append(text)
        if text == self.fail:
            raise RuntimeError('provider unavailable')
        with wave.open(str(out_path), 'wb') as f:
            f.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            f.writeframes(bytes([len(self.calls), 0]) * 2400)


def test_three_cues_independent_failure_retry_restart_and_voice(tmp_path):
    synth = CatalogSynth(fail='Обрабатываю.')
    cache = CueCache(tmp_path, synth, CONFIG)
    assert cache.ensure_all() is False
    assert cache.manifest('listening')
    assert cache.manifest('processing') is None
    assert cache.manifest('offline')
    synth.fail = None
    assert cache.ensure_all() is True
    assert synth.calls == ['Слушаю.', 'Обрабатываю.', 'Нет связи.', 'Обрабатываю.']
    calls = len(synth.calls)
    restarted = CueCache(tmp_path, synth, CONFIG)
    assert restarted.ensure_all()
    assert len(synth.calls) == calls
    assert restarted.manifest() == restarted.manifest('listening')
    assert len({restarted.manifest(name)['version'] for name in ('listening', 'processing', 'offline')}) == 3
    changed = CueCache(tmp_path, synth, replace(CONFIG, voice='new'))
    assert changed.ensure_all()
    assert len(synth.calls) == calls + 3
    for name in ('listening','processing','offline'):
        assert changed.manifest(name)['version'] != restarted.manifest(name)['version']
    assert cache.manifest('invented') is None


def test_named_cue_routes_auth_unknown_and_no_request_synthesis(tmp_path):
    synth = CatalogSynth()
    cache = CueCache(tmp_path, synth, CONFIG)
    app = FastAPI(); install_cue_routes(app, cache, {'device': 'token'})
    with TestClient(app) as client:
        headers = {'X-Device-Id': 'device', 'Authorization': 'Bearer token'}
        for name in ('listening','processing','offline'):
            assert client.get('/api/device/cues/'+name).status_code == 401
            assert client.get('/api/device/cues/'+name,headers=headers).status_code == 503
        assert not synth.calls
        assert client.get('/api/device/cues/invented',headers=headers).status_code == 404
        assert cache.ensure_all()
        for name in ('listening','processing','offline'):
            manifest = client.get('/api/device/cues/'+name,headers=headers).json()
            audio = client.get('/api/device/cues/audio/'+manifest['sha256']+'.pcm',headers=headers)
            assert audio.status_code == 200
            assert len(audio.content) == manifest['size']
            assert hashlib.sha256(audio.content).hexdigest() == manifest['sha256']
        assert len(synth.calls) == 3


def test_listening_reuses_pre_catalog_persistent_key(tmp_path):
    import json
    identity = {'text': 'Слушаю.', 'format': 'pcm16le-24000-mono-v1',
                'endpoint': CONFIG.base_url, 'model': CONFIG.model, 'voice': CONFIG.voice,
                'instructions': CONFIG.instructions, 'response_format': CONFIG.response_format}
    old_version = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    pcm = b'\x01\x00' * 2400
    (tmp_path / (old_version+'.pcm')).write_bytes(pcm)
    (tmp_path / (old_version+'.json')).write_text(json.dumps({'sha256':hashlib.sha256(pcm).hexdigest()}))
    synth = Synth(); synth.bad = True
    cache = CueCache(tmp_path, synth, CONFIG)
    cache.ensure()
    assert cache.version == old_version
    assert synth.calls == 0
    assert cache.audio(cache.manifest()['sha256']) == pcm
