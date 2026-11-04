"""Durable, context-scoped clarification state; never a command parser.

A question is evidence, not a publication receipt. Expired/declined/superseded
questions remain in this journal and their original sources are never removed.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


class DialogueStore:
    def __init__(self, path: Path, *, ttl_seconds=900, clock=time.time):
        self.path, self.ttl_seconds, self.clock = Path(path), ttl_seconds, clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS questions (id TEXT PRIMARY KEY, context TEXT, '
                       'source TEXT UNIQUE, payload TEXT, expires REAL, status TEXT)')

    def _db(self):
        db = sqlite3.connect(self.path, timeout=15)
        os.chmod(self.path, 0o600)
        return db

    def pending(self, context):
        with self._db() as db:
            db.execute("UPDATE questions SET status='expired' WHERE context=? AND status='pending' AND expires<=?",
                       (context, self.clock()))
            row = db.execute("SELECT payload FROM questions WHERE context=? AND status='pending' ORDER BY rowid DESC LIMIT 1",
                             (context,)).fetchone()
        return json.loads(row[0]) if row else None

    def reset(self, context):
        with self._db() as db:
            db.execute("UPDATE questions SET status='reset' WHERE context=? AND status='pending'", (context,))

    def for_source(self, source):
        with self._db() as db:
            row = db.execute('SELECT payload FROM questions WHERE source=?', (source,)).fetchone()
        return json.loads(row[0]) if row else None

    def apply(self, context, source, clarification, resolution, pending):
        with self._db() as db:
            old = db.execute('SELECT payload FROM questions WHERE source=?', (source,)).fetchone()
            if old:
                return json.loads(old[0])
            if resolution:
                db.execute("UPDATE questions SET status=? WHERE id=? AND context=? AND status='pending'",
                           (resolution.action, resolution.question_id, context))
            if clarification is None:
                return None
            # An omitted resolution must not bypass the consecutive listen cap.
            depth = (pending['depth'] if pending else 0) + 1
            payload = dict(question_id=str(uuid.uuid5(uuid.NAMESPACE_URL, 'zateya-question:'+source)),
                           question=clarification.question, source_ids=clarification.source_ids,
                           depth=depth, listen=depth <= 3)
            db.execute("UPDATE questions SET status='superseded' WHERE context=? AND status='pending'", (context,))
            db.execute("INSERT INTO questions VALUES (?, ?, ?, ?, ?, 'pending')",
                       (payload['question_id'], context, source, json.dumps(payload, ensure_ascii=False),
                        self.clock()+self.ttl_seconds))
            return payload
