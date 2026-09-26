"""Durable, device-scoped LLM result cache and bounded conversation history."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class IdempotencyConflict(ValueError):
    """A request ID was reused for different input."""


@dataclass(frozen=True, slots=True)
class SessionStart:
    generation: int
    cached: dict | None


class AgentSessionStore:
    def __init__(self, database: str | Path, *, history_turns: int = 6,
                 history_max_chars: int = 12000) -> None:
        self.database = Path(database)
        self.history_turns = history_turns
        self.history_max_chars = history_max_chars

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=15, isolation_level=None)
        os.chmod(self.database, 0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 15000")
        try:
            yield connection
        finally:
            connection.close()
            for suffix in ("", "-wal", "-shm"):
                path = Path(str(self.database) + suffix)
                if path.exists():
                    os.chmod(path, 0o600)

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS generations (
                    device_id TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL CHECK(generation > 0)
                );
                CREATE TABLE IF NOT EXISTS results (
                    device_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    result_json TEXT,
                    history_committed INTEGER NOT NULL DEFAULT 0,
                    transcript TEXT,
                    final_reply TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    PRIMARY KEY(device_id, request_id)
                );
                CREATE INDEX IF NOT EXISTS results_history
                    ON results(device_id, generation, history_committed, created_at);
            """)

    def begin(self, device_id: str, request_id: str, input_hash: str) -> SessionStart:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO generations(device_id, generation) VALUES (?, 1)",
                (device_id,),
            )
            generation = int(connection.execute(
                "SELECT generation FROM generations WHERE device_id = ?", (device_id,)
            ).fetchone()[0])
            row = connection.execute(
                "SELECT input_hash, generation, result_json FROM results "
                "WHERE device_id = ? AND request_id = ?", (device_id, request_id)
            ).fetchone()
            if row is not None:
                if row["input_hash"] != input_hash:
                    connection.rollback()
                    raise IdempotencyConflict("request ID was reused with different input")
                if int(row["generation"]) == generation and row["result_json"] is not None:
                    cached = json.loads(row["result_json"])
                    connection.commit()
                    return SessionStart(generation, cached)
                connection.execute(
                    "DELETE FROM results WHERE device_id = ? AND request_id = ?",
                    (device_id, request_id),
                )
            connection.execute(
                "INSERT OR IGNORE INTO results(device_id, request_id, input_hash, generation, result_json) "
                "VALUES (?, ?, ?, ?, NULL)", (device_id, request_id, input_hash, generation)
            )
            connection.commit()
            return SessionStart(generation, None)

    def history(self, device_id: str) -> list[dict[str, str]]:
        if self.history_turns == 0:
            return []
        with self._connect() as connection:
            rows = connection.execute("""
                SELECT r.transcript, r.final_reply FROM results r
                JOIN generations g ON g.device_id = r.device_id AND g.generation = r.generation
                WHERE r.device_id = ? AND r.history_committed = 1
                ORDER BY r.created_at DESC, r.request_id DESC LIMIT ?
            """, (device_id, self.history_turns)).fetchall()
        pairs = list(reversed(rows))
        messages: list[dict[str, str]] = []
        for row in pairs:
            messages.extend(({"role": "user", "content": row["transcript"]},
                             {"role": "assistant", "content": row["final_reply"]}))
        while messages and sum(len(message["content"]) for message in messages) > self.history_max_chars:
            messages = messages[2:]
        return messages

    def save_result(self, device_id: str, request_id: str, generation: int, result: dict) -> None:
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT generation FROM generations WHERE device_id = ?", (device_id,)
            ).fetchone()
            if current is None or int(current[0]) != generation:
                connection.rollback()
                return
            connection.execute(
                "UPDATE results SET result_json = ? WHERE device_id = ? AND request_id = ? "
                "AND generation = ?", (encoded, device_id, request_id, generation)
            )
            connection.commit()

    def record_turn(self, device_id: str, request_id: str, transcript: str,
                    final_reply: str, generation: int | None = None) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT generation, history_committed FROM results "
                "WHERE device_id = ? AND request_id = ?", (device_id, request_id)
            ).fetchone()
            current = connection.execute(
                "SELECT generation FROM generations WHERE device_id = ?", (device_id,)
            ).fetchone()
            if row is None or current is None:
                connection.rollback()
                return False
            row_generation = int(row["generation"])
            if (generation is not None and generation != row_generation) or int(current[0]) != row_generation:
                connection.rollback()
                return False
            if row["history_committed"]:
                connection.commit()
                return True
            connection.execute(
                "UPDATE results SET history_committed = 1, transcript = ?, final_reply = ? "
                "WHERE device_id = ? AND request_id = ? AND generation = ?",
                (transcript, final_reply, device_id, request_id, row_generation),
            )
            connection.commit()
            return True

    def reset(self, device_id: str) -> int:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO generations(device_id, generation) VALUES (?, 1) "
                "ON CONFLICT(device_id) DO UPDATE SET generation = generation + 1",
                (device_id,),
            )
            generation = int(connection.execute(
                "SELECT generation FROM generations WHERE device_id = ?", (device_id,)
            ).fetchone()[0])
            connection.commit()
            return generation


def input_digest(transcript: str, knowledge_context: dict | None) -> str:
    encoded = json.dumps(
        {"transcript": transcript, "knowledge_context": knowledge_context or {}},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
