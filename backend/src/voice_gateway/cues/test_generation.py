from dataclasses import replace
from pathlib import Path

import pytest

from backend.src.voice_gateway.cues.cache import CUE_TEXTS
from backend.src.voice_gateway.cues.generation import MP3CueGenerations, UnknownCueGeneration
from backend.src.voice_gateway.cues.mp3_decode import validate_mp3
from backend.src.voice_gateway.tts.config import TTSConfig

FIXTURE = Path(__file__).parent / 'fixtures' / 'talia.mp3'
CONFIG = TTSConfig('https://example.test/audio/speech', 'eleven-flash', voice='talia',
                   response_format='mp3', api_key='never-persist-this')


class Provider:
    def __init__(self, config=CONFIG):
        self.config = config
        self.calls = []
        self.fail_at = None

    def synthesize(self, text, path):
        self.calls.append(text)
        if len(self.calls) == self.fail_at:
            raise RuntimeError('not persisted')
        path.write_bytes(FIXTURE.read_bytes())


def test_all_fourteen_decode_and_restart_without_calls(tmp_path):
    provider = Provider()
    cache = MP3CueGenerations(tmp_path, provider, CONFIG)
    assert cache.manifest() is None
    assert cache.ensure_all()
    assert provider.calls == list(CUE_TEXTS.values())
    manifest = cache.manifest()
    assert set(manifest['items']) == set(CUE_TEXTS)
    assert all(item['duration_ms'] > 0 for item in manifest['items'].values())
    fresh = Provider()
    restarted = MP3CueGenerations(tmp_path, fresh, CONFIG)
    assert restarted.ensure_all()
    assert fresh.calls == []
    assert restarted.audio(manifest['generation_id'], 'listening') == FIXTURE.read_bytes()
    assert 'never-persist-this' not in (tmp_path / cache.generation_id / 'profile.json').read_text()


@pytest.mark.parametrize('field,value', [('model', 'new-model'), ('voice', 'new-voice'),
                                       ('instructions', 'gentle'), ('base_url', 'https://new.test/speech')])
def test_setting_changes_regenerate_every_cue_and_pin_old_profile(tmp_path, field, value):
    old = MP3CueGenerations(tmp_path, Provider(), CONFIG)
    assert old.ensure_all()
    config = replace(CONFIG, **{field: value})
    provider = Provider(config)
    new = MP3CueGenerations(tmp_path, provider, config)
    assert new.manifest()['generation_id'] == old.generation_id
    assert new.ensure_all()
    assert len(provider.calls) == 14
    assert new.generation_id != old.generation_id
    pinned = new.resolve_mp3_profile(old.generation_id)
    assert pinned.config == CONFIG
    assert new.resolve_mp3_profile(new.generation_id) is provider


def test_text_changes_all_and_secret_does_not_change_identity(tmp_path):
    first = MP3CueGenerations(tmp_path, Provider(), CONFIG)
    assert first.ensure_all()
    same = MP3CueGenerations(tmp_path, Provider(), replace(CONFIG, api_key='rotated'))
    assert same.generation_id == first.generation_id
    changed = dict(CUE_TEXTS, listening='Да, слушаю.')
    provider = Provider()
    second = MP3CueGenerations(tmp_path, provider, CONFIG, texts=changed)
    assert second.ensure_all()
    assert len(provider.calls) == 14
    assert first.generation_id != second.generation_id


def test_failure_keeps_old_complete_generation_and_restart_backoff(tmp_path):
    old = MP3CueGenerations(tmp_path, Provider(), CONFIG)
    assert old.ensure_all()
    now = [1000]
    provider = Provider()
    provider.fail_at = 7
    config = replace(CONFIG, voice='changed')
    cache = MP3CueGenerations(tmp_path, provider, config, clock=lambda: now[0])
    assert not cache.ensure_all()
    assert len(provider.calls) == 7
    assert cache.manifest()['generation_id'] == old.generation_id
    assert cache.status()['status'] == 'error'
    assert not (tmp_path / cache.generation_id).exists()
    assert not cache.ensure_all()
    restarted = MP3CueGenerations(tmp_path, provider, config, clock=lambda: now[0])
    assert not restarted.ensure_all()
    assert len(provider.calls) == 7
    now[0] += 60
    assert restarted.ensure_all()
    assert len(provider.calls) == 15


def test_corrupt_persistent_audio_requires_regeneration(tmp_path):
    cache = MP3CueGenerations(tmp_path, Provider(), CONFIG)
    assert cache.ensure_all()
    (tmp_path / cache.generation_id / 'done.mp3').write_bytes(b'bad')
    provider = Provider()
    restarted = MP3CueGenerations(tmp_path, provider, CONFIG)
    assert restarted.manifest() is None
    assert restarted.ensure_all()
    assert len(provider.calls) == 14


