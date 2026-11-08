"""Job queue and orchestrator state (SPEC §4.8: ``jobs`` mirrors the Job contract §3.5).

Schema ``orch`` of the trial database (PostgreSQL ``trialbox_wf``, D-126; :mod:`tb_common.db`)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from tb_common.db import ENV as DB_URL_ENV
from tb_common.db import Database, Tx
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
  queued BIGINT NOT NULL DEFAULT 0,
  cancel BIGINT NOT NULL DEFAULT 0,
  data TEXT NOT NULL,
  seq BIGINT GENERATED ALWAYS AS IDENTITY
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
CREATE TABLE IF NOT EXISTS candidates (
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  status TEXT NOT NULL,
  reason TEXT,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  source TEXT NOT NULL,
  source_job TEXT,
  tier TEXT,
  events BIGINT NOT NULL DEFAULT 1,
  PRIMARY KEY (ruleset, pid)
);
CREATE TABLE IF NOT EXISTS candidate_events (
  seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  status TEXT NOT NULL,
  previous TEXT,
  reason TEXT,
  at TEXT NOT NULL,
  by TEXT NOT NULL,
  source_job TEXT
);
CREATE INDEX IF NOT EXISTS candidate_events_pid ON candidate_events (ruleset, pid, seq);
CREATE TABLE IF NOT EXISTS submissions (
  job_id TEXT PRIMARY KEY,
  ruleset TEXT NOT NULL,
  pid TEXT NOT NULL,
  nav_job_id TEXT NOT NULL,
  bundle_sha TEXT NOT NULL,
  dry_run BIGINT NOT NULL,
  outcome TEXT NOT NULL,
  submitted_by TEXT NOT NULL,
  submitted_at TEXT NOT NULL,
  seq BIGINT GENERATED ALWAYS AS IDENTITY
);
CREATE INDEX IF NOT EXISTS submissions_bundle ON submissions(bundle_sha, dry_run);
CREATE UNIQUE INDEX IF NOT EXISTS submissions_live_once ON submissions(bundle_sha) WHERE dry_run = 0;
CREATE TABLE IF NOT EXISTS cohort_tables (
  seq BIGINT GENERATED ALWAYS AS IDENTITY,
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
  equivalence_pct DOUBLE PRECISION,
  compiled_at TEXT NOT NULL,
  PRIMARY KEY (nct_id, last_update)
);
"""
#: ``migrate`` versions of schema ``orch`` (append-only; version 1 is the schema as it was on SQLite, with an identity
#: ``seq`` on ``jobs``, ``submissions`` and ``cohort_tables`` for the insertion order SQLite's rowid gave to ties)
MIGRATIONS = (SCHEMA,)
SCHEMA_NAME = "orch"

TERMINAL = ("done", "failed")


