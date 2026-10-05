"""Small bounded SQLite inbox for device reports."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .models import DeviceDiagnostics


class DiagnosticConflict(Exception):
    pass


class DiagnosticsStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS device_diagnostics (
                    device_id TEXT NOT NULL,
                    boot_id INTEGER NOT NULL,
                    sequence INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (device_id, boot_id, sequence)
                )
            """)
            with db:
                yield db
        finally:
            db.close()

    def save(self, device_id: str, report: DeviceDiagnostics) -> None:
        payload = report.model_dump_json()
        now = int(time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT payload FROM device_diagnostics WHERE device_id=? AND boot_id=? AND sequence=?",
                (device_id, report.boot_id, report.sequence),
            ).fetchone()
            if old is not None:
                if old[0] != payload:
                    raise DiagnosticConflict
                return
            db.execute(
                "INSERT INTO device_diagnostics VALUES (?,?,?,?,?)",
                (device_id, report.boot_id, report.sequence, now, payload),
            )
            db.execute("DELETE FROM device_diagnostics WHERE created_at < ?", (now - 7 * 86400,))
            db.execute("""
                DELETE FROM device_diagnostics WHERE rowid IN (
                    SELECT rowid FROM device_diagnostics WHERE device_id=?
                    ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET 20
                )
            """, (device_id,))

    def count(self, device_id: str) -> int:
        with self._connect() as db:
            return db.execute(
                "SELECT COUNT(*) FROM device_diagnostics WHERE device_id=?",
                (device_id,),
            ).fetchone()[0]
