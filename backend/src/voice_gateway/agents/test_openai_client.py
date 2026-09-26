import asyncio
import json

import httpx
import pytest

from .base import AgentClientError, AgentRequest
from .config import LLMConfig
from .openai_client import OpenAICompatibleAgentClient
from .sessions import AgentSessionStore


VALID = {
    "reply": "Сохранила мысль",
    "note": {"create": True, "title": "Заметка", "content": "Текст",
             "tags": ["идея"], "knowledge": {"operation": "capture", "target_id": None, "pages": []}},
}


def make_config(**values):
    return LLMConfig.from_env({"LLM_BASE_URL": "https://host.example/api/v1/",
                               "LLM_MODEL": "small", **values})


def response(content, *, model="small-actual", finish="stop", message_extra=None):
    message = {"role": "assistant", "content": content, **(message_extra or {})}
    return {"choices": [{"message": message, "finish_reason": finish}], "model": model}


def test_client_sends_openai_chat_completion_and_parses_knowledge_json():
    async def scenario():
        seen = []
        async def handler(request):
            seen.append(request)
            return httpx.Response(200, json=response(json.dumps(VALID, ensure_ascii=False)))
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OpenAICompatibleAgentClient(make_config(LLM_API_KEY="test-key"), "fixed system", client=http)
        try:
            result = await client.complete(AgentRequest("req-1", "mic", "Идея", {"pages": []}))
        finally:
            await http.aclose()
        req = seen[0]
        body = json.loads(req.content)
        assert str(req.url) == "https://host.example/api/v1/chat/completions"
        assert req.headers["Authorization"] == "Bearer test-key"
        assert body["model"] == "small"
        assert body["messages"] == [
            {"role": "system", "content": "fixed system"},
            {"role": "user", "content": '{"transcript": "Идея", "knowledge_context": {"pages": []}}'},
        ]
        assert "response_format" not in body
        assert result.reply == "Сохранила мысль"
        assert result.model == "small-actual"
        assert result.provider == "openai_compatible"
        assert result.note["knowledge"]["operation"] == "capture"
    asyncio.run(scenario())


def test_client_omits_auth_header_without_api_key_and_requests_json_mode():
    async def scenario():
        async def handler(request):
            assert "authorization" not in request.headers
            body = json.loads(request.content)
            assert body["response_format"] == {"type": "json_object"}
            return httpx.Response(200, json=response(json.dumps(VALID)))
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OpenAICompatibleAgentClient(make_config(LLM_RESPONSE_FORMAT="json_object"), "rules", client=http)
        try:
            await client.complete(AgentRequest("r", "device", "hi"))
        finally:
            await http.aclose()
    asyncio.run(scenario())


def test_invalid_json_gets_exactly_one_format_repair_request():
    async def scenario():
        calls = []
        async def handler(request):
            calls.append(json.loads(request.content))
            text = "```json\n" + json.dumps(VALID, ensure_ascii=False) + "\n```" if len(calls) == 2 else "not json"
            return httpx.Response(200, json=response(text))
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OpenAICompatibleAgentClient(make_config(), "rules", client=http)
        try:
            result = await client.complete(AgentRequest("r", "device", "words"))
        finally:
            await http.aclose()
        assert len(calls) == 2
        assert calls[1]["messages"][-2] == {"role": "assistant", "content": "not json"}
        assert "JSON" in calls[1]["messages"][-1]["content"]
        assert result.reply == "Сохранила мысль"
    asyncio.run(scenario())


