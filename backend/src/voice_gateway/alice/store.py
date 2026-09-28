"""Durable SQLite queue for the Alice adapter (plan task 3).

Durability contract:
- ``accept`` records the event, the dialogue transition (draft append /
  job creation) and the protocol reply in ONE transaction; the webhook
  answers only after that commit, so a lost HTTP response replays the
  same reply without duplicating work.
- Replays with the same key + payload hash return the stored reply; the
  same key with different content is rejected.
- Jobs are read back from the database by the worker (no in-memory-only
  queue); ``running`` jobs are recovered with their original IDs after a
  restart, so published notes and history never duplicate.
- OAuth tokens are never stored: jobs keep only the text request.

SQLite work runs in threads (``asyncio.to_thread`` at the API layer), so a
long knowledge writer never blocks the webhook event loop; webhook-side
operations use a short busy timeout (150 ms) per plan task 3.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Iterator

from contextlib import contextmanager

from backend.src.voice_gateway.alice.models import (
    ACTION_CANCEL_REQUEST,
    ACTION_CONFIRM_CANCEL,
    ACTION_DECLINE_CANCEL,
    ACTION_FINISH_DRAFT,
    ACTION_NEXT_REPLY,
    DRAFT_MAX_CHARS,
    MAX_QUEUED_JOBS,
    AliceEvent,
    AliceJob,
    AliceReply,
    JOB_STATUSES,
)
from backend.src.voice_gateway.text_turns import TextTurnRequest, TextTurnResult
from backend.src.voice_gateway.alice.render import chunk_text, render_reply

#: Short busy timeout for webhook-path operations (plan task 3: ≤150 ms).
WEBHOOK_BUSY_TIMEOUT_MS = 150

#: Worker operations may wait longer for a busy database.
WORKER_BUSY_TIMEOUT_MS = 5_000

#: One draft per owner (plan task 3).
DRAFT_OPEN = "open"
DRAFT_CLOSED = "closed"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    key TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    reply_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS drafts (
    owner TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    target_id TEXT,
    text TEXT NOT NULL DEFAULT '',
    fragments INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS draft_confirmations (
    owner TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    reply TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS reply_cursors (
    owner TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    page_index INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_owner_status ON jobs(owner, status, created_at);
"""


