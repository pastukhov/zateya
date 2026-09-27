"""Yandex ID token verification for the Alice webhook (plan task 4).

The OAuth access token from the linked account is checked against
``GET https://login.yandex.ru/info``; the returned ``id`` must equal
``ALICE_ALLOWED_YANDEX_ID``. JSON fields ``user_id``/``skill_id`` inside
the webhook body are treated as data, never as proof of identity.

Failure policy (plan task 4): a missing/revoked token asks for account
linking; Yandex ID being unreachable refuses access (fail closed). A
positive result is cached for at most 60 s keyed by token hash; tokens are
never logged.
"""

from __future__ import annotations

import hashlib
import logging
import time

import httpx

from backend.src.voice_gateway.alice.models import AliceIdentity

logger = logging.getLogger(__name__)

INFO_URL = "https://login.yandex.ru/info"

#: Token check timeout (plan task 4): 1 s.
INFO_TIMEOUT_SECONDS = 1.0

#: Positive cache lifetime (plan task 4): at most 60 s.
POSITIVE_CACHE_SECONDS = 60.0


class AliceAuthenticator:
    def __init__(self, *, allowed_yandex_id: str, context_id: str,
                 client: httpx.AsyncClient | None = None,
                 cache_seconds: float = POSITIVE_CACHE_SECONDS,
                 timeout: float = INFO_TIMEOUT_SECONDS) -> None:
        self.allowed_yandex_id = allowed_yandex_id
        self.context_id = context_id
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._cache_seconds = cache_seconds
        self._timeout = timeout
        self._cache: dict[str, tuple[float, AliceIdentity]] = {}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _cache_key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def authenticate(self, token: str) -> AliceIdentity:
        """Verify the OAuth token; raise :class:`AuthFailure` on any problem.

        - ``AuthFailure.link`` — token absent/revoked → account linking flow;
        - ``AuthFailure.unavailable`` — Yandex ID unreachable → refuse access.
        """
        key = self._cache_key(token)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._cache_seconds:
            return cached[1]
        try:
            response = await self._client.get(
                INFO_URL,
                params={"format": "json"},
                headers={"Authorization": f"OAuth {token}"},
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            logger.warning("yandex id token check timed out")
            raise AuthFailure.unavailable("yandex id timed out") from None
        except httpx.HTTPError:
            logger.warning("yandex id token check failed")
            raise AuthFailure.unavailable("yandex id is unavailable") from None
        if response.status_code in (401, 403):
            raise AuthFailure.link("token revoked or invalid")
        if response.status_code != 200:
            logger.warning("yandex id token check status %s", response.status_code)
            raise AuthFailure.unavailable("yandex id rejected the request")
        try:
            payload = response.json()
            yandex_id = payload["id"]
        except (ValueError, KeyError, TypeError):
            logger.warning("yandex id returned an unexpected payload shape")
            raise AuthFailure.unavailable("yandex id payload is invalid") from None
        if not isinstance(yandex_id, str) or yandex_id != self.allowed_yandex_id:
            # A valid token belonging to someone else: refuse, ask linking.
            logger.info("alice token owner mismatch")
            raise AuthFailure.link("token belongs to another account")
        identity = AliceIdentity(yandex_user_id=yandex_id, context_id=self.context_id)
        self._cache[key] = (now, identity)
        return identity


class AuthFailure(Exception):
    """Authentication did not pass; carries the safe client behavior."""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind  # "link" | "unavailable"
        super().__init__(message)

    @classmethod
    def link(cls, message: str) -> "AuthFailure":
        return cls("link", message)

    @classmethod
    def unavailable(cls, message: str) -> "AuthFailure":
        return cls("unavailable", message)
