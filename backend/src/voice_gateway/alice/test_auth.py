import asyncio

import httpx
import pytest

from backend.src.voice_gateway.alice.auth import AliceAuthenticator, AuthFailure


def handler(fail_mode=None, user_id="owner-1", status=200):
    async def inner(request):
        if fail_mode == "timeout":
            raise httpx.ConnectTimeout("slow")
        if fail_mode == "network":
            raise httpx.ConnectError("down")
        if fail_mode == "revoked":
            return httpx.Response(403, json={"error": "token expired"})
        if fail_mode == "bad_payload":
            return httpx.Response(200, content=b"not json")
        if fail_mode == "other_user":
            return httpx.Response(200, json={"id": "intruder"})
        if fail_mode == "error":
            return httpx.Response(500, text="boom")
        return httpx.Response(status, json={"id": user_id, "login": "o", "client_id": "c"})
    return httpx.MockTransport(inner)


def make_auth(fail_mode=None, user_id="owner-1", cache_seconds=60.0):
    client = httpx.AsyncClient(transport=handler(fail_mode, user_id=user_id))
    return AliceAuthenticator(allowed_yandex_id="owner-1", context_id="mic",
                              client=client, cache_seconds=cache_seconds)


def test_valid_token_returns_identity():
    async def scenario():
        auth = make_auth()
        try:
            identity = await auth.authenticate("token-1")
            assert identity.yandex_user_id == "owner-1"
            assert identity.context_id == "mic"
        finally:
            await auth.aclose()

    asyncio.run(scenario())


def test_revoked_token_asks_linking():
    async def scenario():
        auth = make_auth(fail_mode="revoked")
        try:
            with pytest.raises(AuthFailure) as error:
                await auth.authenticate("token-1")
            assert error.value.kind == "link"
        finally:
            await auth.aclose()

    asyncio.run(scenario())


def test_unreachable_yandex_id_fails_closed():
    async def scenario():
        for mode in ("timeout", "network", "error", "bad_payload"):
            auth = make_auth(fail_mode=mode)
            try:
                with pytest.raises(AuthFailure) as error:
                    await auth.authenticate("token-1")
                assert error.value.kind == "unavailable", mode
            finally:
                await auth.aclose()

    asyncio.run(scenario())


def test_other_account_never_gets_access():
    async def scenario():
        auth = make_auth(fail_mode="other_user")
        try:
            with pytest.raises(AuthFailure) as error:
                await auth.authenticate("stolen-token")
            assert error.value.kind == "link"
        finally:
            await auth.aclose()

    asyncio.run(scenario())


def test_positive_result_is_cached():
    async def scenario():
        calls = []

        async def counting(request):
            calls.append(request)
            return httpx.Response(200, json={"id": "owner-1"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(counting))
        auth = AliceAuthenticator(allowed_yandex_id="owner-1", context_id="mic",
                                  client=client, cache_seconds=60.0)
        try:
            await auth.authenticate("token-1")
            await auth.authenticate("token-1")
            assert len(calls) == 1  # second call hit the cache
        finally:
            await auth.aclose()

    asyncio.run(scenario())


def test_expired_cache_entry_rechecks():
    async def scenario():
        calls = []

        async def counting(request):
            calls.append(request)
            return httpx.Response(200, json={"id": "owner-1"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(counting))
        auth = AliceAuthenticator(allowed_yandex_id="owner-1", context_id="mic",
                                  client=client, cache_seconds=0.0)
        try:
            await auth.authenticate("token-1")
            await auth.authenticate("token-1")
            assert len(calls) == 2
        finally:
            await auth.aclose()

    asyncio.run(scenario())
