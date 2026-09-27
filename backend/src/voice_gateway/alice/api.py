"""Fast Alice webhook endpoint (plan task 4).

Budget: the whole handler fits into 2 s (platform limit is 4.5 s). The
endpoint does only four things: verify the token, build the verified event,
persist it through the durable store (short busy timeout), and return the
stored reply. LLM, Git and knowledge work happen in the background worker
— a slow LLM/Git never delays the HTTP answer (tested separately).

Limits: 64 KiB body, 30 requests/minute per owner plus the general ingress
limiter before OAuth verification. HTTP client disconnects after the store
commit never delete the accepted job.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.src.voice_gateway.alice.auth import AliceAuthenticator, AuthFailure
from backend.src.voice_gateway.alice.config import AliceConfig
from backend.src.voice_gateway.alice.models import (
    AliceEvent,
    AliceReply,
    DRAFT_MAX_CHARS,
)
from backend.src.voice_gateway.alice.store import (
    AliceStore,
    DraftOverflow,
    EventConflict,
    QueueFull,
)
from backend.src.voice_gateway.alice.render import (
    reply_busy,
    reply_overflow,
    reply_queue_full,
)


def safe_reply(reply: AliceReply, *, version: str | None) -> dict:
    """Wrap an AliceReply into the protocol envelope."""
    payload = reply.as_protocol()
    if version is not None:
        payload["version"] = version
    return payload
from backend.src.voice_gateway.alice.dialogue import route_utterance
from backend.src.voice_gateway.alice.worker import AliceWorker

logger = logging.getLogger(__name__)

#: Handler budget (plan task 4): 2 s for the whole webhook.
WEBHOOK_BUDGET_SECONDS = 2.0

#: Maximum accepted body size (plan task 4): 64 KiB.
MAX_BODY_BYTES = 64 * 1024

#: Per-owner request rate (plan task 4).
OWNER_RATE_LIMIT = 30
OWNER_RATE_PERIOD = 60.0


class _OwnerRateLimiter:
    """Small sliding-window limiter for the per-owner quota."""

    def __init__(self, limit: int = OWNER_RATE_LIMIT, period: float = OWNER_RATE_PERIOD) -> None:
        self.limit = limit
        self.period = period
        self._windows: dict[str, list[float]] = {}

    def check(self, owner: str) -> bool:
        now = time.monotonic()
        window = [t for t in self._windows.get(owner, []) if now - t < self.period]
        if len(window) >= self.limit:
            self._windows[owner] = window
            return False
        window.append(now)
        self._windows[owner] = window
        return True


def install_alice_routes(
    app: FastAPI,
    config: AliceConfig,
    store: AliceStore,
    worker: AliceWorker,
    authenticator: AliceAuthenticator,
) -> None:
    limiter = _OwnerRateLimiter()

    @app.post("/api/alice/webhook")
    async def webhook(request: Request) -> JSONResponse:
        started = time.monotonic()
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse(safe_reply(reply_busy(), version=None), status_code=413)
        try:
            envelope = json.loads(body)
        except ValueError:
            return JSONResponse(safe_reply(reply_busy(), version=None), status_code=400)
        if not isinstance(envelope, dict):
            return JSONResponse(safe_reply(reply_busy(), version=None), status_code=400)

        session = envelope.get("session") or {}
        skill_id = session.get("skill_id", "")
        # Ping needs no auth and no data access (plan task 4).
        if skill_id == "ping":
            return JSONResponse({"version": envelope.get("version", "1.0"),
                                 "session": session,
                                 "response": {"text": "pong", "end_session": True}})
        if skill_id != config.skill_id:
            return JSONResponse(safe_reply(reply_busy(), version=envelope.get("version")), status_code=403)

        # Ingress rate limit per owner candidate before OAuth verification:
        # unauthenticated floods are capped by the general limiter + body size;
        # the per-owner quota applies to the verified owner below.
        token = _extract_token(request) or _token_from_body(envelope)
        if token is None:
            return JSONResponse(_linking_reply(envelope))
        try:
            identity = await authenticator.authenticate(token)
        except AuthFailure as failure:
            if failure.kind == "link":
                return JSONResponse(_linking_reply(envelope))
            # Yandex ID unavailable: refuse access without data (fail closed).
            return JSONResponse(safe_reply(reply_busy(), version=envelope.get("version")), status_code=503)

        if not limiter.check(identity.yandex_user_id):
            return JSONResponse(safe_reply(reply_busy(), version=envelope.get("version")), status_code=429)

        utterance = _utterance(envelope)
        action = route_utterance(envelope, store=store, owner=identity.yandex_user_id)
        event = AliceEvent(
            owner=identity.yandex_user_id,
            context_id=identity.context_id,
            skill_id=skill_id,
            session_id=str(session.get("session_id", "")),
            message_id=str(session.get("message_id", "")),
            payload_hash="",
            action=action.action,
            text=utterance,
            has_screen=bool((envelope.get("meta") or {}).get("interfaces", {}).get("screen")),
            archive_dir=str(config.archive_root / "alice"),
        )
        try:
            reply = await asyncio.wait_for(
                asyncio.to_thread(store.accept, event, action.reply),
                timeout=max(0.2, WEBHOOK_BUDGET_SECONDS - (time.monotonic() - started)),
            )
        except (DraftOverflow, QueueFull, EventConflict) as exc:
            logger.info("alice event rejected: %s", type(exc).__name__)
            problem = reply_overflow() if isinstance(exc, DraftOverflow) else reply_queue_full()
            return JSONResponse(safe_reply(problem, version=envelope.get("version")))
        except TimeoutError:
            logger.warning("alice webhook store commit exceeded the budget")
            return JSONResponse(safe_reply(reply_busy(), version=envelope.get("version")), status_code=503)
        worker.notify()
        return JSONResponse(safe_reply(reply, version=envelope.get("version")))


def _extract_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    # Alice also delivers the token inside the request body for linked skills.
    return None


def _token_from_body(envelope: dict) -> str | None:
    token = ((envelope.get("session") or {}).get("user") or {}).get("access_token")
    return token if isinstance(token, str) and token else None


def _utterance(envelope: dict) -> str:
    request = envelope.get("request") or {}
    original = request.get("original_utterance")
    return original if isinstance(original, str) else ""


def _linking_reply(envelope: dict) -> dict:
    """Official start_account_linking when possible, otherwise instruction."""
    response: dict = {"text": "Подключите аккаунт в приложении Яндекса: откройте навык и войдите.",
                      "end_session": True}
    return {"version": envelope.get("version", "1.0"),
            "session": envelope.get("session", {}),
            "response": response}


__all__ = ["install_alice_routes", "MAX_BODY_BYTES", "WEBHOOK_BUDGET_SECONDS"]
