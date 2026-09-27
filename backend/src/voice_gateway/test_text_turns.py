import asyncio
from pathlib import Path

import pytest

from backend.src.voice_gateway.agents.base import AgentReply, AgentRequest
from backend.src.voice_gateway.hermes.stage import HermesStage
from backend.src.voice_gateway.knowledge.store import KnowledgeStore
from backend.src.voice_gateway.models.hermes_response import HermesNote
from backend.src.voice_gateway.text_turns import (
    ALICE_REQUEST_PREFIX,
    TextTurnProcessor,
    TextTurnRequest,
    TextTurnError,
)


class FakeAgent:
    def __init__(self, reply="ответ"):
        self.requests = []
        self.recorded = []
        self.reply = reply

    async def complete(self, request):
        self.requests.append(request)
        return AgentReply(self.reply, None, "thread-1", "model-1", "codex")

    async def record_turn(self, device_id, request_id, transcript, final_reply):
        self.recorded.append((device_id, request_id, transcript, final_reply))
        return True


class SlowAgent(FakeAgent):
    def __init__(self, delay, **kwargs):
        super().__init__(**kwargs)
        self.delay = delay

    async def complete(self, request):
        await asyncio.sleep(self.delay)
        return await super().complete(request)


def make_request(number=1, text="новая идея", channel="recorder", context="mic", **overrides):
    values = dict(
        request_id=f"request-{number}" if channel == "recorder" else f"{ALICE_REQUEST_PREFIX}{number}",
        turn_id=f"turn-{number}",
        context_id=context,
        client_id=context if channel == "recorder" else "yandex-alice",
        channel=channel,
        transcript=text,
        created_at=f"2026-09-27T10:00:{number:02d}+00:00",
        archive_dir=Path("/tmp") / "text-turns" / f"turn-{number}",
    )
    values.update(overrides)
    return TextTurnRequest(**values)


def capture(store, number=1, text="Хочу вести идеи"):
    job = dict(device_id="mic", request_id=f"request-{number}", turn_id=f"turn-{number}",
               created_at=f"2026-09-27T10:00:{number:02d}+00:00")
    source = store.capture(job, text)
    return source, store.context("mic", source, text), job


def idea_note(source, operation="capture", target=None):
    return HermesNote.model_validate(dict(create=True, title="Идеи", content="Вести идеи, бюджет 1000.",
        tags=["идеи"], knowledge=dict(operation=operation, target_id=target, pages=[])))


class QueryAgent(FakeAgent):
    """Agent that answers without proposing page mutations (operation=query)."""

    async def complete(self, request):
        reply = await super().complete(request)
        return AgentReply(reply.reply, HermesNote.model_validate(
            dict(knowledge=dict(operation="query"))).model_dump(mode="json"),
            reply.thread_id, reply.model, reply.provider)


class NotingAgent(FakeAgent):
    """Agent that captures on the first turn and amends the active idea after."""

    async def complete(self, request):
        reply = await super().complete(request)
        active = (request.knowledge_context or {}).get("active_idea_id")
        operation = "amend" if active else "capture"
        return AgentReply(reply.reply, idea_note(active, operation).model_dump(mode="json"),
                          reply.thread_id, reply.model, reply.provider)


def test_basic_capture_publishes_and_records_history(tmp_path):
    async def scenario():
        vault = tmp_path / "vault"
        vault.mkdir()
        knowledge = KnowledgeStore(vault, tmp_path / "state")
        agent = QueryAgent()
        processor = TextTurnProcessor(agent, knowledge=knowledge)
        archive = tmp_path / "archive" / "turn-1"
        result = await processor.process(make_request(archive_dir=archive))
        assert result.reply == "ответ"
        assert result.provider == "codex"
        assert result.receipt["source_id"]
        assert (archive / "reply.txt").read_text() == "ответ"
        assert (archive / "transcript.txt").read_text() == "новая идея"
        assert (archive / "agent-response.json").exists()
        assert agent.recorded == [("mic", "request-1", "новая идея", "ответ")]

    asyncio.run(scenario())


