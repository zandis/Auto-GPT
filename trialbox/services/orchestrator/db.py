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
CREATE TABLE IF NOT EXISTS submissions (
  job_id TEXT PRIMARY KEY,
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  nav_job_id TEXT NOT NULL,
  bundle_sha TEXT NOT NULL,
  dry_run INTEGER NOT NULL,
  outcome TEXT NOT NULL,
  submitted_by TEXT NOT NULL,
  submitted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS submissions_bundle ON submissions(bundle_sha, dry_run);
CREATE UNIQUE INDEX IF NOT EXISTS submissions_live_once ON submissions(bundle_sha) WHERE dry_run = 0;
CREATE TABLE IF NOT EXISTS cohort_tables (
  site_id TEXT NOT NULL,
  disease TEXT NOT NULL,
  quarter TEXT NOT NULL,
  criterion_id TEXT NOT NULL,
  definition_version TEXT NOT NULL,
  criterion_label TEXT NOT NULL,
  n TEXT NOT NULL,
  n_contactable TEXT NOT NULL,
  received_from TEXT NOT NULL,
  job_id TEXT NOT NULL,
  PRIMARY KEY (site_id, disease, quarter, criterion_id, definition_version)
);
CREATE TABLE IF NOT EXISTS trial_cache (
  nct_id TEXT NOT NULL,
  last_update TEXT NOT NULL,
  version TEXT NOT NULL,
  draft_zip_key TEXT NOT NULL,
  equivalence_pct REAL,
  compiled_at TEXT NOT NULL,
  PRIMARY KEY (nct_id, last_update)
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

    _SUB_COLS = ("job_id", "ruleset", "pid", "nav_job_id", "bundle_sha", "dry_run", "outcome", "submitted_by", "at")

    def submission_reserve(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """Claim a bundle for one live NHI submission before it is sent: inserts ``row`` (outcome ``pending``) and
        returns None, or returns the existing live submission of the same bundle and inserts nothing. Atomic under
        the DB lock; the partial unique index ``submissions_live_once`` backs it up."""
        with self.tx() as con:
            prior = con.execute(
                "SELECT job_id, ruleset, pid, nav_job_id, bundle_sha, dry_run, outcome, submitted_by, submitted_at "
                "FROM submissions WHERE bundle_sha = ? AND dry_run = 0",
                (row["bundle_sha"],),
            ).fetchone()
            if prior is not None:
                return dict(zip(self._SUB_COLS, prior, strict=True))
            self._submission_insert(con, {**row, "dry_run": False}, replace=False)
        return None

    def submission_update(self, job_id: str, outcome: str, submitted_at: str | None = None) -> None:
        with self.tx() as con:
            con.execute(
                "UPDATE submissions SET outcome = ?, submitted_at = coalesce(?, submitted_at) WHERE job_id = ?",
                (outcome, submitted_at, job_id),
            )

    def submission_release(self, job_id: str) -> None:
        """Drop a live reservation whose bundle provably never reached NHI (connection refused, HTTP 4xx)."""
        with self.tx() as con:
            con.execute("DELETE FROM submissions WHERE job_id = ? AND dry_run = 0", (job_id,))

    def submission_add(self, row: dict[str, Any]) -> None:
        """Record a dry run (idempotent per job: a re-run after a restart replaces the row)."""
        with self.tx() as con:
            self._submission_insert(con, row, replace=True)

    @staticmethod
    def _submission_insert(con: sqlite3.Connection, row: dict[str, Any], replace: bool) -> None:
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        con.execute(
            f"""{verb} INTO submissions (job_id, ruleset, pid, nav_job_id, bundle_sha, dry_run, outcome,
                 submitted_by, submitted_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                row["job_id"],
                row["ruleset"],
                row["pid"],
                row["nav_job_id"],
                row["bundle_sha"],
                int(bool(row["dry_run"])),
                row["outcome"],
                row["submitted_by"],
                row["submitted_at"],
            ),
        )

    def submissions(self, bundle_sha: str | None = None, live_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT job_id, ruleset, pid, nav_job_id, bundle_sha, dry_run, outcome, submitted_by, submitted_at "
        sql += "FROM submissions WHERE (? IS NULL OR bundle_sha = ?)" + (" AND dry_run = 0" if live_only else "")
        with self._lock:
            rows = self._con.execute(sql + " ORDER BY submitted_at", (bundle_sha, bundle_sha)).fetchall()
        return [dict(zip(self._SUB_COLS, r, strict=True)) for r in rows]

    def prune_inactive(self, approved: set[str], cutoff_iso: str) -> dict[str, int]:
        """Retention (SPEC §10.3): pool / feedback rows of rulesets no longer approved here, untouched since cutoff."""
        keep = sorted(approved) or [""]
        marks = ",".join("?" for _ in keep)
        with self.tx() as con:
            pool = con.execute(
                f"DELETE FROM pool WHERE ruleset NOT IN ({marks}) AND last_eval < ?", (*keep, cutoff_iso)
            ).rowcount
            feedback = con.execute(
                f"DELETE FROM feedback WHERE ruleset NOT IN ({marks}) AND received_at < ?", (*keep, cutoff_iso)
            ).rowcount
        return {"pool": int(pool), "feedback": int(feedback)}

    # ------------------------------------------------------------------ alliance cohort tables (COHORT MERGE)
    _COHORT_COLS = (
        "site_id",
        "disease",
        "quarter",
        "criterion_id",
        "criterion_label",
        "n",
        "n_contactable",
        "definition_version",
    )

    def cohort_store(self, rows: list[dict[str, Any]], job_id: str, received_from: str) -> None:
        """Replace a site's table for each (disease, quarter, definition) it contains, then insert the rows."""
        with self.tx() as con:
            for site, disease, quarter, version in {
                (r["site_id"], r["disease"], r["quarter"], r["definition_version"]) for r in rows
            }:
                con.execute(
                    "DELETE FROM cohort_tables WHERE site_id=? AND disease=? AND quarter=? AND definition_version=?",
                    (site, disease, quarter, version),
                )
            for r in rows:
                con.execute(
                    """INSERT INTO cohort_tables (site_id, disease, quarter, criterion_id, definition_version,
                         criterion_label, n, n_contactable, received_from, job_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r["site_id"],
                        r["disease"],
                        r["quarter"],
                        r["criterion_id"],
                        r["definition_version"],
                        r["criterion_label"],
                        json.dumps(r["n"]),
                        json.dumps(r["n_contactable"]),
                        received_from,
                        job_id,
                    ),
                )

    def cohort_senders(self, site_id: str) -> set[str]:
        """Who has contributed tables for ``site_id`` (``self:<site>`` for the root's own runs)."""
        with self._lock:
            rows = self._con.execute(
                "SELECT DISTINCT received_from FROM cohort_tables WHERE site_id = ?", (site_id,)
            ).fetchall()
        return {str(r[0]) for r in rows}

    def cohort_rows(self, disease: str, quarter: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._con.execute(
                f"SELECT {', '.join(self._COHORT_COLS)} FROM cohort_tables WHERE disease=? AND quarter=? "
                "ORDER BY site_id, rowid",
                (disease, quarter),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(zip(self._COHORT_COLS, r, strict=True))
            d["n"], d["n_contactable"] = json.loads(d["n"]), json.loads(d["n_contactable"])
            out.append(d)
        return out

    # ------------------------------------------------------------------ CT.gov compile cache (COHORT trial sim)
    def trial_cache_put(self, row: dict[str, Any]) -> None:
        with self.tx() as con:
            con.execute(
                """INSERT OR REPLACE INTO trial_cache (nct_id, last_update, version, draft_zip_key, equivalence_pct,
                     compiled_at) VALUES (?,?,?,?,?,?)""",
                (
                    row["nct_id"],
                    row["last_update"],
                    row["version"],
                    row["draft_zip_key"],
                    row.get("equivalence_pct"),
                    row["compiled_at"],
                ),
            )

    def trial_cache_all(self) -> list[dict[str, Any]]:
        cols = ("nct_id", "last_update", "version", "draft_zip_key", "equivalence_pct", "compiled_at")
        with self._lock:
            rows = self._con.execute(f"SELECT {', '.join(cols)} FROM trial_cache ORDER BY nct_id").fetchall()
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def trial_cache_get(self, nct_id: str, last_update: str) -> dict[str, Any] | None:
        cols = ("nct_id", "last_update", "version", "draft_zip_key", "equivalence_pct", "compiled_at")
        with self._lock:
            r = self._con.execute(
                f"SELECT {', '.join(cols)} FROM trial_cache WHERE nct_id=? AND last_update=?", (nct_id, last_update)
            ).fetchone()
        return dict(zip(cols, r, strict=True)) if r else None

    def close(self) -> None:
        with self._lock:
            self._con.close()
