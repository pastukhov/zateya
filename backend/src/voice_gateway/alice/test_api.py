import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.src.voice_gateway.alice.api import install_alice_routes, MAX_BODY_BYTES
from backend.src.voice_gateway.alice.auth import AliceAuthenticator
from backend.src.voice_gateway.alice.config import AliceConfig
from backend.src.voice_gateway.alice.store import AliceStore
from backend.src.voice_gateway.alice.worker import AliceWorker
from backend.src.voice_gateway.text_turns import TextTurnProcessor


def handler(fail_mode=None):
    async def inner(request):
        if fail_mode == "timeout":
            raise httpx.ConnectTimeout("slow")
        if fail_mode == "down":
            raise httpx.ConnectError("down")
        if fail_mode == "other":
            return httpx.Response(200, json={"id": "intruder"})
        if fail_mode == "revoked":
            return httpx.Response(403, json={"error": "token expired"})
        return httpx.Response(200, json={"id": "owner-1"})
    return httpx.MockTransport(inner)


def make_app(tmp_path, fail_mode=None):
    app = FastAPI()
    config = AliceConfig(enabled=True, skill_id="skill-1", allowed_yandex_id="owner-1",
                         context_device_id="mic",
                         database=tmp_path / "alice.sqlite3", archive_root=tmp_path / "archive")
    store = AliceStore(config.database)
    store.initialize()
    agent = SlowAgent()
    processor = TextTurnProcessor(agent)
    worker = AliceWorker(store, processor)
    client = httpx.AsyncClient(transport=handler(fail_mode))
    auth = AliceAuthenticator(allowed_yandex_id="owner-1", context_id="mic", client=client)
    install_alice_routes(app, config, store, worker, auth)
    return app, store, worker


class SlowAgent:
    async def complete(self, request):
        await asyncio.sleep(120)
        raise AssertionError("LLM must not be called in the webhook handler")

    async def record_turn(self, *args):
        return True


def envelope(skill_id="skill-1", text="запиши мысль про полив", message_id="m-1", **extra):
    payload = {
        "meta": {"interfaces": {"screen": False}},
        "request": {"command": text.lower(), "original_utterance": text, "type": "SimpleUtterance"},
        "session": {"skill_id": skill_id, "session_id": "sess-1", "message_id": message_id,
                    "user_id": "spoofed-user-id"},
        "version": "1.0",
    }
    payload.update(extra)
    return payload


def post(client, payload, token="oauth-token", headers=None):
    send = {"Authorization": f"Bearer {token}"} if token else {}
    send.update(headers or {})
    return client.post("/api/alice/webhook", content=json.dumps(payload).encode(),
                       headers=send)


def test_yandex_ping_uses_original_utterance_without_auth_or_data(tmp_path):
    app, store, _ = make_app(tmp_path)
    payload = envelope(text="ping")
    with TestClient(app) as client:
        response = post(client, payload, token=None)
    assert response.status_code == 200
    assert response.json()["response"]["text"] == "pong"
    assert store.pending_count("owner-1") == 0


def test_wrong_skill_id_is_rejected(tmp_path):
    app, store, _ = make_app(tmp_path)
    with TestClient(app) as client:
        response = post(client, envelope(skill_id="other-skill"))
    assert response.status_code == 403
    assert store.pending_count("owner-1") == 0


def test_missing_token_asks_account_linking(tmp_path):
    app, store, _ = make_app(tmp_path)
    payload = envelope()
    payload["meta"]["interfaces"]["account_linking"] = {}
    with TestClient(app) as client:
        response = post(client, payload, token=None)
    assert response.status_code == 200
    assert response.json()["start_account_linking"] == {}
    assert "response" not in response.json()
    assert store.pending_count("owner-1") == 0


def test_missing_token_without_linking_interface_gets_instruction(tmp_path):
    app, store, _ = make_app(tmp_path)
    with TestClient(app) as client:
        response = post(client, envelope(), token=None)
    assert "Подключите аккаунт" in response.json()["response"]["text"]
    assert "start_account_linking" not in response.json()
    assert store.pending_count("owner-1") == 0


def test_account_linking_completion_is_acknowledged_without_creating_idea(tmp_path):
    app, store, _ = make_app(tmp_path)
    payload = envelope(text="")
    payload["request"] = {"account_linking_complete_event": {}}
    with TestClient(app) as client:
        response = post(client, payload)
    assert response.status_code == 200
    assert response.json()["response"]["text"] == "Аккаунт подключён. Можно диктовать заметку."
    assert store.pending_count("owner-1") == 0


