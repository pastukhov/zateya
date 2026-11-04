import hashlib
import math
import struct

import pytest

from backend.src.voice_gateway.cues.opus import encode_pcm,decode_container,parse_container


def test_real_opus_preskip_and_final_trim_exact_duration():
    for samples in (1,479,480,481,24000,120000):
        pcm=b''.join(struct.pack('<h',int(5000*math.sin(i*.08))) for i in range(samples))
        encoded=encode_pcm(pcm)
        meta,packets=parse_container(encoded)
        assert len(encoded)<=65536
        assert meta['samples']==samples and meta['preskip']>0
        decoded=decode_container(encoded)
        assert len(decoded)==len(pcm)
        if samples>1000:assert max(abs(x[0]) for x in struct.iter_unpack('<h',decoded))>1000


def test_container_bounds_and_corruption_rejected():
    encoded=encode_pcm(b'\0\0'*1000)
    for bad in (encoded[:31],encoded[:-1],encoded+b'x',b'bad'+encoded[3:],encoded[:32]+b'\0\0'+encoded[34:]):
        with pytest.raises(ValueError):parse_container(bad)
    with pytest.raises(ValueError):encode_pcm(b'odd')
    with pytest.raises(ValueError):encode_pcm(b'\0\0'*120001)


def test_cache_encodes_existing_pcm_once_without_resynthesis(tmp_path):
    from backend.src.voice_gateway.cues.cache import CueCache
    from backend.src.voice_gateway.cues.test_cache import CONFIG,Synth
    synth=Synth();cache=CueCache(tmp_path,synth,CONFIG);cache.ensure()
    cache.ensure_opus('listening');manifest=cache.manifest('listening',codec='opus-v1')
    assert manifest['codec']=='opus-v1' and manifest['samples']==2400
    encoded=cache.opus_audio(manifest['sha256'])
    assert hashlib.sha256(encoded).hexdigest()==manifest['sha256']
    assert len(decode_container(encoded))==4800
    restarted=CueCache(tmp_path,synth,CONFIG);restarted.ensure_opus('listening')
    assert synth.calls==1
    assert restarted.manifest('listening',codec='opus-v1')==manifest
    assert cache.manifest()['size']==4800


def test_encoder_failure_keeps_pcm_and_retries_independently(tmp_path,monkeypatch):
    from backend.src.voice_gateway.cues.cache import CueCache
    from backend.src.voice_gateway.cues.test_cache import CONFIG,CatalogSynth
    from backend.src.voice_gateway.cues import opus
    synth=CatalogSynth();cache=CueCache(tmp_path,synth,CONFIG)
    real=opus.encode_pcm
    monkeypatch.setattr(opus,'encode_pcm',lambda _: (_ for _ in ()).throw(RuntimeError('encoder failure')))
    assert cache.ensure_all() is False
    assert cache.manifest() and cache.manifest('listening',codec='opus-v1') is None
    calls=len(synth.calls);monkeypatch.setattr(opus,'encode_pcm',real)
    assert cache.ensure_all() is True
    assert len(synth.calls)==calls


def test_routes_explicit_codec_auth_and_legacy_pcm(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.src.voice_gateway.cues.cache import CueCache,install_cue_routes
    from backend.src.voice_gateway.cues.test_cache import CONFIG,Synth
    synth=Synth();cache=CueCache(tmp_path,synth,CONFIG)
    app=FastAPI();install_cue_routes(app,cache,{'device':'token'})
    headers={'X-Device-Id':'device','Authorization':'Bearer token'}
    with TestClient(app) as client:
        assert client.get('/api/device/cues/listening?codec=opus-v1').status_code==401
        assert client.get('/api/device/cues/listening?codec=opus-v1',headers=headers).status_code==503
        assert synth.calls==0
        cache.ensure_opus('listening')
        manifest=client.get('/api/device/cues/listening?codec=opus-v1',headers=headers).json()
        path='/api/device/cues/audio/'+manifest['sha256']+'.vop'
        assert client.get(path).status_code==401
        encoded=client.get(path,headers=headers);assert encoded.status_code==200
        assert encoded.headers['content-type'].startswith('application/vnd.zateya.vcopus')
        assert hashlib.sha256(encoded.content).hexdigest()==manifest['sha256']
        assert client.get('/api/device/cues/listening?codec=unknown',headers=headers).status_code==400
        old=client.get('/api/device/cues/listening',headers=headers).json()
        assert 'codec' not in old
        assert client.get('/api/device/cues/audio/'+old['sha256']+'.pcm',headers=headers).status_code==200
        assert synth.calls==1


@pytest.mark.parametrize('suffix',['.vop','.opus.json'])
def test_corrupt_encoded_cache_regenerated_without_tts(tmp_path,suffix):
    from backend.src.voice_gateway.cues.cache import CueCache
    from backend.src.voice_gateway.cues.test_cache import CONFIG,Synth
    synth=Synth();cache=CueCache(tmp_path,synth,CONFIG);cache.ensure_opus('listening')
    original=cache.manifest('listening',codec='opus-v1')
    files=list(tmp_path.rglob('*'+suffix));assert len(files)==1
    files[0].write_bytes(b'corrupt')
    restarted=CueCache(tmp_path,synth,CONFIG);restarted.ensure_opus('listening')
    assert synth.calls==1
    assert restarted.manifest('listening',codec='opus-v1')==original
