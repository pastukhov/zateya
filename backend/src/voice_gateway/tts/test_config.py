"""Tests for TTS config loading from environment (ТЗ sections 31, 33).

No dependence on ``os.environ`` — every test passes an explicit mapping.
"""
import pytest

from backend.src.voice_gateway.tts.config import DEFAULT_TTS_TIMEOUT, TTSConfig


class TestTTSConfigFromEnv:
    def test_uses_llm_base_url(self):
        config = TTSConfig.from_env({
            "LLM_BASE_URL": "https://provider.example/api/v1/",
            "TTS_MODEL": "voice-model",
        })
        assert config.base_url == "https://provider.example/api/v1/audio/speech"

    def test_all_values_from_env(self):
        config = TTSConfig.from_env(
            {
                "LLM_BASE_URL": "https://tts.local/v1",
                "LLM_API_KEY": "sekret",
                "TTS_MODEL": "tts-1",
                "TTS_VOICE": "alloy",
                "TTS_TIMEOUT": "30.5",
            }
        )
        assert config.base_url == "https://tts.local/v1/audio/speech"
        assert config.api_key == "sekret"
        assert config.model == "tts-1"
        assert config.voice == "alloy"
        assert config.timeout == 30.5

    def test_defaults_for_timeout_and_api_key(self):
        config = TTSConfig.from_env(
            {
                "LLM_BASE_URL": "https://tts.local/v1",
                "TTS_MODEL": "m",
                "TTS_VOICE": "v",
            }
        )
        assert config.timeout == DEFAULT_TTS_TIMEOUT == 60.0
        assert config.api_key == ""

    def test_missing_env_defaults_to_empty_mapping(self):
        with pytest.raises(ValueError, match="LLM_BASE_URL"):
            TTSConfig.from_env(None)

    def test_missing_base_url_raises(self):
        with pytest.raises(ValueError, match="LLM_BASE_URL"):
            TTSConfig.from_env({"TTS_MODEL": "m", "TTS_VOICE": "v"})

    def test_whitespace_only_base_url_raises(self):
        with pytest.raises(ValueError, match="LLM_BASE_URL"):
            TTSConfig.from_env(
                {"LLM_BASE_URL": "   ", "TTS_MODEL": "m", "TTS_VOICE": "v"}
            )

    def test_missing_model_raises(self):
        with pytest.raises(ValueError, match="TTS_MODEL"):
            TTSConfig.from_env({"LLM_BASE_URL": "https://tts.local/v1"})

    def test_whitespace_only_model_raises(self):
        with pytest.raises(ValueError, match="TTS_MODEL"):
            TTSConfig.from_env(
                {"LLM_BASE_URL": "https://tts.local/v1", "TTS_MODEL": "   "}
            )

    def test_invalid_timeout_raises(self):
        env = {
            "LLM_BASE_URL": "https://tts.local/v1",
            "TTS_MODEL": "m",
            "TTS_TIMEOUT": "not-a-number",
        }
        with pytest.raises(ValueError, match="TTS_TIMEOUT"):
            TTSConfig.from_env(env)

    def test_zero_timeout_raises(self):
        env = {
            "LLM_BASE_URL": "https://tts.local/v1",
            "TTS_MODEL": "m",
            "TTS_TIMEOUT": "0",
        }
        with pytest.raises(ValueError, match="positive"):
            TTSConfig.from_env(env)

    def test_negative_timeout_raises(self):
        env = {
            "LLM_BASE_URL": "https://tts.local/v1",
            "TTS_MODEL": "m",
            "TTS_TIMEOUT": "-1",
        }
        with pytest.raises(ValueError, match="positive"):
            TTSConfig.from_env(env)

    def test_from_env_is_frozen(self):
        config = TTSConfig.from_env(
            {"LLM_BASE_URL": "https://tts.local/v1", "TTS_MODEL": "m"}
        )
        with pytest.raises(AttributeError):
            config.model = "other"  # pyright: ignore[reportAttributeAccessIssue]


def test_language_defaults_empty_and_keeps_positional_compatibility():
    config = TTSConfig("https://tts.test/speech", "m", "v", "style", "key", 30, "mp3")
    assert config.response_format == "mp3"
    assert config.language_code == ""
    assert TTSConfig.from_env({"LLM_BASE_URL": "https://tts.test", "TTS_MODEL": "m"}).language_code == ""


@pytest.mark.parametrize("value,expected", [(" RU ", "ru"), ("en", "en"), ("  ", "")])
def test_language_is_normalized_in_environment_and_direct_profiles(value, expected):
    env = {"LLM_BASE_URL": "https://tts.test", "TTS_MODEL": "elevenlabs/eleven-flash-v2.5",
           "TTS_LANGUAGE_CODE": value}
    assert TTSConfig.from_env(env).language_code == expected
    assert TTSConfig("https://tts.test/speech", env["TTS_MODEL"], language_code=value).language_code == expected


@pytest.mark.parametrize("value", ["rus", "ru-RU", "r", "12", "рф", "r u", "ru\nxx"])
def test_invalid_language_codes_fail_without_echoing_value(value):
    with pytest.raises(ValueError, match="TTS_LANGUAGE_CODE"):
        TTSConfig.from_env({"LLM_BASE_URL": "https://tts.test", "TTS_MODEL": "elevenlabs/model",
                            "TTS_LANGUAGE_CODE": value})


def test_language_rejects_unsupported_provider_model():
    with pytest.raises(ValueError, match="ElevenLabs"):
        TTSConfig("https://tts.test/speech", "other/model", language_code="ru")


def test_mp3_language_never_inherits_legacy_and_does_not_change_legacy_profile():
    env = {"LLM_BASE_URL": "https://tts.test", "TTS_MODEL": "elevenlabs/legacy",
           "TTS_LANGUAGE_CODE": "en", "TTS_VOICE": "legacy-voice", "MP3_TTS_MODEL": "other/mp3",
           "MP3_TTS_VOICE": "mp3-voice"}
    legacy = TTSConfig.from_env(env)
    mp3 = TTSConfig.mp3_from_env(env)
    assert legacy.language_code == "en" and legacy.response_format == "wav"
    assert mp3.language_code == "" and mp3.response_format == "mp3"
    env.update(MP3_TTS_MODEL="elevenlabs/eleven-flash-v2.5", MP3_TTS_LANGUAGE_CODE=" RU ")
    assert TTSConfig.mp3_from_env(env).language_code == "ru"
    assert TTSConfig.from_env(env) == legacy
