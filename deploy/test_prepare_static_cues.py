"""Offline checks of imported spoken assets; no provider credentials needed."""
import importlib.util
import wave
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('static_cues', Path(__file__).parent/'firmware/prepare-static-cues.py')
cues = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cues)


def wav(path, rate=24000):
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
        output.writeframes(b'\0\0'*2400)


def test_import_and_manifest_reject_corruption_preserve_previous_header(tmp_path):
    source = tmp_path/'cue.wav'; wav(source)
    assets = tmp_path/'assets'; header = tmp_path/'manifest.h'
    for name in cues.PHRASES:
        cues.import_wav(source, assets, name, 'test-model', 'test-voice')
    cues.manifest(assets, header)
    old = header.read_text()
    (assets/'voice-offline.pcm').write_bytes(b'\0\0')
    with pytest.raises(ValueError, match='hash'):
        cues.manifest(assets, header)
    assert header.read_text() == old


def test_wrong_pcm_rate_never_replaces_valid_asset(tmp_path):
    source = tmp_path/'cue.wav'; wav(source)
    cues.import_wav(source, tmp_path, 'listening', 'test', 'test')
    old = (tmp_path/'voice-listening.pcm').read_bytes()
    wav(source, 16000)
    with pytest.raises(ValueError, match='24 kHz'):
        cues.import_wav(source, tmp_path, 'listening', 'test', 'test')
    assert (tmp_path/'voice-listening.pcm').read_bytes() == old


def test_committed_spoken_assets_match_manifest(tmp_path):
    cues.manifest(Path(__file__).parents[1]/'firmware/assets', tmp_path/'manifest.h')
    assert (tmp_path/'manifest.h').read_text() == (Path(__file__).parents[1]/'firmware/include/voice_static_cues_manifest.h').read_text()
