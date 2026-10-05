"""Authenticated ingestion of bounded device diagnostics."""

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from backend.src.voice_gateway.jobs.auth import owns_device

from .models import DeviceDiagnostics
from .store import DiagnosticConflict, DiagnosticsStore


MAX_REPORT_BYTES = 16 * 1024


def install_diagnostic_routes(app: FastAPI, store: DiagnosticsStore,
                              device_tokens: dict[str, str]) -> None:
    @app.post("/api/devices/diagnostics", status_code=202)
    async def receive_diagnostics(request: Request):
        device_id = request.headers.get("X-Device-Id", "")
        if not device_id or not owns_device(
            device_id, request.headers.get("Authorization"), device_tokens
        ):
            raise HTTPException(status_code=401, detail={"error": "unauthorized"})
        content_length = request.headers.get("Content-Length")
        if content_length and (not content_length.isdecimal() or int(content_length) > MAX_REPORT_BYTES):
            raise HTTPException(status_code=413, detail={"error": "report_too_large"})
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_REPORT_BYTES:
                raise HTTPException(status_code=413, detail={"error": "report_too_large"})
        try:
            report = DeviceDiagnostics.model_validate_json(body)
        except ValidationError:
            # Never echo user-provided values or validation context; secrets may
            # have been submitted in an unexpected field.
            raise HTTPException(status_code=400, detail={"error": "invalid_diagnostics"}) from None
        try:
            store.save(device_id, report)
        except DiagnosticConflict:
            raise HTTPException(status_code=409, detail={"error": "report_conflict"}) from None
        return {"accepted": True}