class JobDB:
    def __init__(self, url: str | None = None, *, schema: str = SCHEMA_NAME) -> None:
        """``url``: the trial database (``TB_DB_URL`` when None; :class:`tb_common.db.DatabaseError` if unset).
        ``schema``: ``orch``; a re-run uses a scratch schema of its own (:meth:`drop` removes it)."""
        self._db = Database.connect(url if url is not None else os.environ.get(DB_URL_ENV), schema)
        self._db.migrate(MIGRATIONS)
        self.url = self._db.url
        self.schema = self._db.schema

    @contextmanager
    def tx(self) -> Iterator[Tx]:
        with self._db.transaction() as tx:
            yield tx

    # ------------------------------------------------------------------ jobs
    def put(self, job: Job, queued: bool | None = None) -> None:
        data = job.model_dump_json(by_alias=True, exclude_none=True)
        keep = "jobs.queued" if queued is None else "excluded.queued"  # None: an update keeps the queue flag
        with self.tx() as con:
            con.execute(
                f"""INSERT INTO jobs (job_id, type, state, ruleset, ruleset_version, requested_by, received_at,
                                     updated_at, message_id, parent_job_id, queued, data)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET type=excluded.type, state=excluded.state,
                     ruleset=excluded.ruleset, ruleset_version=excluded.ruleset_version, updated_at=excluded.updated_at,
                     message_id=excluded.message_id, parent_job_id=excluded.parent_job_id, data=excluded.data,
                     queued={keep}""",
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
                ),
            )

    def get(self, job_id: str) -> Job | None:
        row = self._db.fetchone("SELECT data FROM jobs WHERE job_id = ?", (job_id,))
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
        rows = self._db.fetchall(sql, [*args, limit])
        return [Job.model_validate_json(r[0]) for r in rows]

    def claim(self) -> str | None:
        with self.tx() as con:
            row = con.fetchone(
                "SELECT job_id FROM jobs WHERE queued = 1 ORDER BY received_at, job_id LIMIT 1 FOR UPDATE SKIP LOCKED"
            )
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
        row = self._db.fetchone("SELECT cancel FROM jobs WHERE job_id = ?", (job_id,))
        return bool(row and row[0])

    def interrupted(self) -> list[str]:
        """Jobs left mid-flight by a restart (not terminal, not waiting for approval, not queued)."""
        rows = self._db.fetchall(
            "SELECT job_id FROM jobs WHERE queued = 0 AND state NOT IN ('done','failed','awaiting_approval') "
            "ORDER BY received_at, seq"
        )
        return [str(r[0]) for r in rows]

    def count_since(self, requested_by: str, since_iso: str) -> int:
        row = self._db.fetchone(
            "SELECT count(*) FROM jobs WHERE requested_by = ? AND received_at >= ?", (requested_by, since_iso)
        )
        assert row is not None
        return int(row[0])

    # ------------------------------------------------------------------ outbound mail index (reply-to-thread)
    def add_mail(self, message_id: str, job_id: str, kind: str, subject: str, sent_at: str) -> None:
        with self.tx() as con:
            con.execute(
                "INSERT INTO mails (message_id, job_id, kind, subject, sent_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT (message_id) DO UPDATE SET job_id = excluded.job_id, kind = excluded.kind, "
                "subject = excluded.subject, sent_at = excluded.sent_at",
                (message_id, job_id, kind, subject, sent_at),
            )

    def mail(self, message_id: str) -> tuple[str, str, str] | None:
        row = self._db.fetchone("SELECT job_id, kind, subject FROM mails WHERE message_id = ?", (message_id,))
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
        rows = self._db.fetchall(
            "SELECT pid, version, tier, next_appointment, practitioner_id, department, verdicts, added_at, "
            "last_eval, job_id FROM pool WHERE ruleset = ? ORDER BY pid",
            (ruleset,),
        )
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
        return [str(r[0]) for r in self._db.fetchall("SELECT DISTINCT ruleset FROM pool ORDER BY 1")]

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
        rows = self._db.fetchall(
            "SELECT pid, outcome, reason_code, note, received_at FROM feedback WHERE ruleset = ? ORDER BY pid",
            (ruleset,),
        )
        return [dict(zip(("pid", "outcome", "reason_code", "note", "received_at"), r, strict=True)) for r in rows]

    def feedback_rulesets(self) -> list[str]:
        return [str(r[0]) for r in self._db.fetchall("SELECT DISTINCT ruleset FROM feedback ORDER BY 1")]

    _SUB_COLS = ("job_id", "ruleset", "pid", "nav_job_id", "bundle_sha", "dry_run", "outcome", "submitted_by", "at")

    def submission_reserve(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """Claim a bundle for one live NHI submission before it is sent: inserts ``row`` (outcome ``pending``) and
        returns None, or returns the existing live submission of the same bundle and inserts nothing. Atomic under
        the DB lock; the partial unique index ``submissions_live_once`` backs it up."""
        with self.tx() as con:
            prior = con.fetchone(
                "SELECT job_id, ruleset, pid, nav_job_id, bundle_sha, dry_run, outcome, submitted_by, submitted_at "
                "FROM submissions WHERE bundle_sha = ? AND dry_run = 0" + self._db_row_lock,
                (row["bundle_sha"],),
            )
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
    def _submission_insert(con: Tx, row: dict[str, Any], replace: bool) -> None:
        upsert = (
            " ON CONFLICT (job_id) DO UPDATE SET ruleset = excluded.ruleset, pid = excluded.pid, nav_job_id ="
            " excluded.nav_job_id, bundle_sha = excluded.bundle_sha, dry_run = excluded.dry_run, outcome ="
            " excluded.outcome, submitted_by = excluded.submitted_by, submitted_at = excluded.submitted_at"
        )
        con.execute(
            """INSERT INTO submissions (job_id, ruleset, pid, nav_job_id, bundle_sha, dry_run, outcome,
                 submitted_by, submitted_at) VALUES (?,?,?,?,?,?,?,?,?)"""
            + (upsert if replace else ""),
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
        sql += "FROM submissions WHERE " + ("TRUE" if bundle_sha is None else "bundle_sha = ?")
        sql += " AND dry_run = 0" if live_only else ""
        rows = self._db.fetchall(sql + " ORDER BY submitted_at, seq", () if bundle_sha is None else (bundle_sha,))
        return [dict(zip(self._SUB_COLS, r, strict=True)) for r in rows]

    def prune_inactive(self, approved: set[str], cutoff_iso: str) -> dict[str, int]:
        """Retention (SPEC §10.3): pool / feedback rows of rulesets no longer approved here, untouched since cutoff."""
        keep = sorted(approved) or [""]
        marks = ",".join("?" for _ in keep)
        with self.tx() as con:
            pool = con.execute(
                f"DELETE FROM pool WHERE ruleset NOT IN ({marks}) AND last_eval < ?", (*keep, cutoff_iso)
            )
            feedback = con.execute(
                f"DELETE FROM feedback WHERE ruleset NOT IN ({marks}) AND received_at < ?", (*keep, cutoff_iso)
            )
        return {"pool": int(pool), "feedback": int(feedback)}

    # ------------------------------------------------------------------ candidate registry (D-92)
    _CAND_KEYS = (
        "ruleset",
        "pid",
        "status",
        "reason",
        "updated_at",
        "updated_by",
        "source",
        "source_job",
        "tier",
        "events",
    )

    def candidate_get(self, ruleset: str, pid: str) -> dict[str, Any] | None:
        row = self._db.fetchone(
            f"SELECT {', '.join(self._CAND_KEYS)} FROM candidates WHERE ruleset = ? AND pid = ?", (ruleset, pid)
        )
        return dict(zip(self._CAND_KEYS, row, strict=True)) if row else None

    def candidates(self, ruleset: str) -> list[dict[str, Any]]:
        rows = self._db.fetchall(
            f"SELECT {', '.join(self._CAND_KEYS)} FROM candidates WHERE ruleset = ? ORDER BY updated_at DESC, pid",
            (ruleset,),
        )
        return [dict(zip(self._CAND_KEYS, r, strict=True)) for r in rows]

    def candidate_summaries(self) -> list[dict[str, Any]]:
        rows = self._db.fetchall(
            "SELECT ruleset, status, count(*), max(updated_at) FROM candidates GROUP BY ruleset, status ORDER BY 1, 2"
        )
        out: dict[str, dict[str, Any]] = {}
        for ruleset, status, n, at in rows:
            s = out.setdefault(ruleset, {"ruleset": ruleset, "counts": {}, "updated_at": None})
            s["counts"][status] = int(n)
            s["updated_at"] = max(filter(None, [s["updated_at"], at]), default=None)
        return list(out.values())

    def candidate_set(
        self,
        ruleset: str,
        pid: str,
        status: str,
        reason: str | None,
        by: str,
        at: str,
        source: str,
        source_job: str | None,
        tier: str | None = None,
    ) -> dict[str, Any]:
        """Insert or update one row and append its event; returns the row after the change."""
        with self.tx() as con:
            row = con.fetchone(
                "SELECT status FROM candidates WHERE ruleset=? AND pid=?" + self._db_row_lock, (ruleset, pid)
            )
            if row is None:
                con.execute(
                    "INSERT INTO candidates (ruleset, pid, status, reason, updated_at, updated_by, source, source_job, "
                    "tier, events) VALUES (?,?,?,?,?,?,?,?,?,1)",
                    (ruleset, pid, status, reason, at, by, source, source_job, tier),
                )
                previous = None
            else:
                previous = str(row[0])
                con.execute(
                    "UPDATE candidates SET status=?, reason=?, updated_at=?, updated_by=?, "
                    "source_job=coalesce(?, source_job), tier=coalesce(?, tier), events=events+1 "
                    "WHERE ruleset=? AND pid=?",
                    (status, reason, at, by, source_job, tier, ruleset, pid),
                )
            con.execute(
                "INSERT INTO candidate_events (ruleset, pid, status, previous, reason, at, by, source_job) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (ruleset, pid, status, previous, reason, at, by, source_job),
            )
        got = self.candidate_get(ruleset, pid)
        assert got is not None
        return got

    def candidate_events(self, ruleset: str, pid: str | None = None) -> list[dict[str, Any]]:
        keys = ("ruleset", "pid", "status", "previous", "reason", "at", "by", "source_job")
        sql = f"SELECT {', '.join(keys)} FROM candidate_events WHERE ruleset = ?"
        params: list[Any] = [ruleset]
        if pid is not None:
            sql += " AND pid = ?"
            params.append(pid)
        rows = self._db.fetchall(sql + " ORDER BY seq", params)
        return [dict(zip(keys, r, strict=True)) for r in rows]

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
        rows = self._db.fetchall("SELECT DISTINCT received_from FROM cohort_tables WHERE site_id = ?", (site_id,))
        return {str(r[0]) for r in rows}

    def cohort_rows(self, disease: str, quarter: str) -> list[dict[str, Any]]:
        rows = self._db.fetchall(
            f"SELECT {', '.join(self._COHORT_COLS)} FROM cohort_tables WHERE disease=? AND quarter=? "
            "ORDER BY site_id, seq",
            (disease, quarter),
        )
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
                """INSERT INTO trial_cache (nct_id, last_update, version, draft_zip_key, equivalence_pct,
                     compiled_at) VALUES (?,?,?,?,?,?)
                   ON CONFLICT (nct_id, last_update) DO UPDATE SET version = excluded.version,
                     draft_zip_key = excluded.draft_zip_key, equivalence_pct = excluded.equivalence_pct,
                     compiled_at = excluded.compiled_at""",
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
        rows = self._db.fetchall(f"SELECT {', '.join(cols)} FROM trial_cache ORDER BY nct_id, last_update")
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def trial_cache_get(self, nct_id: str, last_update: str) -> dict[str, Any] | None:
        cols = ("nct_id", "last_update", "version", "draft_zip_key", "equivalence_pct", "compiled_at")
        r = self._db.fetchone(
            f"SELECT {', '.join(cols)} FROM trial_cache WHERE nct_id=? AND last_update=?", (nct_id, last_update)
        )
        return dict(zip(cols, r, strict=True)) if r else None

    # SQLite serialised every write transaction (BEGIN IMMEDIATE); a read-then-write locks its row instead
    _db_row_lock = " FOR UPDATE"

    def drop(self) -> None:
        """Remove this store's schema and close (a re-run's scratch copy)."""
        if self.schema.endswith("_" + SCHEMA_NAME) or self.schema == SCHEMA_NAME:
            raise ValueError("refusing to drop the orchestrator's own schema")
        self._db.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.close()

    def close(self) -> None:
        self._db.close()