def payload_hash(event: AliceEvent) -> str:
    """Stable content hash for idempotency checks (never includes tokens)."""
    encoded = json.dumps(
        {"action": event.action, "text": event.text, "skill_id": event.skill_id,
         "session_id": event.session_id, "message_id": event.message_id},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class DraftOverflow(Exception):
    """Draft would exceed the 12 000 character limit; nothing was accepted."""


class QueueFull(Exception):
    """More than the bounded number of queued jobs was requested."""


class EventConflict(Exception):
    """Same idempotency key arrived with different content."""


class AliceStore:
    def __init__(self, database: Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connect(self, timeout_ms: int) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=timeout_ms / 1000,
                                     isolation_level=None)
        os.chmod(self.database, 0o600)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {timeout_ms}")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect(WORKER_BUSY_TIMEOUT_MS) as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Event acceptance (webhook path)
    # ------------------------------------------------------------------

    def accept(self, event: AliceEvent, reply: AliceReply) -> AliceReply:
        """Record event + dialogue transition + reply in one transaction.

        Returns the reply to send: the freshly built one on first delivery,
        the stored one on replay. Raises :class:`EventConflict` when the
        same key arrives with different content.
        """
        digest = payload_hash(event)
        with self._connect(WEBHOOK_BUSY_TIMEOUT_MS) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                stored = db.execute("SELECT reply_json, payload_hash FROM events WHERE key=?",
                                    (event.key(),)).fetchone()
                if stored is not None:
                    if stored["payload_hash"] != digest:
                        raise EventConflict("same key with different payload")
                    return AliceReply(**json.loads(stored["reply_json"]))
                transition = self._apply_event(db, event)
                reply = transition or reply
                db.execute("INSERT INTO events(key, owner, payload_hash, reply_json) VALUES (?,?,?,?)",
                           (event.key(), event.owner, digest, json.dumps(
                               {"text": reply.text, "tts": reply.tts,
                                "end_session": reply.end_session, "extra": reply.extra},
                               ensure_ascii=False)))
                db.execute("COMMIT")
                return reply
            except Exception:
                db.execute("ROLLBACK")
                raise

    def _apply_event(self, db: sqlite3.Connection, event: AliceEvent) -> AliceReply | None:
        """Apply the dialogue transition; None keeps the caller's reply."""
        draft = db.execute("SELECT * FROM drafts WHERE owner=?", (event.owner,)).fetchone()
        if event.action == "new_idea":
            # Direct capture/amend/query: the whole utterance is one task.
            self._create_job(db, event, event.text, None)
        elif event.action == "verbatim":
            # "Запиши дословно: …" — same as new_idea with literal text.
            self._create_job(db, event, event.text, None)
        elif event.action == "append_draft":
            if draft is None or draft["status"] != DRAFT_OPEN:
                raise EventConflict("no open draft for fragment")
            combined = draft["text"] + ("\n" if draft["text"] else "") + event.text
            if len(combined) > DRAFT_MAX_CHARS:
                # Overflow refuses the fragment; the draft keeps its previous
                # text and the client is told, never silently truncated.
                raise DraftOverflow("draft would exceed the character limit")
            db.execute("UPDATE drafts SET text=?, fragments=fragments+1, "
                       "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE owner=?",
                       (combined, event.owner))
            db.execute("DELETE FROM draft_confirmations WHERE owner=?", (event.owner,))
        elif event.action == "start_draft":
            if draft is not None and draft["status"] == DRAFT_OPEN:
                return AliceReply(text="Продолжаем запись. Диктуйте дальше.")
            db.execute("INSERT INTO drafts(owner, status, text, fragments) VALUES (?, 'open', '', 0) "
                       "ON CONFLICT(owner) DO UPDATE SET status='open', "
                       "text='', fragments=0, "
                       "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                       (event.owner,))
        elif event.action == "resume_draft":
            if draft is None or draft["status"] != DRAFT_OPEN:
                return AliceReply(text="Нет открытого черновика. Скажите «Начни запись».")
        elif event.action == ACTION_CANCEL_REQUEST:
            if draft is None or draft["status"] != DRAFT_OPEN:
                return AliceReply(text="Нет активного черновика.")
            db.execute("INSERT INTO draft_confirmations(owner, action) VALUES (?, 'cancel') "
                       "ON CONFLICT(owner) DO UPDATE SET action='cancel', "
                       "created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')", (event.owner,))
        elif event.action == ACTION_CONFIRM_CANCEL:
            pending = db.execute("SELECT action FROM draft_confirmations WHERE owner=?",
                                 (event.owner,)).fetchone()
            if pending is not None and pending["action"] == "cancel":
                db.execute("DELETE FROM drafts WHERE owner=?", (event.owner,))
                db.execute("DELETE FROM draft_confirmations WHERE owner=?", (event.owner,))
            else:
                return AliceReply(text="Нет ожидающего подтверждения отмены.")
        elif event.action == ACTION_DECLINE_CANCEL:
            db.execute("DELETE FROM draft_confirmations WHERE owner=?", (event.owner,))
        elif event.action == ACTION_NEXT_REPLY:
            latest = db.execute(
                "SELECT job_id, reply FROM jobs WHERE owner=? AND status='done' "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1", (event.owner,)
            ).fetchone()
            if latest is None:
                return AliceReply(text="Пока нет готового ответа.")
            pages = chunk_text(latest["reply"] or "Готово.")
            cursor = db.execute("SELECT job_id, page_index FROM reply_cursors WHERE owner=?",
                                 (event.owner,)).fetchone()
            page_index = cursor["page_index"] if cursor and cursor["job_id"] == latest["job_id"] else 0
            next_index = page_index + 1
            if next_index >= len(pages):
                return render_reply("Это конец ответа.")
            db.execute("INSERT INTO reply_cursors(owner, job_id, page_index) VALUES (?, ?, ?) "
                       "ON CONFLICT(owner) DO UPDATE SET job_id=excluded.job_id, "
                       "page_index=excluded.page_index", (event.owner, latest["job_id"], next_index))
            has_more = next_index + 1 < len(pages)
            text = pages[next_index]
            if has_more:
                text += "\\n(Скажите «Дальше», чтобы продолжить.)"
            return render_reply(text)
        elif event.action == "finish_draft":
            if draft is None or draft["status"] != DRAFT_OPEN:
                return None  # nothing to finish; caller's reply stands
            if not draft["text"].strip():
                # An empty draft closes without creating a job or a note.
                db.execute("DELETE FROM drafts WHERE owner=?", (event.owner,))
                return None
            self._create_job(db, event, draft["text"], draft["target_id"])
            db.execute("DELETE FROM drafts WHERE owner=?", (event.owner,))
        elif event.action == "cancel_draft":
            db.execute("DELETE FROM drafts WHERE owner=?", (event.owner,))
            db.execute("DELETE FROM draft_confirmations WHERE owner=?", (event.owner,))
        return None

    def _create_job(self, db: sqlite3.Connection, event: AliceEvent, text: str,
                    target_id: str | None) -> str:
        queued = db.execute("SELECT COUNT(*) FROM jobs WHERE owner=? AND status='queued'",
                            (event.owner,)).fetchone()[0]
        if queued >= MAX_QUEUED_JOBS:
            raise QueueFull("too many queued jobs")
        job_id = uuid.uuid4().hex
        request = TextTurnRequest(
            request_id=f"alice:{event.session_id}:{event.message_id}",
            turn_id=job_id,
            context_id=event.context_id,
            client_id=event.owner,
            channel="alice",
            transcript=text,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            archive_dir=Path(event.archive_dir) / job_id if event.archive_dir
            else Path("archive/alice") / job_id,
        )
        db.execute("INSERT INTO jobs(job_id, owner, status, request_json) VALUES (?, ?, 'queued', ?)",
                   (job_id, event.owner, json.dumps({
                       "request": {
                           "request_id": request.request_id, "turn_id": request.turn_id,
                           "context_id": request.context_id, "client_id": request.client_id,
                           "channel": request.channel, "transcript": request.transcript,
                           "created_at": request.created_at, "archive_dir": str(request.archive_dir),
                       }}, ensure_ascii=False)))
        return job_id

    # ------------------------------------------------------------------
    # Worker path
    # ------------------------------------------------------------------

    def claim_next(self) -> AliceJob | None:
        """Claim one queued job, marking it running (worker thread)."""
        with self._connect(WORKER_BUSY_TIMEOUT_MS) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT * FROM jobs WHERE status='queued' "
                                 "ORDER BY created_at LIMIT 1").fetchone()
                if row is None:
                    db.execute("COMMIT")
                    return None
                db.execute("UPDATE jobs SET status='running', "
                           "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE job_id=?",
                           (row["job_id"],))
                db.execute("COMMIT")
                return self._job_from_row(row, status="running")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def complete(self, job_id: str, result: TextTurnResult) -> None:
        with self._connect(WORKER_BUSY_TIMEOUT_MS) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("UPDATE jobs SET status=?, reply=?, error_code=NULL, "
                           "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE job_id=?",
                           ("needs_review" if result.receipt and result.receipt.get("status") == "needs_review"
                            else "done",
                            result.reply, job_id))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def fail(self, job_id: str, code: str) -> None:
        with self._connect(WORKER_BUSY_TIMEOUT_MS) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("UPDATE jobs SET status='failed', error_code=?, "
                           "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE job_id=?",
                           (code, job_id))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def recover_running(self) -> None:
        """Return interrupted running jobs to the queue with the same IDs."""
        with self._connect(WORKER_BUSY_TIMEOUT_MS) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("UPDATE jobs SET status='queued' WHERE status='running'")
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    def latest_reply(self, owner: str) -> dict | None:
        """Most recent finished job's reply for the status dialogue."""
        with self._connect(WEBHOOK_BUSY_TIMEOUT_MS) as db:
            row = db.execute("SELECT job_id, status, reply, error_code FROM jobs WHERE owner=? "
                             "AND status IN ('done','failed','needs_review') "
                             "ORDER BY created_at DESC, rowid DESC LIMIT 1", (owner,)).fetchone()
            if row is None:
                return None
            return {"job_id": row["job_id"], "status": row["status"], "reply": row["reply"],
                    "error": row["error_code"]}

    def reply_page(self, owner: str) -> tuple[int, int] | None:
        """Return the current page index and total for the latest completed reply."""
        with self._connect(WEBHOOK_BUSY_TIMEOUT_MS) as db:
            latest = db.execute("SELECT job_id, reply FROM jobs WHERE owner=? AND status='done' "
                                "ORDER BY created_at DESC, rowid DESC LIMIT 1", (owner,)).fetchone()
            if latest is None:
                return None
            cursor = db.execute("SELECT job_id, page_index FROM reply_cursors WHERE owner=?",
                                (owner,)).fetchone()
            index = cursor["page_index"] if cursor and cursor["job_id"] == latest["job_id"] else 0
            return index, len(chunk_text(latest["reply"] or "Готово."))

    def pending_count(self, owner: str) -> int:
        with self._connect(WEBHOOK_BUSY_TIMEOUT_MS) as db:
            row = db.execute("SELECT COUNT(*) FROM jobs WHERE owner=? AND status IN ('queued','running')",
                             (owner,)).fetchone()
            return int(row[0])

    def draft_state(self, owner: str) -> dict | None:
        with self._connect(WEBHOOK_BUSY_TIMEOUT_MS) as db:
            row = db.execute("SELECT status, text, fragments, "
                             "EXISTS(SELECT 1 FROM draft_confirmations c WHERE c.owner=drafts.owner "
                             "AND c.action='cancel') AS cancel_pending FROM drafts WHERE owner=?",
                             (owner,)).fetchone()
            if row is None:
                return None
            return {"status": row["status"], "text": row["text"], "fragments": row["fragments"],
                    "cancel_pending": bool(row["cancel_pending"])}

    def has_pending_cancel(self, owner: str) -> bool:
        with self._connect(WEBHOOK_BUSY_TIMEOUT_MS) as db:
            return db.execute("SELECT 1 FROM draft_confirmations WHERE owner=? AND action='cancel'",
                              (owner,)).fetchone() is not None

    def set_draft_target(self, owner: str, target_id: str) -> None:
        """Freeze the amend target when the owner picks a note to extend."""
        with self._connect(WEBHOOK_BUSY_TIMEOUT_MS) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("UPDATE drafts SET target_id=?, "
                           "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE owner=?",
                           (target_id, owner))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

    @staticmethod
    def _job_from_row(row: sqlite3.Row, status: str | None = None) -> AliceJob:
        payload = json.loads(row["request_json"])
        request = TextTurnRequest(
            request_id=payload["request"]["request_id"],
            turn_id=payload["request"]["turn_id"],
            context_id=payload["request"]["context_id"],
            client_id=payload["request"]["client_id"],
            channel=payload["request"]["channel"],
            transcript=payload["request"]["transcript"],
            created_at=payload["request"]["created_at"],
            archive_dir=Path(payload["request"]["archive_dir"]),
        )
        return AliceJob(
            job_id=row["job_id"],
            status=status or row["status"],
            request=request,
            reply=row["reply"],
            error_code=row["error_code"],
        )
