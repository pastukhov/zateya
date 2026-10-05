import json

from fastapi.testclient import TestClient

from backend.src.voice_gateway.app import create_app
from backend.src.voice_gateway.config import SecurityConfig


DEVICE = "001122334455"
TOKEN = "private-device-token"
PATH = "/api/devices/diagnostics"


def report(boot=10, sequence=1):
    return {
        "boot_id": boot, "sequence": sequence, "uptime_ms": 5000,
        "reset_reason": 1, "firmware_revision": "Oct 05 2026 12:00:00",
        "wifi_connected": True, "wg_status": "connected",
        "backend_status": 200, "free_heap_bytes": 200000,
        "recording": {
            "recording_id": 1, "captured_bytes": 32000, "queued_bytes": 32000,
            "sent_bytes": 21000, "ring_high_water_bytes": 11000,
            "upload_high_water_bytes": 8192, "write_max_ms": 5000,
            "last_error_code": 4, "events": [[5000, 4, 1024, 5000]],
        },
    }


def client_for(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_DEVICE_TOKENS", json.dumps({DEVICE: TOKEN}))
    app = create_app(archive_root=tmp_path / "archive",
                     security=SecurityConfig(api_key="different-global-key", auth_enabled=True))
    return TestClient(app), app


def headers(token=TOKEN, device=DEVICE):
    return {"Authorization": f"Bearer {token}", "X-Device-Id": device}


def test_authenticated_report_is_idempotent_and_retained(tmp_path, monkeypatch):
    client, app = client_for(tmp_path, monkeypatch)
    with client:
        assert client.post(PATH, json=report(), headers=headers()).status_code == 202
        assert client.post(PATH, json=report(), headers=headers()).status_code == 202
        changed = report()
        changed["recording"]["sent_bytes"] += 1
        assert client.post(PATH, json=changed, headers=headers()).status_code == 409
        for sequence in range(2, 24):
            assert client.post(PATH, json=report(sequence=sequence), headers=headers()).status_code == 202
    assert app.state.diagnostics_store.count(DEVICE) == 20


def test_rejects_foreign_device_oversize_and_secret_fields(tmp_path, monkeypatch):
    client, app = client_for(tmp_path, monkeypatch)
    with client:
        for auth in [headers(token="wrong"), headers(device="other"), {}]:
            assert client.post(PATH, json=report(), headers=auth).status_code == 401
        assert client.post(PATH, content=b"x" * 16385, headers=headers()).status_code == 413
        bad = report()
        bad["token"] = "do-not-store-or-log"
        assert client.post(PATH, json=bad, headers=headers()).status_code == 400
        bad = report()
        bad["recording"]["events"] = [[1, 4, 0, 0]] * 65
        assert client.post(PATH, json=bad, headers=headers()).status_code == 400
    assert app.state.diagnostics_store.count(DEVICE) == 0