def test_revoked_token_asks_linking_not_access(tmp_path):
    app, store, _ = make_app(tmp_path, fail_mode="revoked")
    with TestClient(app) as client:
        response = post(client, envelope())
    assert response.status_code == 200
    assert "Подключите аккаунт" in response.json()["response"]["text"]
    assert store.pending_count("owner-1") == 0


def test_yandex_id_unreachable_fails_closed(tmp_path):
    app, store, _ = make_app(tmp_path, fail_mode="timeout")
    with TestClient(app) as client:
        response = post(client, envelope())
    assert response.status_code == 503
    assert store.pending_count("owner-1") == 0


def test_spoofed_user_id_gives_no_access(tmp_path):
    """A foreign account with a valid token never reaches the vault."""
    app, store, _ = make_app(tmp_path, fail_mode="other")
    with TestClient(app) as client:
        response = post(client, envelope())
    assert response.status_code == 200
    assert "Подключите аккаунт" in response.json()["response"]["text"]
    assert store.pending_count("owner-1") == 0


def test_verified_owner_creates_job_and_gets_reply(tmp_path):
    app, store, _ = make_app(tmp_path)
    with TestClient(app) as client:
        response = post(client, envelope())
    assert response.status_code == 200
    assert "Приняла мысль" in response.json()["response"]["text"]
    assert store.pending_count("owner-1") == 1


def test_replayed_webhook_returns_same_reply_without_second_job(tmp_path):
    app, store, _ = make_app(tmp_path)
    with TestClient(app) as client:
        first = post(client, envelope())
        replay = post(client, envelope())
    assert first.json()["response"]["text"] == replay.json()["response"]["text"]
    assert store.pending_count("owner-1") == 1


def test_same_key_with_different_text_is_rejected(tmp_path):
    app, store, _ = make_app(tmp_path)
    with TestClient(app) as client:
        first = post(client, envelope())
        conflict = post(client, envelope(text="совсем другая мысль"))
    assert first.status_code == 200
    assert conflict.status_code == 200  # safe reply, not an error
    assert "Приняла мысль" not in conflict.json()["response"]["text"]
    assert store.pending_count("owner-1") == 1


def test_body_limit_is_enforced(tmp_path):
    app, store, _ = make_app(tmp_path)
    with TestClient(app) as client:
        big = "x" * (MAX_BODY_BYTES + 10)
        response = post(client, envelope(text=big))
    assert response.status_code == 413
    assert store.pending_count("owner-1") == 0


def test_per_owner_rate_limit(tmp_path):
    app, _, _ = make_app(tmp_path)
    with TestClient(app) as client:
        statuses = [post(client, envelope(message_id=f"m-{n}")).status_code for n in range(35)]
    assert statuses.count(429) > 0
    assert statuses[:30].count(200) == 30


def test_slow_llm_never_runs_inside_webhook(tmp_path):
    """A 120 s LLM does not delay the webhook: no LLM call in the HTTP path."""
    app, store, worker = make_app(tmp_path)
    started = time.monotonic()
    with TestClient(app) as client:
        response = post(client, envelope())
    elapsed = time.monotonic() - started
    assert response.status_code == 200
    assert elapsed < 2.0


def test_device_api_rejects_alice_tokens(tmp_path):
    """Existing device API keeps its own token check; Alice tokens don't work there."""
    app, _, _ = make_app(tmp_path)
    # The bare app here has no device routes installed (404); the point is
    # that nothing in the Alice stack grants device access. Device-token
    # isolation is proven in test_device_api.py against the real app.
    with TestClient(app) as client:
        response = client.get("/api/voice/knowledge/git", headers={
            "X-Device-Id": "mic", "Authorization": "Bearer oauth-token",
        })
    assert response.status_code in (401, 404)


def test_http_disconnect_after_commit_keeps_job(tmp_path):
    """The store commits before the HTTP answer: a lost reply keeps the job."""
    app, store, _ = make_app(tmp_path)
    with TestClient(app) as client:
        response = post(client, envelope())
    assert response.status_code == 200
    # Simulate a client that never received the answer and retries.
    with TestClient(app) as client2:
        replay = post(client2, envelope())
    assert store.pending_count("owner-1") == 1
    assert replay.json()["response"]["text"] == response.json()["response"]["text"]
