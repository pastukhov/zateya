from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.src.voice_gateway.models import TTSResult


class TestTTSResult:
    def test_create_with_wav_path_and_sample_rate(self):
        """TTSResult stores exact wav_path and sample_rate values."""
        result = TTSResult(wav_path=Path("out/tts.wav"), sample_rate=16000)
        assert result.wav_path == Path("out/tts.wav")
        assert result.sample_rate == 16000

    def test_serialization_roundtrip_preserves_values(self):
        """model_dump/model_validate round-trip preserves both values."""
        result = TTSResult(wav_path=Path("out/tts.wav"), sample_rate=22050)
        dumped = result.model_dump()
        restored = TTSResult.model_validate(dumped)
        assert restored == result
        assert restored.wav_path == Path("out/tts.wav")
        assert restored.sample_rate == 22050

    def test_missing_wav_path_is_validation_error(self):
        """Omitting the required wav_path field raises a validation error."""
        with pytest.raises(ValidationError):
            TTSResult(sample_rate=16000)

    def test_missing_sample_rate_is_validation_error(self):
        """Omitting the required sample_rate field raises a validation error."""
        with pytest.raises(ValidationError):
            TTSResult(wav_path=Path("out/tts.wav"))

    def test_non_conforming_values_are_rejected(self):
        """Non-Path wav_path and non-int sample_rate are rejected."""
        with pytest.raises(ValidationError):
            TTSResult(wav_path=123, sample_rate=16000)
        with pytest.raises(ValidationError):
            TTSResult(wav_path=Path("out/tts.wav"), sample_rate="not-a-rate")


def test_audio_result_accepts_format_neutral_path():
    result=TTSResult(audio_path=Path('reply.part'),codec='mp3',media_type='audio/mpeg',sample_rate=44100)
    assert result.audio_path==Path('reply.part') and result.wav_path==result.audio_path
