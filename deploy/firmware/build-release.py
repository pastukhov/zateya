#!/usr/bin/env python3
"""Build a signed OTA candidate; publish to stable only by an explicit command."""

from __future__ import annotations

import argparse
import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec


SLOT_BYTES = 0x300000
BOARD = "sticks3"
LAYOUT = "ota-v1"


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def key_id(public_key) -> str:
    encoded = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(encoded).hexdigest()[:16]


def make_envelope(image: bytes, release_seq: int, revision: str, private_key) -> dict:
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(
        private_key.curve, ec.SECP256R1
    ):
        raise ValueError("OTA signing key must be ECDSA P-256")
    if (type(release_seq) is not int or not 0 < release_seq <= 0xFFFFFFFF or
            not re.fullmatch(r"[0-9a-f]{40}", revision) or
            not image or len(image) > SLOT_BYTES):
        raise ValueError("invalid release sequence, revision, or image size")
    digest = hashlib.sha256(image).hexdigest()
    manifest = {
        "schema": 1, "board": BOARD, "layout": LAYOUT,
        "release_seq": release_seq, "git_revision": revision,
        "size": len(image), "sha256": digest,
        "image_path": f"/api/firmware/images/{digest}.bin",
        "key_id": key_id(private_key.public_key()),
    }
    manifest_bytes = canonical(manifest)
    signature = private_key.sign(manifest_bytes, ec.ECDSA(hashes.SHA256()))
    return {
        "manifest_b64": base64.b64encode(manifest_bytes).decode("ascii"),
        "signature_b64": base64.b64encode(signature).decode("ascii"),
    }


def verify_envelope(envelope: dict, image: bytes, public_key) -> dict:
    try:
        manifest_bytes = base64.b64decode(envelope["manifest_b64"], validate=True)
        signature = base64.b64decode(envelope["signature_b64"], validate=True)
        public_key.verify(signature, manifest_bytes, ec.ECDSA(hashes.SHA256()))
        manifest = json.loads(manifest_bytes)
    except (KeyError, TypeError, ValueError, binascii.Error, InvalidSignature) as exc:
        # The CLI must not print the envelope or secret key on failure.
        raise ValueError("invalid signed OTA envelope") from exc
    if not isinstance(manifest, dict):
        raise ValueError("OTA manifest must be an object")
    digest = hashlib.sha256(image).hexdigest()
    expected = {
        "schema": 1, "board": BOARD, "layout": LAYOUT,
        "release_seq": manifest.get("release_seq"),
        "git_revision": manifest.get("git_revision"),
        "size": len(image), "sha256": digest,
        "image_path": f"/api/firmware/images/{digest}.bin",
        "key_id": key_id(public_key),
    }
    if (manifest != expected or type(manifest["release_seq"]) is not int or
            manifest["release_seq"] <= 0 or
            not isinstance(manifest["git_revision"], str) or
            not re.fullmatch(r"[0-9a-f]{40}", manifest["git_revision"]) or
            not image or len(image) > SLOT_BYTES):
        raise ValueError("OTA manifest does not match the image or target")
    return manifest


@contextmanager
def release_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".publish.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def load_private(path: Path):
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def prepare_ota_build(firmware: Path) -> None:
    shutil.copyfile(firmware / "partitions.ota.csv", firmware / "partitions.csv")
    defaults = firmware / "sdkconfig.defaults"
    contents = defaults.read_text()
    if "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y" not in contents:
        defaults.write_text(contents + "\nCONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y\n")
    (firmware / "sdkconfig.sticks3").unlink(missing_ok=True)


def write_trust_header(firmware: Path, public_pem: bytes, release_seq: int) -> None:
    if not 0 < release_seq <= 0xFFFFFFFF or not public_pem.startswith(b"-----BEGIN PUBLIC KEY-----"):
        raise ValueError("invalid OTA trust anchor")
    pem = public_pem.decode("ascii")
    header = (
        "#ifndef VOICE_OTA_RELEASE_H\n#define VOICE_OTA_RELEASE_H\n"
        f"#define VOICE_OTA_RELEASE_SEQ {release_seq}u\n"
        f"#define VOICE_OTA_PUBLIC_KEY_PEM {json.dumps(pem)}\n"
        f"#define VOICE_OTA_KEY_ID {json.dumps(key_id(serialization.load_pem_public_key(public_pem)))}\n"
        "#endif\n"
    )
    (firmware / "include" / "voice_ota_release.h").write_text(header)