def test_invalid_repair_and_all_contract_shapes_fail_without_leaking_body():
    async def scenario():
        cases = [
            response("not json"), response(json.dumps({"reply": "ok", "note": {"knowledge": {"operation": "unknown"}}})),
            response(json.dumps(VALID), finish="length"),
            response(json.dumps(VALID), message_extra={"tool_calls": [{"id": "x"}]}),
            response("I cannot do that", message_extra={"refusal": "policy"}),
            response(json.dumps(VALID), finish="content_filter"),
            {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]},
        ]
        for payload in cases:
            calls = 0
            async def handler(request):
                nonlocal calls
                calls += 1
                content = "still invalid" if calls > 1 else payload["choices"][0]["message"].get("content")
                current = payload if calls == 1 else response(content)
                return httpx.Response(200, json=current)
            http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            client = OpenAICompatibleAgentClient(make_config(), "rules", client=http)
            try:
                with pytest.raises(AgentClientError) as exc:
                    await client.complete(AgentRequest("r", "device", "private transcript"))
                assert exc.value.code == "agent_invalid_response"
                assert "private transcript" not in str(exc.value)
                assert "still invalid" not in str(exc.value)
                assert calls == (2 if isinstance(payload["choices"][0]["message"].get("content"), str)
                                 and payload["choices"][0]["finish_reason"] != "length"
                                 and payload["choices"][0]["finish_reason"] != "content_filter"
                                 and not payload["choices"][0]["message"].get("tool_calls")
                                 and not payload["choices"][0]["message"].get("refusal") else 1)
            finally:
                await http.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize("status,code", [(401, "agent_auth_required"), (403, "agent_auth_required"),
                                          (429, "agent_rate_limited"), (503, "agent_unavailable"),
                                          (400, "agent_config_error")])
def test_http_errors_are_mapped_without_echoing_remote_body(status, code):
    async def scenario():
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(status, text="secret transcript response body")
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OpenAICompatibleAgentClient(make_config(), "rules", client=http)
        try:
            with pytest.raises(AgentClientError) as exc:
                await client.complete(AgentRequest("r", "device", "input"))
            assert exc.value.code == code
            assert "secret" not in str(exc.value)
            assert "transcript" not in str(exc.value)
            assert calls == 1
        finally:
            await http.aclose()
    asyncio.run(scenario())


def test_timeout_and_transport_failure_are_safe():
    async def timeout_case():
        async def handler(request):
            await asyncio.sleep(.03)
            return httpx.Response(200, json=response(json.dumps(VALID)))
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OpenAICompatibleAgentClient(make_config(LLM_TIMEOUT_SECONDS="0.01"), "rules", client=http)
        try:
            with pytest.raises(AgentClientError, match="timed out") as exc:
                await client.complete(AgentRequest("r", "device", "input"))
            assert exc.value.code == "agent_timeout"
        finally:
            await http.aclose()
    asyncio.run(timeout_case())


def test_response_body_is_bounded():
    async def scenario():
        async def handler(request):
            return httpx.Response(200, content=b"x" * (1024 * 1024 + 1))
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = OpenAICompatibleAgentClient(make_config(), "rules", client=http)
        try:
            with pytest.raises(AgentClientError) as exc:
                await client.complete(AgentRequest("r", "device", "input"))
            assert exc.value.code == "agent_invalid_response"
        finally:
            await http.aclose()
    asyncio.run(scenario())


def test_session_cache_prevents_second_http_call_and_history_is_injected(tmp_path):
    async def scenario():
        calls = []
        async def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200, json=response(json.dumps(VALID, ensure_ascii=False)))
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sessions = AgentSessionStore(tmp_path / "sessions.sqlite3")
        client = OpenAICompatibleAgentClient(make_config(), "rules", client=http, sessions=sessions)
        try:
            request = AgentRequest("r", "device", "Идея", {"pages": []})
            first = await client.complete(request)
            sessions.record_turn("device", "r", "Идея", first.reply)
            again = await client.complete(request)
            assert again == first
            assert len(calls) == 1
            second = await client.complete(AgentRequest("r2", "device", "Подробнее"))
            assert second.reply == first.reply
            assert calls[1]["messages"][1:3] == [
                {"role": "user", "content": "Идея"},
                {"role": "assistant", "content": "Сохранила мысль"},
            ]
        finally:
            await http.aclose()
    asyncio.run(scenario())
