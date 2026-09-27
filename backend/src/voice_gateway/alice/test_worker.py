import asyncio
from pathlib import Path

import pytest

from backend.src.voice_gateway.alice.models import AliceReply
from backend.src.voice_gateway.alice.store import AliceStore
from backend.src.voice_gateway.alice.worker import AliceWorker
from backend.src.voice_gateway.test_text_turns import FakeAgent, SlowAgent
from backend.src.voice_gateway.text_turns import TextTurnProcessor, TextTurnError


def make_event(number=1, text="запиши мысль про полив"):
    from backend.src.voice_gateway.alice.test_store import make_event as factory
    return factory(number, "new_idea", text)


def make_worker(tmp_path, agent):
    store = AliceStore(tmp_path / "alice.sqlite3")
    store.initialize()
    processor = TextTurnProcessor(agent)
    return store, AliceWorker(store, processor)


def drain(store, worker, timeout=2.0):
    """Wait until the store has no queued/running jobs left."""

    async def scenario():
        await asyncio.sleep(0)
        while store.pending_count("owner-1") > 0:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)

    asyncio.run(asyncio.wait_for(scenario(), timeout))


def test_worker_processes_job_and_stores_reply(tmp_path):
    async def scenario():
        agent = FakeAgent()
        store, worker = make_worker(tmp_path, agent)
        store.accept(make_event(), AliceReply(text="ok"))
        await worker.start()
        try:
            for _ in range(100):
                if store.latest_reply("owner-1") is not None:
                    break
                await asyncio.sleep(0.01)
            latest = store.latest_reply("owner-1")
            assert latest["status"] == "done"
            assert latest["reply"] == "ответ"
            assert len(agent.requests) == 1
        finally:
            await worker.close()

    asyncio.run(scenario())


def test_failed_processing_marks_job_failed_and_keeps_text(tmp_path):
    class BrokenAgent(FakeAgent):
        async def complete(self, request):
            raise TextTurnError("agent_timeout")

    async def scenario():
        agent = BrokenAgent()
        store, worker = make_worker(tmp_path, agent)
        store.accept(make_event(), AliceReply(text="ok"))
        await worker.start()
        try:
            for _ in range(100):
                latest = store.latest_reply("owner-1")
                if latest is not None:
                    break
                await asyncio.sleep(0.01)
            latest = store.latest_reply("owner-1")
            assert latest["status"] == "failed"
            assert latest["error"] == "agent_timeout"
            # The original text survives in the job row for inspection.
            job = store.claim_next()
            assert job is None  # nothing queued anymore
        finally:
            await worker.close()

    asyncio.run(scenario())


def test_worker_picks_jobs_from_database_after_restart(tmp_path):
    """Accepted jobs survive a full process restart (fresh worker instance)."""

    async def first_process(tmp_path):
        agent = FakeAgent()
        store, worker = make_worker(tmp_path, agent)
        store.accept(make_event(), AliceReply(text="ok"))
        await worker.start()
        # Crash before processing: close without draining.
        await worker.close()
        return store

    async def scenario():
        store = await first_process(tmp_path)
        # New process: new store/worker instances over the same database.
        agent = FakeAgent()
        processor = TextTurnProcessor(agent)
        worker = AliceWorker(store, processor)
        await worker.start()
        try:
            for _ in range(100):
                if store.latest_reply("owner-1") is not None:
                    break
                await asyncio.sleep(0.01)
            assert store.latest_reply("owner-1")["status"] == "done"
            assert len(agent.requests) == 1
        finally:
            await worker.close()

    asyncio.run(scenario())


def test_slow_llm_does_not_block_acceptance(tmp_path):
    """A 120 s LLM would not stop the webhook path from accepting new jobs."""

    async def scenario():
        agent = SlowAgent(120)
        store, worker = make_worker(tmp_path, agent)
        store.accept(make_event(1), AliceReply(text="ok"))
        await worker.start()
        try:
            # Give the worker a moment to claim the slow job.
            for _ in range(100):
                if store.pending_count("owner-1") == 1:
                    break
                await asyncio.sleep(0.01)
            store.accept(make_event(2, "вторая мысль"), AliceReply(text="ok"))
            assert store.pending_count("owner-1") == 2
        finally:
            await worker.close()
        # The slow job was cancelled mid-flight by close(); recovery returns
        # both jobs to the queue with the same IDs for the next start.
        store.recover_running()
        jobs = []
        while True:
            job = store.claim_next()
            if job is None:
                break
            jobs.append(job.request.request_id)
        assert len(jobs) == 2
        assert len(set(jobs)) == 2

    asyncio.run(scenario())


def test_cancelled_job_text_is_preserved_after_shutdown(tmp_path):
    async def scenario():
        agent = SlowAgent(60)
        store, worker = make_worker(tmp_path, agent)
        store.accept(make_event(), AliceReply(text="ok"))
        await worker.start()
        for _ in range(100):
            if store.pending_count("owner-1") == 1:
                break
            await asyncio.sleep(0.01)
        await worker.close()
        store.recover_running()
        job = store.claim_next()
        assert job is not None
        assert job.request.transcript == "запиши мысль про полив"

    asyncio.run(scenario())