def build_candidate(firmware: Path, root: Path, signing: Path,
                    release_seq: int, revision: str) -> Path:
    if not 0 < release_seq <= 0xFFFFFFFF or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("invalid release sequence or git revision")
    private_key = load_private(signing / "ota-p256.pem")
    public_pem = (signing / "ota-p256-public.pem").read_bytes()
    public_key = serialization.load_pem_public_key(public_pem)
    if (not isinstance(private_key, ec.EllipticCurvePrivateKey) or
            not isinstance(private_key.curve, ec.SECP256R1) or
            private_key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ) != public_key.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )):
        raise ValueError("OTA signing key pair does not match")
    prepare_ota_build(firmware)
    write_trust_header(firmware, public_pem, release_seq)
    subprocess.run(["pio", "run", "-e", "sticks3"], cwd=firmware, check=True)
    sdkconfig = (firmware / "sdkconfig.sticks3").read_text()
    if "CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y" not in sdkconfig:
        raise ValueError("candidate build lacks bootloader rollback")
    build_dir = firmware / ".pio/build/sticks3"
    image = (build_dir / "firmware.bin").read_bytes()
    envelope = make_envelope(image, release_seq, revision, private_key)
    verify_envelope(envelope, image, public_key)
    releases = root / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".candidate-", dir=releases))
    try:
        (temporary / "image.bin").write_bytes(image)
        (temporary / "envelope.json").write_bytes(canonical(envelope))
        for name in ("bootloader.bin", "partitions.bin", "ota_data_initial.bin"):
            shutil.copyfile(build_dir / name, temporary / name)
        with release_lock(root):
            trusted_public = root / "trusted_public.pem"
            if trusted_public.exists() and trusted_public.read_bytes() != public_pem:
                raise ValueError("signing key differs from previous releases")
            if not trusted_public.exists():
                trusted_public.write_bytes(public_pem)
            target = releases / str(release_seq)
            if target.exists():
                raise ValueError("release sequence already exists")
            temporary.rename(target)
        return target
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def publish(root: Path, signing: Path, release_seq: int) -> dict:
    with release_lock(root):
        trusted_public = (root / "trusted_public.pem").read_bytes()
        signing_public = (signing / "ota-p256-public.pem").read_bytes()
        if trusted_public != signing_public:
            raise ValueError("publication key differs from the trusted release key")
        candidate = root / "releases" / str(release_seq)
        image = (candidate / "image.bin").read_bytes()
        envelope = json.loads((candidate / "envelope.json").read_bytes())
        manifest = verify_envelope(envelope, image,
                                   serialization.load_pem_public_key(trusted_public))
        if manifest["release_seq"] != release_seq:
            raise ValueError("release sequence mismatch")
        current_path = root / "stable.json"
        if current_path.exists():
            current = json.loads(current_path.read_text())
            if current["release_seq"] > release_seq or (current["release_seq"] == release_seq
                    and current["sha256"] != manifest["sha256"]):
                raise ValueError("stable release cannot move backward or change digest")
        pointer = {"release_seq": release_seq, "sha256": manifest["sha256"]}
        fd, temporary = tempfile.mkstemp(prefix=".stable-", dir=root)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(canonical(pointer))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, current_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return pointer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "publish"))
    parser.add_argument("release_seq", type=int)
    parser.add_argument("--revision", default=os.environ.get("GIT_REVISION", ""))
    parser.add_argument("--firmware", type=Path, default=Path("/work/firmware"))
    parser.add_argument("--releases", type=Path, default=Path("/releases"))
    parser.add_argument("--signing", type=Path, default=Path("/signing"))
    args = parser.parse_args()
    if args.release_seq <= 0:
        parser.error("release_seq must be positive")
    if args.action == "build":
        if not args.revision:
            parser.error("GIT_REVISION or --revision is required")
        path = build_candidate(args.firmware, args.releases, args.signing,
                               args.release_seq, args.revision)
        print(f"Candidate ready: {path}; publish separately after review")
    else:
        pointer = publish(args.releases, args.signing, args.release_seq)
        print(f"Published release {pointer['release_seq']} ({pointer['sha256']})")


if __name__ == "__main__":
    main()
