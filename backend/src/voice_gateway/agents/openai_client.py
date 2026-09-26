"""Bounded direct Chat Completions client for OpenAI-compatible providers."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from backend.src.voice_gateway.hermes.validation import HermesValidationError, parse_hermes_response

from .base import AgentClientError, AgentReply, AgentRequest
from .config import LLMConfig
from .sessions import AgentSessionStore, IdempotencyConflict, input_digest

logger = logging.getLogger(__name__)


class OpenAICompatibleAgentClient:
    MAX_RESPONSE_BYTES = 1024 * 1024

    def __init__(
        self,
        config: LLMConfig,
        system_prompt: str,
        *,
        client: httpx.AsyncClient | None = None,
        sessions: AgentSessionStore | None = None,
    ) -> None:
        self.config = config
        self.system_prompt = system_prompt
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._active: dict[str, asyncio.Task] = {}
        self.sessions = sessions
        if sessions is not None:
            sessions.initialize()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def cancel(self, request_id: str) -> None:
        task = self._active.get(request_id)
        if task and task is not asyncio.current_task():
            task.cancel()

    async def reset(self, device_id: str) -> None:
        if self.sessions is not None:
            self.sessions.reset(device_id)

    async def record_turn(self, device_id: str, request_id: str, transcript: str,
                          final_reply: str) -> bool:
        if self.sessions is None:
            return True
        return self.sessions.record_turn(device_id, request_id, transcript, final_reply)

    async def complete(self, request: AgentRequest) -> AgentReply:
        task = asyncio.current_task()
        started_at = time.monotonic()
        if task is not None:
            self._active[request.request_id] = task
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                session = None
                if self.sessions is not None:
                    try:
                        session = self.sessions.begin(
                            request.device_id, request.request_id,
                            input_digest(request.transcript, request.knowledge_context),
                        )
                    except IdempotencyConflict:
                        raise AgentClientError(
                            "idempotency_conflict", "Request ID was reused with different input"
                        ) from None
                    if session.cached is not None:
                        return AgentReply(**session.cached)
                messages = [
                    {"role": "system", "content": self.system_prompt},
                ]
                if self.sessions is not None:
                    messages.extend(self.sessions.history(request.device_id))
                messages.append({"role": "user", "content": self._user_message(request)})
                payload = await self._post(messages)
                content, model = self._extract_content(payload)
                try:
                    parsed = parse_hermes_response(content)
                except HermesValidationError:
                    repair_messages = [
                        *messages,
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": self._repair_instruction()},
                    ]
                    repaired_payload = await self._post(repair_messages)
                    content, repaired_model = self._extract_content(repaired_payload)
                    model = repaired_model or model
                    try:
                        parsed = parse_hermes_response(content)
                    except HermesValidationError:
                        raise AgentClientError("agent_invalid_response", "LLM returned invalid JSON") from None
                result = AgentReply(
                    reply=parsed.reply.strip(),
                    note=parsed.note.model_dump(mode="json"),
                    thread_id=f"device:{request.device_id}",
                    model=model or self.config.model,
                    provider="openai_compatible",
                )
                if self.sessions is not None and session is not None:
                    self.sessions.save_result(
                        request.device_id, request.request_id, session.generation,
                        {"reply": result.reply, "note": result.note, "thread_id": result.thread_id,
                         "model": result.model, "provider": result.provider},
                    )
                return result
        except TimeoutError:
            logger.warning(
                "LLM request timed out (request_id=%s, model=%s, elapsed_seconds=%.1f, configured_timeout_seconds=%.1f)",
                request.request_id,
                self.config.model,
                time.monotonic() - started_at,
                self.config.timeout_seconds,
            )
            raise AgentClientError("agent_timeout", "LLM request timed out", True) from None
        except httpx.TimeoutException:
            logger.warning(
                "LLM transport timed out (request_id=%s, model=%s, elapsed_seconds=%.1f)",
                request.request_id,
                self.config.model,
                time.monotonic() - started_at,
            )
            raise AgentClientError("agent_timeout", "LLM request timed out", True) from None
        except httpx.HTTPError:
            raise AgentClientError("agent_unavailable", "LLM endpoint is unavailable", True) from None
        finally:
            if self._active.get(request.request_id) is task:
                self._active.pop(request.request_id, None)

    @staticmethod
    def _user_message(request: AgentRequest) -> str:
        from .prompts import user_message

        return user_message(request.transcript, request.knowledge_context)

    @staticmethod
    def _repair_instruction() -> str:
        return "Исправь только формат и соответствие исходному JSON-контракту. Сохрани смысл и верни только корректный JSON без пояснений."

    async def _post(self, messages: list[dict[str, str]]) -> dict:
        body: dict = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.response_format == "json_object":
            body["response_format"] = {"type": "json_object"}
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        url = f"{self.config.base_url}/chat/completions"
        async with self._client.stream(
            "POST", url, json=body, headers=headers, timeout=None
        ) as response:
            if response.status_code != 200:
                self._raise_status(response.status_code)
            data = bytearray()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > self.MAX_RESPONSE_BYTES:
                    raise AgentClientError("agent_invalid_response", "LLM response is too large")
                data.extend(chunk)
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AgentClientError("agent_invalid_response", "LLM returned invalid response JSON") from None
        if not isinstance(payload, dict):
            raise AgentClientError("agent_invalid_response", "LLM returned invalid response JSON")
        return payload

    @staticmethod
    def _raise_status(status: int) -> None:
        if status in (401, 403):
            raise AgentClientError("agent_auth_required", "LLM credentials were rejected")
        if status == 429:
            raise AgentClientError("agent_rate_limited", "LLM provider rate limit reached", True)
        if status >= 500:
            raise AgentClientError("agent_unavailable", "LLM provider is unavailable", True)
        raise AgentClientError("agent_config_error", "LLM provider rejected the request")

    @staticmethod
    def _extract_content(payload: dict) -> tuple[str, str | None]:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise AgentClientError("agent_invalid_response", "LLM returned an invalid response")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise AgentClientError("agent_invalid_response", "LLM response was truncated")
        if choice.get("finish_reason") == "content_filter":
            raise AgentClientError("agent_invalid_response", "LLM response was refused")
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise AgentClientError("agent_invalid_response", "LLM returned an invalid response")
        content = message.get("content")
        if (message.get("tool_calls") or message.get("refusal")
                or not isinstance(content, str) or not content.strip()):
            raise AgentClientError("agent_invalid_response", "LLM returned an invalid response")
        model = payload.get("model")
        return content, model if isinstance(model, str) and model else None
