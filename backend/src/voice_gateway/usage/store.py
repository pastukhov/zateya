from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from .models import CallContext, Cost, UsageObservation


_SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    attempt TEXT NOT NULL,
    state TEXT NOT NULL,
    outcome TEXT,
    elapsed_seconds REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    audio_seconds TEXT,
    text_characters INTEGER,
    reported_amount TEXT,
    reported_currency TEXT,
    cost_amount TEXT,
    cost_currency TEXT,
    cost_kind TEXT,
    started_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS calls_turn_id ON calls(turn_id);
CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    outcome TEXT NOT NULL,
    operation TEXT NOT NULL,
    note_saved INTEGER NOT NULL,
    finished_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    stage TEXT NOT NULL,
    outcome TEXT NOT NULL,
    elapsed_seconds REAL NOT NULL
);
"""


class UsageStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=0.15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=150")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES ('started_at', ?)",
                (str(time.time()),),
            )

    def begin_call(self, context: CallContext) -> str:
        call_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO calls(call_id,turn_id,channel,stage,model,attempt,state,started_at) "
                    "VALUES (?,?,?,?,?,?,'started',?)",
                    (call_id, context.turn_id, context.channel, context.stage, context.model,
                     context.attempt, time.time()),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return call_id

    def finish_call(
        self,
        call_id: str,
        *,
        outcome: str,
        elapsed_seconds: float,
        usage: UsageObservation,
        cost: Cost,
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "UPDATE calls SET state='finished',outcome=?,elapsed_seconds=?,"
                    "input_tokens=?,output_tokens=?,audio_seconds=?,text_characters=?,"
                    "reported_amount=?,reported_currency=?,cost_amount=?,cost_currency=?,"
                    "cost_kind=?,finished_at=? WHERE call_id=? AND state='started'",
                    (
                        outcome, elapsed_seconds, usage.input_tokens, usage.output_tokens,
                        _decimal_text(usage.audio_seconds), usage.text_characters,
                        _decimal_text(usage.reported_amount), usage.reported_currency,
                        _decimal_text(cost.amount), cost.currency, cost.kind, time.time(), call_id,
                    ),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def finish_turn(
        self,
        turn_id: str,
        *,
        channel: str,
        outcome: str,
        operation: str,
        note_saved: bool,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO turns(turn_id,channel,outcome,operation,note_saved,finished_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(turn_id) DO UPDATE SET "
                "outcome=excluded.outcome, operation=CASE WHEN excluded.operation='none' "
                "THEN turns.operation ELSE excluded.operation END, "
                "note_saved=MAX(turns.note_saved,excluded.note_saved), finished_at=excluded.finished_at",
                (turn_id, channel, outcome, operation, int(note_saved), time.time()),
            )

    def record_stage(self, *, channel: str, stage: str, outcome: str,
                     elapsed_seconds: float) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO stage_events(channel,stage,outcome,elapsed_seconds) VALUES (?,?,?,?)",
                (channel, stage, outcome, elapsed_seconds),
            )

    def snapshot(self) -> dict:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM calls ORDER BY started_at, call_id").fetchall()
            started_at = Decimal(connection.execute(
                "SELECT value FROM metadata WHERE key='started_at'"
            ).fetchone()[0])
            turns = [dict(row) for row in connection.execute("SELECT * FROM turns")]
            stage_events = [dict(row) for row in connection.execute("SELECT * FROM stage_events")]
        totals: dict[tuple[str, str, str, str, str], Decimal] = {}
        finished = 0
        unknown = 0
        for row in rows:
            if row["state"] != "finished":
                unknown += 1
                continue
            finished += 1
            if row["cost_amount"] is None:
                unknown += 1
                continue
            key = (row["channel"], row["stage"], row["model"],
                   row["cost_currency"], row["cost_kind"])
            totals[key] = totals.get(key, Decimal(0)) + Decimal(row["cost_amount"])
        return {
            "accounting_started_at": started_at,
            "calls": [dict(row) for row in rows],
            "turns": turns,
            "stage_events": stage_events,
            "finished_calls": finished,
            "unknown_calls": unknown,
            "cost_totals": totals,
        }


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
