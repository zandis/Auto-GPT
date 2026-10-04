"""mail-gateway state (``/data/mail/mail.sqlite``): intake log (idempotency + rate limit) and sent-message index
(reply-to-thread matching)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS intake (
  message_id TEXT PRIMARY KEY,
  sender TEXT NOT NULL,
  received_at TEXT NOT NULL,
  action TEXT NOT NULL,            -- job | reject | pending
  job_id TEXT,
  reason TEXT
);
CREATE INDEX IF NOT EXISTS intake_sender ON intake(sender, received_at);
CREATE TABLE IF NOT EXISTS sent (
  message_id TEXT PRIMARY KEY,
  job_id TEXT,
  subject TEXT NOT NULL,
  recipients TEXT NOT NULL,
  tag TEXT NOT NULL,
  sent_at TEXT NOT NULL
);
"""


class MailDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.executescript(SCHEMA)

    def intake(self, message_id: str) -> tuple[str, str | None] | None:
        with self._lock:
            row = self._con.execute("SELECT action, job_id FROM intake WHERE message_id = ?", (message_id,)).fetchone()
        return (str(row[0]), row[1]) if row else None

    def record_intake(
        self, message_id: str, sender: str, at: str, action: str, job_id: str | None, reason: str | None = None
    ) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO intake (message_id, sender, received_at, action, job_id, reason) "
                "VALUES (?,?,?,?,?,?)",
                (message_id, sender, at, action, job_id, reason),
            )

    def jobs_since(self, sender: str, since_iso: str) -> int:
        with self._lock:
            row = self._con.execute(
                "SELECT count(*) FROM intake WHERE sender = ? AND action = 'job' AND received_at >= ?",
                (sender, since_iso),
            ).fetchone()
        return int(row[0])

    def record_sent(
        self, message_id: str, job_id: str | None, subject: str, recipients: list[str], tag: str, at: str
    ) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO sent (message_id, job_id, subject, recipients, tag, sent_at) "
                "VALUES (?,?,?,?,?,?)",
                (message_id, job_id, subject, ",".join(recipients), tag, at),
            )

    def sent(self, message_id: str) -> tuple[str | None, str] | None:
        with self._lock:
            row = self._con.execute("SELECT job_id, subject FROM sent WHERE message_id = ?", (message_id,)).fetchone()
        return (row[0], str(row[1])) if row else None
