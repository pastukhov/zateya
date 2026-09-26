import pytest

from .config import LLMConfig, LLMConfigError


def test_config_requires_endpoint_and_model():
    with pytest.raises(LLMConfigError, match="LLM_BASE_URL"):
        LLMConfig.from_env({"LLM_MODEL": "small"})
    with pytest.raises(LLMConfigError, match="LLM_MODEL"):
        LLMConfig.from_env({"LLM_BASE_URL": "https://api.example/v1"})


def test_config_accepts_chat_completions_prefixes_and_optional_key():
    for url in ("https://api.openai.com/v1/", "https://openrouter.ai/api/v1", "http://127.0.0.1:11434/v1"):
        config = LLMConfig.from_env({"LLM_BASE_URL": url, "LLM_MODEL": "cheap"})
        assert config.base_url == url.rstrip("/")
        assert config.api_key == ""
        assert config.model == "cheap"
        assert config.response_format == "text"
        assert config.timeout_seconds == 120
        assert config.max_tokens == 8192
        assert config.history_turns == 6
        assert config.history_max_chars == 12000


@pytest.mark.parametrize("url", [
    "ftp://api.example/v1", "https://user:pass@api.example/v1",
    "https://api.example/v1?key=secret", "https://api.example/v1#frag",
    "https:///v1", "https://api.example:bad/v1",
])
def test_config_rejects_unsafe_or_malformed_urls(url):
    with pytest.raises(LLMConfigError):
        LLMConfig.from_env({"LLM_BASE_URL": url, "LLM_MODEL": "cheap"})


def test_config_rejects_invalid_modes_and_bounds():
    base = {"LLM_BASE_URL": "http://localhost:11434/v1", "LLM_MODEL": "qwen"}
    for key, value in (("LLM_RESPONSE_FORMAT", "tools"), ("LLM_TIMEOUT_SECONDS", "0"),
                       ("LLM_TIMEOUT_SECONDS", "121"), ("LLM_MAX_TOKENS", "0"),
                       ("LLM_HISTORY_TURNS", "-1"), ("LLM_HISTORY_MAX_CHARS", "0")):
        with pytest.raises(LLMConfigError):
            LLMConfig.from_env({**base, key: value})
    assert LLMConfig.from_env({**base, "LLM_RESPONSE_FORMAT": "json_object",
                              "LLM_HISTORY_TURNS": "0"}).response_format == "json_object"
