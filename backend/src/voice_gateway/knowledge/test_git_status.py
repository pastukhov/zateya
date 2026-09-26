import json

from fastapi.testclient import TestClient

from backend.src.voice_gateway.app import create_app
from backend.src.voice_gateway.config import SecurityConfig


class FakeAgent:
    async def complete(self, request):
        raise AssertionError("not used")

    async def cancel(self, request_id):
        pass


def test_git_status_is_device_authenticated_and_compact(tmp_path, monkeypatch):
    device = "001122334455"
    monkeypatch.setenv("VOICE_DEVICE_TOKENS", json.dumps({device: "test-token"}))
    monkeypatch.setenv("VOICE_KNOWLEDGE_ENABLED", "true")
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    app = create_app(archive_root=tmp_path / "archive", agent=FakeAgent(),
                     security=SecurityConfig(api_key="", auth_enabled=False))
    with TestClient(app) as client:
        assert client.get("/api/voice/knowledge/git", headers={"X-Device-Id": device}).status_code == 401
        response = client.get("/api/voice/knowledge/git", headers={
            "X-Device-Id": device, "Authorization": "Bearer test-token",
        })
    assert response.status_code == 200
    assert response.json() == {"status": "idle", "commit": None, "updates": 0}
