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
CREATE TABLE IF NOT EXISTS metric_totals (
    metric TEXT NOT NULL,
    labels TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY(metric, labels)
);
"""

_STAGE_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)


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
            unfinished = connection.execute("SELECT * FROM calls WHERE state='started'").fetchall()
            for row in unfinished:
                connection.execute(
                    "UPDATE calls SET state='finished',outcome='unknown',cost_kind='unknown',"
                    "finished_at=? WHERE call_id=?", (time.time(), row["call_id"])
                )
                recovered = connection.execute(
                    "SELECT * FROM calls WHERE call_id=?", (row["call_id"],)
                ).fetchone()
                self._rollup_call(connection, recovered)

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
                updated = connection.execute(
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
                if updated.rowcount:
                    row = connection.execute("SELECT * FROM calls WHERE call_id=?", (call_id,)).fetchone()
                    self._rollup_call(connection, row)
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
            connection.execute("BEGIN IMMEDIATE")
            try:
                previous = connection.execute(
                    "SELECT * FROM turns WHERE turn_id=?", (turn_id,)
                ).fetchone()
                connection.execute(
                    "INSERT INTO turns(turn_id,channel,outcome,operation,note_saved,finished_at) "
                    "VALUES (?,?,?,?,?,?) ON CONFLICT(turn_id) DO UPDATE SET "
                    "outcome=excluded.outcome, operation=CASE WHEN excluded.operation='none' "
                    "THEN turns.operation ELSE excluded.operation END, "
                    "note_saved=MAX(turns.note_saved,excluded.note_saved), finished_at=excluded.finished_at",
                    (turn_id, channel, outcome, operation, int(note_saved), time.time()),
                )
                if outcome != "pending" and (previous is None or previous["outcome"] == "pending"):
                    final = connection.execute(
                        "SELECT * FROM turns WHERE turn_id=?", (turn_id,)
                    ).fetchone()
                    self._increment(connection, "turns", (channel, outcome), 1)
                    if final["operation"] != "none":
                        self._increment(connection, "operations", (channel, final["operation"]), 1)
                    if final["note_saved"] and final["operation"] in ("capture", "amend"):
                        self._increment(connection, "notes", (channel, final["operation"]), 1)
                    if final["note_saved"] and final["operation"] == "capture":
                        self._rollup_completed_capture(connection, turn_id, channel)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def record_stage(self, *, channel: str, stage: str, outcome: str,
                     elapsed_seconds: float) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._rollup_stage(connection, channel, stage, outcome, elapsed_seconds)
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _increment(connection, metric: str, labels: tuple, amount) -> None:
        import json
        key = json.dumps(labels, separators=(",", ":"))
        row = connection.execute(
            "SELECT value FROM metric_totals WHERE metric=? AND labels=?", (metric, key)
        ).fetchone()
        value = Decimal(row[0]) if row else Decimal(0)
        connection.execute(
            "INSERT INTO metric_totals(metric,labels,value) VALUES (?,?,?) "
            "ON CONFLICT(metric,labels) DO UPDATE SET value=excluded.value",
            (metric, key, str(value + Decimal(str(amount)))),
        )

    def _rollup_stage(self, connection, channel, stage, outcome, elapsed) -> None:
        self._increment(connection, "stage_sum", (channel, stage, outcome), elapsed)
        self._increment(connection, "stage_count", (channel, stage, outcome), 1)
        for bound in _STAGE_BUCKETS:
            if elapsed <= bound:
                self._increment(connection, "stage_bucket", (channel, stage, outcome, str(bound)), 1)
        self._increment(connection, "stage_bucket", (channel, stage, outcome, "+Inf"), 1)

    def _rollup_call(self, connection, row) -> None:
        base = (row["channel"], row["stage"], row["model"])
        self._increment(connection, "provider_calls", base + (row["outcome"],), 1)
        if row["cost_amount"] is None:
            self._increment(connection, "usage_unknown", base, 1)
        else:
            self._increment(connection, "provider_cost", base + (
                row["cost_currency"], row["cost_kind"]), row["cost_amount"])
        if row["input_tokens"] is not None:
            self._increment(connection, "usage_tokens", base + ("input",), row["input_tokens"])
        if row["output_tokens"] is not None:
            self._increment(connection, "usage_tokens", base + ("output",), row["output_tokens"])
        if row["elapsed_seconds"] is not None:
            self._rollup_stage(connection, row["channel"], row["stage"], row["outcome"],
                               row["elapsed_seconds"])

    def _rollup_completed_capture(self, connection, turn_id, channel) -> None:
        rows = connection.execute("SELECT * FROM calls WHERE turn_id=?", (turn_id,)).fetchall()
        stages = {row["stage"] for row in rows}
        required = {"llm"} if channel == "alice" else {"stt", "llm", "tts"}
        if (not required <= stages
                or any(row["state"] != "finished" or row["cost_amount"] is None for row in rows)):
            self._increment(connection, "completed_excluded", (channel, "incomplete_usage"), 1)
            return
        currencies = {row["cost_currency"] for row in rows}
        if len(currencies) != 1:
            self._increment(connection, "completed_excluded", (channel, "mixed_currency"), 1)
            return
        currency = currencies.pop()
        kind = "reported" if all(row["cost_kind"] == "reported" for row in rows) else "estimated"
        total = sum((Decimal(row["cost_amount"]) for row in rows), Decimal(0))
        self._increment(connection, "completed_cost", (channel, currency, kind), total)
        self._increment(connection, "completed_count", (channel, currency, kind), 1)

    def metrics_snapshot(self) -> dict:
        import json
        with self._connect() as connection:
            started_at = Decimal(connection.execute(
                "SELECT value FROM metadata WHERE key='started_at'"
            ).fetchone()[0])
            rows = connection.execute("SELECT metric,labels,value FROM metric_totals").fetchall()
        metrics = {}
        for row in rows:
            metrics.setdefault(row["metric"], []).append(
                (tuple(json.loads(row["labels"])), Decimal(row["value"]))
            )
        return {"accounting_started_at": started_at, "metrics": metrics}

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
