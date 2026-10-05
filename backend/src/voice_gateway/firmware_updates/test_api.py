import base64
import hashlib
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from backend.src.voice_gateway.app import create_app
from backend.src.voice_gateway.config import SecurityConfig


DEVICE = "001122334455"
TOKEN = "device-token"
HEADERS = {"X-Device-Id": DEVICE, "Authorization": f"Bearer {TOKEN}"}


def release_tree(root, seq=2):
    key = ec.generate_private_key(ec.SECP256R1())
    image = b"small signed firmware fixture"
    digest = hashlib.sha256(image).hexdigest()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    public_der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    manifest = {
        "schema": 1, "board": "sticks3", "layout": "ota-v1", "release_seq": seq,
        "git_revision": "a" * 40, "size": len(image), "sha256": digest,
        "image_path": f"/api/firmware/images/{digest}.bin",
        "key_id": hashlib.sha256(public_der).hexdigest()[:16],
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    signature = key.sign(raw, ec.ECDSA(hashes.SHA256()))
    envelope = {
        "manifest_b64": base64.b64encode(raw).decode(),
        "signature_b64": base64.b64encode(signature).decode(),
    }
    candidate = root / "releases" / str(seq)
    candidate.mkdir(parents=True)
    (candidate / "image.bin").write_bytes(image)
    (candidate / "envelope.json").write_text(json.dumps(envelope))
    (root / "trusted_public.pem").write_bytes(public)
    (root / "stable.json").write_text(json.dumps({"release_seq": seq, "sha256": digest}))
    return image, digest, candidate


def app_for(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_DEVICE_TOKENS", json.dumps({DEVICE: TOKEN}))
    root = tmp_path / "firmware"
    monkeypatch.setenv("FIRMWARE_RELEASE_ROOT", str(root))
    app = create_app(archive_root=tmp_path / "archive",
                     security=SecurityConfig(api_key="unrelated-global-token", auth_enabled=True))
    return TestClient(app), root


def test_firmware_is_private_and_only_explicit_stable_is_served(tmp_path, monkeypatch):
    client, root = app_for(tmp_path, monkeypatch)
    image, digest, _ = release_tree(root)
    with client:
        path = "/api/firmware/manifest?board=sticks3&layout=ota-v1&current_seq=0"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer wrong", "X-Device-Id": DEVICE}).status_code == 401
        response = client.get(path, headers=HEADERS)
        assert response.status_code == 200
        assert "signature_b64" in response.json()
        assert client.get(path.replace("current_seq=0", "current_seq=2"), headers=HEADERS).status_code == 204
        assert client.get(path.replace("board=sticks3", "board=other"), headers=HEADERS).status_code == 204
        assert client.get(f"/api/firmware/images/{digest}.bin").status_code == 401
        image_response = client.get(f"/api/firmware/images/{digest}.bin", headers=HEADERS)
        assert image_response.status_code == 200
        assert image_response.content == image
        assert image_response.headers["etag"] == digest
        assert image_response.headers["content-length"] == str(len(image))
        assert client.get(f"/api/firmware/images/{'0' * 64}.bin", headers=HEADERS).status_code == 404


def test_corrupt_or_unpublished_release_never_reaches_device(tmp_path, monkeypatch):
    client, root = app_for(tmp_path, monkeypatch)
    image, digest, candidate = release_tree(root)
    with client:
        path = "/api/firmware/manifest?board=sticks3&layout=ota-v1&current_seq=0"
        (root / "stable.json").unlink()
        assert client.get(path, headers=HEADERS).status_code == 204
        (root / "stable.json").write_text(json.dumps({"release_seq": 2, "sha256": digest}))
        (candidate / "image.bin").write_bytes(image + b"tampered")
        assert client.get(path, headers=HEADERS).status_code == 204
        assert client.get(f"/api/firmware/images/{digest}.bin", headers=HEADERS).status_code == 404
        (candidate / "image.bin").write_bytes(image)
        (root / "trusted_public.pem").write_text("wrong key")
        assert client.get(path, headers=HEADERS).status_code == 204