def test_bounded_history_unknown_is_explicit(tmp_path):
    caches = []
    for voice in ('one', 'two', 'three', 'four'):
        cache = MP3CueGenerations(tmp_path, Provider(), replace(CONFIG, voice=voice), retained=2)
        assert cache.ensure_all()
        caches.append(cache)
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 2
    with pytest.raises(UnknownCueGeneration, match='cue_generation_update_required'):
        caches[-1].resolve_mp3_profile(caches[0].generation_id)
    assert caches[-1].resolve_mp3_profile(caches[-2].generation_id).config.voice == 'three'


def test_crash_after_directory_publication_reuses_without_tts(tmp_path):
    first = MP3CueGenerations(tmp_path, Provider(), CONFIG)
    assert first.ensure_all()
    (tmp_path / 'active.json').unlink()
    provider = Provider()
    second = MP3CueGenerations(tmp_path, provider, CONFIG)
    assert second.manifest() is None
    assert second.ensure_all()
    assert not provider.calls


def test_real_decode_rejects_truncation_and_wrong_profile():
    assert validate_mp3(FIXTURE.read_bytes())['sample_rate'] == 44100
    with pytest.raises(Exception):
        validate_mp3(FIXTURE.read_bytes()[:-1])
    with pytest.raises(ValueError):
        validate_mp3(b'x' * 160001)


def test_failed_attempts_are_hard_bounded_and_persisted(tmp_path):
    class Broken(Provider):
        def synthesize(self, text, path):
            self.calls.append(text)
            raise RuntimeError('failure')
    now = [1000]
    provider = Broken()
    cache = MP3CueGenerations(tmp_path, provider, CONFIG, clock=lambda: now[0])
    for _ in range(10):
        assert not cache.ensure_all()
        now[0] += 3601
    assert len(provider.calls) == 5
    assert cache.status()['status'] == 'exhausted'
    cache = MP3CueGenerations(tmp_path, provider, CONFIG, clock=lambda: now[0])
    assert not cache.ensure_all()
    assert len(provider.calls) == 5


def test_publication_failure_keeps_pointer_then_recovers_without_paid_calls(tmp_path, monkeypatch):
    import backend.src.voice_gateway.cues.generation as module
    old = MP3CueGenerations(tmp_path, Provider(), CONFIG)
    assert old.ensure_all()
    config = replace(CONFIG, voice='new')
    provider = Provider()
    now = [1000]
    new = MP3CueGenerations(tmp_path, provider, config, clock=lambda: now[0])
    atomic = module._atomic_cache_bytes

    def interrupted(path, data):
        if path.name == 'active.json':
            raise OSError('power interruption')
        return atomic(path, data)

    monkeypatch.setattr(module, '_atomic_cache_bytes', interrupted)
    assert not new.ensure_all()
    assert new.manifest()['generation_id'] == old.generation_id
    assert len(provider.calls) == 14
    monkeypatch.setattr(module, '_atomic_cache_bytes', atomic)
    now[0] += 61
    fresh = Provider()
    restarted = MP3CueGenerations(tmp_path, fresh, config, clock=lambda: now[0])
    assert restarted.ensure_all()
    assert not fresh.calls
    assert restarted.manifest()['generation_id'] == new.generation_id


def test_process_death_consumes_durable_attempt_and_backoff(tmp_path):
    class Dies(Provider):
        def synthesize(self, text, path):
            self.calls.append(text)
            raise KeyboardInterrupt('simulated process death')
    now = [1000]
    provider = Dies()
    for attempt in range(5):
        cache = MP3CueGenerations(tmp_path, provider, CONFIG, clock=lambda: now[0])
        with pytest.raises(KeyboardInterrupt):
            cache.ensure_all()
        restart = MP3CueGenerations(tmp_path, provider, CONFIG, clock=lambda: now[0])
        assert not restart.ensure_all()
        assert len(provider.calls) == attempt + 1
        now[0] += 3601
    final = MP3CueGenerations(tmp_path, provider, CONFIG, clock=lambda: now[0])
    assert final.status()['status'] == 'exhausted'
    assert not final.ensure_all()
    assert len(provider.calls) == 5


def test_strict_decode_rejects_payload_errors_concealed_by_mpg123():
    from backend.src.voice_gateway.tts.mp3 import MP3Parser
    data = bytearray(FIXTURE.read_bytes())
    parser = MP3Parser()
    parser.feed(data)
    parser.finish()
    offset = parser.metadata_bytes
    frame = 0
    while offset < len(data):
        length = 144 * 128000 // 44100 + ((data[offset + 2] >> 1) & 1)
        if frame >= 4:
            data[offset + 4:offset + length] = b'\xff' * (length - 4)
        frame += 1
        offset += length
    with pytest.raises(ValueError, match='payload decode failed'):
        validate_mp3(bytes(data))
