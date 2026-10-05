"""Private pull-only OTA endpoints for the recorder."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

from backend.src.voice_gateway.jobs.auth import owns_device

from .manifest import SHA256_RE, verified_stable


def install_firmware_routes(app: FastAPI, root: Path,
                            device_tokens: dict[str, str]) -> None:
    def authenticate(request: Request) -> None:
        device_id = request.headers.get("X-Device-Id", "")
        if not device_id or not owns_device(
            device_id, request.headers.get("Authorization"), device_tokens
        ):
            raise HTTPException(status_code=401, detail={"error": "unauthorized"})

    @app.get("/api/firmware/manifest")
    def manifest(request: Request, board: str, layout: str, current_seq: int):
        authenticate(request)
        if board != "sticks3" or layout != "ota-v1" or current_seq < 0:
            return Response(status_code=204)
        stable = verified_stable(root)
        if stable is None or stable.sequence <= current_seq:
            return Response(status_code=204)
        return stable.envelope

    @app.get("/api/firmware/images/{digest}.bin")
    def image(request: Request, digest: str):
        authenticate(request)
        if not SHA256_RE.fullmatch(digest):
            raise HTTPException(status_code=404)
        stable = verified_stable(root)
        if stable is None or stable.sha256 != digest:
            raise HTTPException(status_code=404)
        return FileResponse(
            stable.image, media_type="application/octet-stream",
            headers={"ETag": digest, "Cache-Control": "private, no-store"},
        )
