"""Job queue and orchestrator state in SQLite (SPEC §4.8: ``jobs`` mirrors the Job contract §3.5)."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from tb_contracts import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  state TEXT NOT NULL,
  ruleset TEXT,
  ruleset_version TEXT,
  requested_by TEXT NOT NULL,
  received_at TEXT NOT NULL,
  updated_at TEXT,
  message_id TEXT,
  parent_job_id TEXT,
  queued INTEGER NOT NULL DEFAULT 0,
  cancel INTEGER NOT NULL DEFAULT 0,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS jobs_ruleset ON jobs(ruleset, ruleset_version, state);
CREATE INDEX IF NOT EXISTS jobs_queued ON jobs(queued, received_at);
CREATE TABLE IF NOT EXISTS mails (
  message_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  subject TEXT NOT NULL,
  sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mails_job ON mails(job_id);
CREATE TABLE IF NOT EXISTS pool (
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  version TEXT NOT NULL,
  tier TEXT NOT NULL,
  next_appointment TEXT,
  practitioner_id TEXT,
  department TEXT,
  verdicts TEXT NOT NULL,
  added_at TEXT NOT NULL,
  last_eval TEXT NOT NULL,
  job_id TEXT NOT NULL,
  PRIMARY KEY (ruleset, pid)
);
CREATE TABLE IF NOT EXISTS feedback (
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  outcome TEXT NOT NULL,
  reason_code TEXT,
  note TEXT,
  job_id TEXT NOT NULL,
  received_at TEXT NOT NULL,
  PRIMARY KEY (ruleset, pid)
);
"""

TERMINAL = ("done", "failed")


