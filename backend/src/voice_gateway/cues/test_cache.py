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
