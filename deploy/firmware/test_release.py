import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


SOURCE = Path(__file__).with_name("build-release.py")
SPEC = importlib.util.spec_from_file_location("zateya_build_release", SOURCE)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


def test_signed_envelope_rejects_modified_image_manifest_and_key():
    key = signing_key()
    image = b"firmware image bytes"
    envelope = release.make_envelope(image, 5, "a" * 40, key)
    manifest = release.verify_envelope(envelope, image, key.public_key())
    assert manifest["release_seq"] == 5
    assert manifest["size"] == len(image)
    with pytest.raises(ValueError):
        release.verify_envelope(envelope, image + b"changed", key.public_key())
    with pytest.raises(ValueError):
        release.verify_envelope(envelope, image, signing_key().public_key())
    tampered = dict(envelope)
    tampered["manifest_b64"] = envelope["manifest_b64"][:-4] + "AAAA"
    with pytest.raises(ValueError):
        release.verify_envelope(tampered, image, key.public_key())
    with pytest.raises(ValueError):
        release.make_envelope(image, 6, "not-a-git-revision", key)
    with pytest.raises(ValueError):
        release.make_envelope(b"", 6, "a" * 40, key)
    with pytest.raises(ValueError):
        release.make_envelope(image, 0x100000000, "a" * 40, key)


def test_publish_is_explicit_atomic_and_cannot_change_existing_sequence(tmp_path):
    key = signing_key()
    signing = tmp_path / "signing"
    signing.mkdir()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    (signing / "ota-p256-public.pem").write_bytes(public)
    root = tmp_path / "firmware"
    candidate = root / "releases" / "5"
    candidate.mkdir(parents=True)
    image = b"firmware image bytes"
    (candidate / "image.bin").write_bytes(image)
    (candidate / "envelope.json").write_text(json.dumps(
        release.make_envelope(image, 5, "a" * 40, key)
    ))
    (root / "trusted_public.pem").write_bytes(public)
    assert not (root / "stable.json").exists()
    first = release.publish(root, signing, 5)
    assert first["release_seq"] == 5
    assert release.publish(root, signing, 5) == first
    (candidate / "image.bin").write_bytes(b"changed")
    with pytest.raises(ValueError):
        release.publish(root, signing, 5)
    assert json.loads((root / "stable.json").read_text()) == first


def test_publish_refuses_different_trusted_key(tmp_path):
    key = signing_key()
    signing = tmp_path / "signing"
    signing.mkdir()
    signing_public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    (signing / "ota-p256-public.pem").write_bytes(signing_public)
    root = tmp_path / "firmware"
    candidate = root / "releases" / "1"
    candidate.mkdir(parents=True)
    image = b"test image"
    (candidate / "image.bin").write_bytes(image)
    (candidate / "envelope.json").write_text(json.dumps(
        release.make_envelope(image, 1, "b" * 40, key)
    ))
    other = signing_key().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    (root / "trusted_public.pem").write_bytes(other)
    with pytest.raises(ValueError, match="trusted release key"):
        release.publish(root, signing, 1)
    assert not (root / "stable.json").exists()


def test_generated_trust_header_contains_only_public_key(tmp_path):
    key = signing_key()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (tmp_path / "include").mkdir()
    release.write_trust_header(tmp_path, public, 11)
    header = (tmp_path / "include" / "voice_ota_release.h").read_bytes()
    assert b"VOICE_OTA_RELEASE_SEQ 11u" in header
    assert b"BEGIN PUBLIC KEY" in header
    assert private not in header
    assert b"BEGIN PRIVATE KEY" not in header


def test_builder_rejects_mismatched_key_pair_before_compiling(tmp_path):
    private_key = signing_key()
    other_public = signing_key().public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signing = tmp_path / "signing"
    signing.mkdir()
    (signing / "ota-p256.pem").write_bytes(private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    (signing / "ota-p256-public.pem").write_bytes(other_public)
    with pytest.raises(ValueError, match="key pair"):
        release.build_candidate(tmp_path / "unbuilt-firmware", tmp_path / "releases",
                                signing, 1, "a" * 40)
    assert not (tmp_path / "releases").exists()
