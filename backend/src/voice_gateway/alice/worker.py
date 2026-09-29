"""Background worker for the durable Alice queue (plan task 3).

The worker reads jobs from SQLite — never from an in-memory queue — so a
restart resumes exactly what was accepted. ``running`` jobs found at start
are recovered to ``queued`` and re-processed with the same request IDs;
the knowledge store and LLM session cache make that replay idempotent
(no duplicated notes, no second LLM generation for the same result).

The processor call carries the job's 180 s deadline (plan task 3); a
timeout or failure marks the job ``failed`` and keeps the original text in
the job row, so nothing is lost.
"""

from __future__ import annotations

import asyncio
import logging

from backend.src.voice_gateway.alice.models import AliceJob
from backend.src.voice_gateway.alice.store import AliceStore
from backend.src.voice_gateway.text_turns import TextTurnProcessor, TextTurnError
from backend.src.voice_gateway.usage.recorder import UsageRecorder

logger = logging.getLogger(__name__)


class AliceWorker:
    def __init__(self, store: AliceStore, processor: TextTurnProcessor,
                 usage_recorder: UsageRecorder | None = None) -> None:
        self.store = store
        self.processor = processor
        self.usage_recorder = usage_recorder
        self._task: asyncio.Task | None = None
        self._wakeup: asyncio.Event | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self.store.initialize()
        # Interrupted running jobs go back to the queue with the same IDs;
        # durable LLM/knowledge state makes the retry idempotent.
        self.store.recover_running()
        self._wakeup = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="alice-worker")
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._started = False

    def notify(self) -> None:
        """Nudge the worker after a new job was accepted."""
        if self._wakeup is not None:
            self._wakeup.set()

    async def _run(self) -> None:
        while True:
            job = await asyncio.to_thread(self.store.claim_next)
            if job is None:
                assert self._wakeup is not None
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=5.0)
                except TimeoutError:
                    pass
                self._wakeup.clear()
                continue
            await self._process(job)

    async def _process(self, job: AliceJob) -> None:
        try:
            result = await self.processor.process(job.request)
        except TextTurnError as exc:
            logger.warning("alice job %s failed: %s", job.job_id, exc.code)
            await asyncio.to_thread(self.store.fail, job.job_id, exc.code)
            await self._finish(job, "timeout" if exc.code == "agent_timeout" else "error")
            return
        except Exception:
            logger.exception("alice job %s failed unexpectedly", job.job_id)
            await asyncio.to_thread(self.store.fail, job.job_id, "agent_unavailable")
            await self._finish(job, "error")
            return
        await asyncio.to_thread(self.store.complete, job.job_id, result)
        await self._finish(job, "success")
        logger.info("alice job %s finished", job.job_id)

    async def _finish(self, job: AliceJob, outcome: str) -> None:
        if self.usage_recorder is not None:
            await self.usage_recorder.finish_turn_async(
                job.request.turn_id, channel="alice", outcome=outcome,
                operation="none", note_saved=False,
            )
