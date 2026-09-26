"""Production provider wiring uses one direct OpenAI-compatible LLM."""
from backend.src.voice_gateway.agents.openai_client import OpenAICompatibleAgentClient
from backend.src.voice_gateway.agents.sessions import AgentSessionStore
from backend.src.voice_gateway.app import create_app
from backend.src.voice_gateway.stt.client import OpenAICompatibleSTT
from backend.src.voice_gateway.tts.openai_compatible import OpenAICompatibleTTS


def test_create_app_builds_configured_runtime_providers(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8642/api/v1/")
    monkeypatch.setenv("LLM_API_KEY", "llm-test-key")
    monkeypatch.setenv("LLM_MODEL", "small-model")
    monkeypatch.setenv("LLM_RESPONSE_FORMAT", "json_object")
    monkeypatch.setenv("STT_API_KEY", "stt-test-key")
    monkeypatch.setenv("STT_MODEL", "transcribe-small")
    monkeypatch.setenv("TTS_API_KEY", "tts-test-key")
    monkeypatch.setenv("TTS_MODEL", "speak-small")
    monkeypatch.setenv("TTS_VOICE", "alloy")

    app = create_app(archive_root=tmp_path / "archive")

    assert isinstance(app.state.stt_provider, OpenAICompatibleSTT)
    assert isinstance(app.state.agent_client, OpenAICompatibleAgentClient)
    assert isinstance(app.state.agent_client.sessions, AgentSessionStore)
    assert app.state.agent_client.config.base_url == "http://127.0.0.1:8642/api/v1"
    assert app.state.agent_client.config.api_key == "llm-test-key"
    assert app.state.agent_client.config.model == "small-model"
    assert app.state.stt_provider._config.transcriptions_url == "http://127.0.0.1:8642/api/v1/audio/transcriptions"
    assert isinstance(app.state.tts_provider, OpenAICompatibleTTS)
    assert app.state.tts_provider._config.base_url == "http://127.0.0.1:8642/api/v1/audio/speech"
    assert app.state.agent_provider == "openai_compatible"


def test_old_provider_switches_are_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICE_AGENT_PROVIDER", "codex")
    monkeypatch.setenv("CODEX_AGENT_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("CODEX_AGENT_TOKEN", "test-only")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    app = create_app(archive_root=tmp_path / "archive")
    assert app.state.agent_client is None
    assert app.state.hermes_client is None
    assert app.state.agent_provider == "openai_compatible"


def test_injected_agent_remains_a_test_seam(monkeypatch, tmp_path):
    class FakeAgent:
        async def complete(self, request):
            raise AssertionError("not used")

    app = create_app(archive_root=tmp_path / "archive", agent=FakeAgent())
    assert app.state.agent_client is not None
    assert app.state.agent_provider == "injected"