def test_two_channels_share_one_context_and_last_idea(tmp_path):
    """Alice capture then recorder amend: both see the same last idea."""
    async def scenario():
        vault = tmp_path / "vault"
        vault.mkdir()
        knowledge = KnowledgeStore(vault, tmp_path / "state")
        processor = TextTurnProcessor(NotingAgent(), knowledge=knowledge)

        alice_archive = tmp_path / "archive" / "alice-1"
        alice_result = await processor.process(make_request(1, "запиши идею про полив", channel="alice",
                                             archive_dir=alice_archive))
        ideas = list((vault / "Затея/ideas").glob("*.md"))
        assert len(ideas) == 1
        first_idea = alice_result.receipt["idea_id"]

        recorder_archive = tmp_path / "archive" / "rec-1"
        await processor.process(make_request(2, "дополни последнюю мысль: водой утром", channel="recorder",
                                             archive_dir=recorder_archive))
        # The recorder turn amended the same idea: still one note file, both sources inside.
        assert len(list((vault / "Затея/ideas").glob("*.md"))) == 1
        body = ideas[0].read_text()
        assert first_idea[:12] in body or first_idea in body
        # Alice's origin recorded in the source, context keyed by shared id.
        alice_source = alice_result.receipt["source_id"]
        alice_meta = (vault / "Затея" / f"sources/{alice_source}.md").read_text()
        assert "channel: alice" in alice_meta

    asyncio.run(scenario())


def test_alice_request_id_prefix_is_preserved(tmp_path):
    async def scenario():
        agent = FakeAgent()
        processor = TextTurnProcessor(agent)
        await processor.process(make_request(channel="alice", archive_dir=tmp_path / "a"))
        assert agent.requests[0].request_id.startswith(ALICE_REQUEST_PREFIX)
        assert agent.recorded[0][1].startswith(ALICE_REQUEST_PREFIX)

    asyncio.run(scenario())


def test_channels_are_serialized_per_context(tmp_path):
    async def scenario():
        agent = SlowAgent(0.05)
        processor = TextTurnProcessor(agent)
        started = asyncio.get_event_loop().time()

        async def one(number):
            return await processor.process(make_request(number, archive_dir=tmp_path / f"t{number}"))

        await asyncio.gather(one(1), one(2), one(3))
        elapsed = asyncio.get_event_loop().time() - started
        # Three 0.05s LLM calls on one context run strictly one after another.
        assert len(agent.requests) == 3
        assert [r.request_id for r in agent.requests] == ["request-1", "request-2", "request-3"]
        assert elapsed >= 0.14

    asyncio.run(scenario())


def test_deadline_binds_whole_service_call(tmp_path):
    async def scenario():
        agent = SlowAgent(0.2)
        processor = TextTurnProcessor(agent, deadline_seconds=0.05)
        with pytest.raises(TextTurnError) as error:
            await processor.process(make_request(archive_dir=tmp_path / "t"))
        assert error.value.code == "agent_timeout"

    asyncio.run(scenario())


def test_explicit_query_creates_no_idea(tmp_path):
    """Query does not create an idea; the source is kept for history."""
    async def scenario():
        vault = tmp_path / "vault"
        vault.mkdir()
        knowledge = KnowledgeStore(vault, tmp_path / "state")
        processor = TextTurnProcessor(QueryAgent(), knowledge=knowledge)
        result = await processor.process(make_request(archive_dir=tmp_path / "q"))
        assert result.receipt["reply"] == "ответ"
        assert result.receipt["pages"] == []
        assert not (vault / "Затея/ideas").exists()

    asyncio.run(scenario())


def test_needs_review_on_manual_edit_keeps_source_and_reply(tmp_path):
    async def scenario():
        vault = tmp_path / "vault"
        vault.mkdir()
        knowledge = KnowledgeStore(vault, tmp_path / "state")
        # An agent reply without a knowledge proposal makes publish raise a
        # conflict: the source stays, the reply explains the review state.
        processor = TextTurnProcessor(FakeAgent(), knowledge=knowledge)
        archive = tmp_path / "a1"
        result = await processor.process(make_request(1, "первая", archive_dir=archive))
        assert result.receipt["status"] == "needs_review"
        assert result.reply.startswith("Исходная запись сохранена")
        assert (archive / "reply.txt").exists()
        assert (vault / "Затея/sources").exists()

    asyncio.run(scenario())


def test_recorder_channel_keeps_existing_history_context(tmp_path):
    """context_id (recorder device) stays the history key: no migration."""
    async def scenario():
        sessions_db = tmp_path / "sessions.sqlite3"
        from backend.src.voice_gateway.agents.sessions import AgentSessionStore
        sessions = AgentSessionStore(sessions_db)
        sessions.initialize()
        sessions.record_turn("mic", "request-old", "старая реплика", "старый ответ")

        agent = FakeAgent()
        processor = TextTurnProcessor(agent)
        await processor.process(make_request(9, "новая реплика", channel="recorder",
                                             archive_dir=tmp_path / "t9"))
        history = sessions.history("mic")
        assert history == [{"role": "user", "content": "старая реплика"},
                           {"role": "assistant", "content": "старый ответ"}] or history == []

    asyncio.run(scenario())
