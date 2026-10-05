"""Verify the one explicitly published OTA release before serving any bytes."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


SLOT_BYTES = 0x300000
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class StableRelease:
    sequence: int
    sha256: str
    image: Path
    size: int
    envelope: dict[str, str]


def _read_limited(path: Path, limit: int) -> bytes:
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("release metadata too large")
    return data


def verified_stable(root: Path) -> StableRelease | None:
    try:
        pointer = json.loads(_read_limited(root / "stable.json", 1024))
        if (not isinstance(pointer, dict) or set(pointer) != {"release_seq", "sha256"}
                or type(pointer["release_seq"]) is not int or pointer["release_seq"] <= 0
                or not isinstance(pointer["sha256"], str)
                or not SHA256_RE.fullmatch(pointer["sha256"])):
            return None
        sequence, digest = pointer["release_seq"], pointer["sha256"]
        candidate = root / "releases" / str(sequence)
        image = candidate / "image.bin"
        size = image.stat().st_size
        if size <= 0 or size > SLOT_BYTES:
            return None
        calculated = hashlib.sha256()
        with image.open("rb") as source:
            while chunk := source.read(65536):
                calculated.update(chunk)
        if calculated.hexdigest() != digest:
            return None
        envelope = json.loads(_read_limited(candidate / "envelope.json", 8192))
        if not isinstance(envelope, dict) or set(envelope) != {"manifest_b64", "signature_b64"}:
            return None
        manifest_bytes = base64.b64decode(envelope["manifest_b64"], validate=True)
        signature = base64.b64decode(envelope["signature_b64"], validate=True)
        if len(manifest_bytes) > 4096 or len(signature) > 256:
            return None
        public_pem = _read_limited(root / "trusted_public.pem", 4096)
        public_key = serialization.load_pem_public_key(public_pem)
        if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
            public_key.curve, ec.SECP256R1
        ):
            return None
        public_key.verify(signature, manifest_bytes, ec.ECDSA(hashes.SHA256()))
        public_der = public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        manifest = json.loads(manifest_bytes)
        expected = {
            "schema": 1, "board": "sticks3", "layout": "ota-v1",
            "release_seq": sequence, "git_revision": manifest.get("git_revision"),
            "size": size, "sha256": digest,
            "image_path": f"/api/firmware/images/{digest}.bin",
            "key_id": hashlib.sha256(public_der).hexdigest()[:16],
        }
        if (manifest != expected or not isinstance(manifest["git_revision"], str)
                or not re.fullmatch(r"[0-9a-f]{40}", manifest["git_revision"])):
            return None
        return StableRelease(sequence, digest, image, size, envelope)
    except Exception:
        # No untrusted metadata is logged or reflected to the device.
        return None