class JobDB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA busy_timeout=5000")
        self._con.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._con.execute("BEGIN IMMEDIATE")
            try:
                yield self._con
            except BaseException:
                self._con.execute("ROLLBACK")
                raise
            self._con.execute("COMMIT")

    # ------------------------------------------------------------------ jobs
    def put(self, job: Job, queued: bool | None = None) -> None:
        data = job.model_dump_json(by_alias=True, exclude_none=True)
        with self.tx() as con:
            con.execute(
                """INSERT INTO jobs (job_id, type, state, ruleset, ruleset_version, requested_by, received_at,
                                     updated_at, message_id, parent_job_id, queued, data)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET type=excluded.type, state=excluded.state,
                     ruleset=excluded.ruleset, ruleset_version=excluded.ruleset_version, updated_at=excluded.updated_at,
                     message_id=excluded.message_id, parent_job_id=excluded.parent_job_id, data=excluded.data,
                     queued=CASE WHEN ? IS NULL THEN jobs.queued ELSE excluded.queued END""",
                (
                    job.job_id,
                    job.type,
                    job.state,
                    job.ruleset,
                    job.ruleset_version,
                    job.requested_by,
                    job.received_at.isoformat(),
                    job.updated_at.isoformat() if job.updated_at else None,
                    job.message_id,
                    job.parent_job_id,
                    1 if queued else 0,
                    data,
                    queued,
                ),
            )

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._con.execute("SELECT data FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def find(
        self,
        *,
        state: str | None = None,
        ruleset: str | None = None,
        version: str | None = None,
        type_: str | None = None,
        message_id: str | None = None,
        limit: int = 100,
    ) -> list[Job]:
        where, args = [], []
        for col, val in (
            ("state", state),
            ("ruleset", ruleset),
            ("ruleset_version", version),
            ("type", type_),
            ("message_id", message_id),
        ):
            if val is not None:
                where.append(f"{col} = ?")
                args.append(val)
        sql = "SELECT data FROM jobs" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY received_at DESC, job_id DESC LIMIT ?"
        with self._lock:
            rows = self._con.execute(sql, [*args, limit]).fetchall()
        return [Job.model_validate_json(r[0]) for r in rows]

    def claim(self) -> str | None:
        with self.tx() as con:
            row = con.execute(
                "SELECT job_id FROM jobs WHERE queued = 1 ORDER BY received_at, job_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            con.execute("UPDATE jobs SET queued = 0 WHERE job_id = ?", (row[0],))
            return str(row[0])

    def enqueue(self, job_id: str) -> None:
        with self.tx() as con:
            con.execute("UPDATE jobs SET queued = 1, cancel = 0 WHERE job_id = ?", (job_id,))

    def request_cancel(self, job_id: str) -> None:
        with self.tx() as con:
            con.execute("UPDATE jobs SET cancel = 1, queued = 0 WHERE job_id = ?", (job_id,))

    def cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            row = self._con.execute("SELECT cancel FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return bool(row and row[0])

    def interrupted(self) -> list[str]:
        """Jobs left mid-flight by a restart (not terminal, not waiting for approval, not queued)."""
        with self._lock:
            rows = self._con.execute(
                "SELECT job_id FROM jobs WHERE queued = 0 AND state NOT IN ('done','failed','awaiting_approval') "
                "ORDER BY received_at"
            ).fetchall()
        return [str(r[0]) for r in rows]

    def count_since(self, requested_by: str, since_iso: str) -> int:
        with self._lock:
            row = self._con.execute(
                "SELECT count(*) FROM jobs WHERE requested_by = ? AND received_at >= ?", (requested_by, since_iso)
            ).fetchone()
        return int(row[0])

    # ------------------------------------------------------------------ outbound mail index (reply-to-thread)
    def add_mail(self, message_id: str, job_id: str, kind: str, subject: str, sent_at: str) -> None:
        with self.tx() as con:
            con.execute(
                "INSERT OR REPLACE INTO mails (message_id, job_id, kind, subject, sent_at) VALUES (?,?,?,?,?)",
                (message_id, job_id, kind, subject, sent_at),
            )

    def mail(self, message_id: str) -> tuple[str, str, str] | None:
        with self._lock:
            row = self._con.execute(
                "SELECT job_id, kind, subject FROM mails WHERE message_id = ?", (message_id,)
            ).fetchone()
        return (str(row[0]), str(row[1]), str(row[2])) if row else None

    # ------------------------------------------------------------------ candidate pool (SPEC §8.2)
    def pool_upsert(self, ruleset: str, version: str, rows: list[dict[str, Any]], job_id: str, at: str) -> None:
        with self.tx() as con:
            for r in rows:
                con.execute(
                    """INSERT INTO pool (ruleset, pid, version, tier, next_appointment, practitioner_id, department,
                                         verdicts, added_at, last_eval, job_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(ruleset, pid) DO UPDATE SET version=excluded.version, tier=excluded.tier,
                         next_appointment=excluded.next_appointment, practitioner_id=excluded.practitioner_id,
                         department=excluded.department, verdicts=excluded.verdicts, last_eval=excluded.last_eval,
                         job_id=excluded.job_id""",
                    (
                        ruleset,
                        r["pid"],
                        version,
                        r["tier"],
                        r.get("next_appointment"),
                        r.get("practitioner_id"),
                        r.get("department"),
                        json.dumps(r["verdicts"], sort_keys=True),
                        at,
                        at,
                        job_id,
                    ),
                )

    def pool(self, ruleset: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._con.execute(
                "SELECT pid, version, tier, next_appointment, practitioner_id, department, verdicts, added_at, "
                "last_eval, job_id FROM pool WHERE ruleset = ? ORDER BY pid",
                (ruleset,),
            ).fetchall()
        keys = (
            "pid",
            "version",
            "tier",
            "next_appointment",
            "practitioner_id",
            "department",
            "verdicts",
            "added_at",
            "last_eval",
            "job_id",
        )
        out = []
        for r in rows:
            d = dict(zip(keys, r, strict=True))
            d["verdicts"] = json.loads(d["verdicts"])
            out.append(d)
        return out

    def pool_rulesets(self) -> list[str]:
        with self._lock:
            return [str(r[0]) for r in self._con.execute("SELECT DISTINCT ruleset FROM pool ORDER BY 1")]

    def feedback_upsert(self, ruleset: str, rows: list[dict[str, Any]], job_id: str, at: str) -> None:
        with self.tx() as con:
            for r in rows:
                con.execute(
                    """INSERT INTO feedback (ruleset, pid, outcome, reason_code, note, job_id, received_at)
                       VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(ruleset, pid) DO UPDATE SET outcome=excluded.outcome,
                         reason_code=excluded.reason_code, note=excluded.note, job_id=excluded.job_id,
                         received_at=excluded.received_at""",
                    (ruleset, r["pid"], r["outcome"], r.get("reason_code"), r.get("note"), job_id, at),
                )

    def feedback(self, ruleset: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._con.execute(
                "SELECT pid, outcome, reason_code, note, received_at FROM feedback WHERE ruleset = ? ORDER BY pid",
                (ruleset,),
            ).fetchall()
        return [dict(zip(("pid", "outcome", "reason_code", "note", "received_at"), r, strict=True)) for r in rows]

    def feedback_rulesets(self) -> list[str]:
        with self._lock:
            return [str(r[0]) for r in self._con.execute("SELECT DISTINCT ruleset FROM feedback ORDER BY 1")]

    def close(self) -> None:
        with self._lock:
            self._con.close()
