"""Job queue and orchestrator state (SPEC §4.8: ``jobs`` mirrors the Job contract §3.5).

Schema ``orch`` of the trial database (PostgreSQL ``trialbox_wf``, D-126; :mod:`tb_common.db`)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Callable, Iterator, Mapping
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
# T-103 (D-438): the orchestrator's per-person caps on identifiers (chart numbers revealed, exports with chart
# numbers) as use rows in the store, so a restart or a second process does not reset them. ``at`` is epoch ms.
SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS id_limits (
  seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind TEXT NOT NULL,
  who TEXT NOT NULL,
  at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS id_limits_who ON id_limits (kind, who, at);
"""
# T-689 (D-456): a restart is counted per job (``attempts``), and the answers a job's model client gave are kept
# while the job is unfinished, so the job replays them after a restart instead of asking the model again
# (``judge_answers``: the answer as JSON under the job and a key; deleted when the job ends)
SCHEMA_V3 = """
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempts BIGINT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS judge_answers (
  job_id TEXT NOT NULL,
  key TEXT NOT NULL,
  answer TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (job_id, key)
);
"""
# D-648: what the alliance store was given, table by table. ``cohort_tables`` holds a site's latest table only; a
# re-run of a merge needs the tables as they stood when it read them, and what an earlier job stored was read from
# how that job ended, which a stopped job does not say.
# ``cohort_stored``: one row per table stored, written in the transaction that stores it (the job, the site, who
# sent it, the table's hash and the table itself; ``seq`` is the order of all stores).
# ``cohort_read``: when a merge read the tables for its output: ``upto`` is the last ``cohort_stored.seq`` then.
# ``cohort_tables_before``: the tables as this version found them (a box updated in place), which no record holds.
SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS cohort_stored (
  seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  received_from TEXT NOT NULL,
  table_sha256 TEXT NOT NULL,
  rows TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cohort_stored_job ON cohort_stored (job_id, seq);
CREATE TABLE IF NOT EXISTS cohort_read (
  seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_id TEXT NOT NULL,
  upto BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS cohort_read_job ON cohort_read (job_id, seq);
CREATE TABLE IF NOT EXISTS cohort_tables_before (
  seq BIGINT PRIMARY KEY,
  site_id TEXT NOT NULL,
  disease TEXT NOT NULL,
  quarter TEXT NOT NULL,
  criterion_id TEXT NOT NULL,
  definition_version TEXT NOT NULL,
  criterion_label TEXT NOT NULL,
  n TEXT NOT NULL,
  n_contactable TEXT NOT NULL,
  received_from TEXT NOT NULL,
  job_id TEXT NOT NULL
);
INSERT INTO cohort_tables_before (seq, site_id, disease, quarter, criterion_id, definition_version, criterion_label,
  n, n_contactable, received_from, job_id)
SELECT seq, site_id, disease, quarter, criterion_id, definition_version, criterion_label, n, n_contactable,
  received_from, job_id FROM cohort_tables
"""
# D-908 (the owner's D-519): the judged-pair store. One row per model answer (the judge's and the verifier's apart,
# never a combined verdict), by the key of ``orchestrator.judged_store``; the patient's pseudonym and the snapshot
# whose notes it read are columns so an opt-out deletes the patient's rows and the snapshots' retention
# (D-452) takes the rows with it. Class D3: never exported, never in a support bundle.
SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS judged_pairs (
  key TEXT PRIMARY KEY,
  pid TEXT NOT NULL,
  snapshot TEXT NOT NULL,
  role TEXT NOT NULL,
  build_sha TEXT NOT NULL,
  answer TEXT NOT NULL,
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS judged_pairs_pid ON judged_pairs (pid);
CREATE INDEX IF NOT EXISTS judged_pairs_snapshot ON judged_pairs (snapshot);
"""
# D-1223: a member site's alliance table is stored only when its Ed25519 signature holds for the key registered for
# the site (``tb_common.alliance``). ``verified_by``: the signing key's fingerprint, ``own`` for the root's own table
# (made in the box, never mailed), NULL for a table stored before signatures were required: kept, marked unverified,
# and left out of every merge until its site sends it signed. ``signed_seq`` and ``signed_sha256``: the signed
# table's sequence and hash, so an older table is not taken over a newer one. The record (``cohort_stored``) keeps
# the same three, so a replay rebuilds them.
SCHEMA_V6 = """
ALTER TABLE cohort_tables ADD COLUMN IF NOT EXISTS verified_by TEXT;
ALTER TABLE cohort_tables ADD COLUMN IF NOT EXISTS signed_seq BIGINT;
ALTER TABLE cohort_tables ADD COLUMN IF NOT EXISTS signed_sha256 TEXT;
ALTER TABLE cohort_stored ADD COLUMN IF NOT EXISTS verified_by TEXT;
ALTER TABLE cohort_stored ADD COLUMN IF NOT EXISTS signed_seq BIGINT;
ALTER TABLE cohort_stored ADD COLUMN IF NOT EXISTS signed_sha256 TEXT;
UPDATE cohort_tables SET verified_by = 'own' WHERE received_from LIKE 'self:%';
UPDATE cohort_stored SET verified_by = 'own' WHERE received_from LIKE 'self:%'
"""
MIGRATIONS = (SCHEMA, SCHEMA_V2, SCHEMA_V3, SCHEMA_V4, SCHEMA_V5, SCHEMA_V6)
SCHEMA_NAME = "orch"

TERMINAL = ("done", "failed")


def _ruleset_of(definition_version: str) -> str:
    """``tb_common.alliance.ruleset_of``: the rule set of a definition (``GOUT-COH@1.0.0`` -> ``GOUT-COH``)."""
    return definition_version.split("@", 1)[0]


def _counts(site: str, verified_by: str, registered: Mapping[str, str] | None) -> bool:
    """Whether a verified row is merged (D-1223): the root's own, or signed by the key registered for its site now
    (any verified row when the caller gives no register)."""
    return verified_by == "own" or registered is None or registered.get(site) == verified_by


def cohort_table_hash(rows: list[dict[str, Any]]) -> str:
    """The hash of one alliance table (D-648): every stored column of every row, the rows in a fixed order, so the
    same table has the same hash whatever order its file gave the rows in."""
    cells = sorted(json.dumps([r[c] for c in JobDB._COHORT_COLS], ensure_ascii=False) for r in rows)
    return hashlib.sha256("\n".join(cells).encode("utf-8")).hexdigest()


class JobLeased(RuntimeError):
    """Another live worker runs this job (its lease is held): it is not run or queued a second time."""


def lease_keys(schema: str, job_id: str) -> tuple[int, int]:
    """The two 32-bit keys of a job's lease: the halves of one 64-bit hash of the schema and the job id, so two
    jobs share a lock with the odds of a 64-bit collision, not a 32-bit one (review of NEW-B-11, LOW-5)."""
    digest = hashlib.blake2b(f"{schema}:job-run:{job_id}".encode(), digest_size=8).digest()
    return (
        int.from_bytes(digest[:4], "big", signed=True),
        int.from_bytes(digest[4:], "big", signed=True),
    )


class JobLease:
    """One run's lease (D-532): a session lock of the database on a connection of its own. Not timed (OD-10): it
    lives exactly as long as its holder's connection, and releasing it is closing that connection."""

    def __init__(self, url: str, name: str, schema: str, job_id: str) -> None:
        self.job_id = job_id
        self._keys = lease_keys(schema, job_id)
        self._db = Database.connect(url, name)
        try:
            row = self._db.fetchone("SELECT pg_try_advisory_lock(?, ?)", self._keys)
        except BaseException:
            self._db.close()
            raise
        if not (row and row[0]):
            self._db.close()
            raise JobLeased(f"job {job_id} is being run by another worker")

    def release(self) -> None:
        """Give the lease up: unlock, then close. The unlock is said on the connection that holds the lock, while
        it lives: closing alone gives the lock back only when the server has ended the session, a moment after
        the close returns, and for that moment the next worker would find the job "leased" (seen on train 5: a
        test read the lease right after the release and still saw it). A connection that was lost holds nothing
        and is not opened again to say so (review LOW-6)."""
        if not self._db._dead():
            with contextlib.suppress(Exception):
                self._db._con.execute("SELECT pg_advisory_unlock(%s, %s)", self._keys)
        self.drop_connection()

    def drop_connection(self) -> None:
        """What a dying holder does without meaning to: the connection goes, and the lease with it."""
        with contextlib.suppress(Exception):
            self._db.close()


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

    @contextmanager
    def locked(self, name: str) -> Iterator[None]:
        """Hold the lock ``name`` to the end of the block: one holder at a time over every process of the box (an
        advisory lock of one transaction, so a holder that dies releases it). T-704 (D-458): the night's allowance."""
        with self.tx() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (name,))
            yield

    # ------------------------------------------------------------------ identifier caps (T-103, D-438)
    def take_limit(self, kind: str, who: str, at_ms: int, window_ms: int, limit: int) -> bool:
        """One capped use of ``kind`` by ``who``: in one transaction, serialised per kind and person, count the uses
        in the window before ``at_ms`` and record this one only when it is within ``limit``; False at the cap."""
        with self.tx() as tx:
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"id_limits:{kind}:{who}",))
            n = tx.fetchval("SELECT count(*) FROM id_limits WHERE kind = ? AND who = ? AND at > ?",
                            (kind, who, at_ms - window_ms))  # fmt: skip
            if int(n or 0) >= limit:
                return False
            tx.execute("INSERT INTO id_limits (kind, who, at) VALUES (?,?,?)", (kind, who, at_ms))
        return True

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

    def waiting_rulesets(self) -> list[str]:
        """NEW-JRN-1b (D-545): the studies with a job waiting for approval, the one with the newest such job first.
        One row per study, so nothing is cut: a study behind any number of other waiting jobs is named."""
        rows = self._db.fetchall(
            "SELECT ruleset FROM jobs WHERE state = ? AND ruleset IS NOT NULL AND trim(ruleset) <> '' "
            "GROUP BY ruleset ORDER BY max(received_at) DESC, ruleset",
            ("awaiting_approval",),
        )
        return [str(r[0]) for r in rows]

    # ------------------------------------------------------------------ the night's chain (T-726, D-492)
    def scheduler_jobs(
        self,
        *,
        type_: str | None = None,
        ruleset: str | None = None,
        night: str | None = None,
        step: str | None = None,
        night_day_from: str | None = None,
        received_from: str | None = None,
        unfinished: bool = False,
    ) -> list[Job]:
        """The scheduler's own jobs, oldest first: of one type and study (``ruleset=""``: the box-wide ones), of
        one night (``options.night``), of one step of the chain (``options.step``; ``""``: jobs that carry none,
        made before the chain), of nights from a date on (``options.night_day``), received from a time on, or only
        those that have not ended. Every row that matches: the chain reads its state from the jobs, so it must not
        read a part of them."""
        where, args = ["requested_by = 'scheduler'"], []
        filters = (
            ("type = ?", type_),
            ("coalesce(ruleset, '') = ?", ruleset),
            ("received_at >= ?", received_from),
            ("(data::jsonb)->'options'->>'night' = ?", night),
            ("(data::jsonb)->'options'->>'night_day' >= ?", night_day_from),
        )
        for col, val in filters:
            if val is not None:
                where.append(col)
                args.append(val)
        if step == "":
            where.append("(data::jsonb)->'options'->>'step' IS NULL")
        elif step is not None:
            where.append("(data::jsonb)->'options'->>'step' = ?")
            args.append(step)
        if unfinished:
            where.append(f"state NOT IN ({','.join('?' for _ in TERMINAL)})")
            args += list(TERMINAL)
        rows = self._db.fetchall(
            "SELECT data FROM jobs WHERE " + " AND ".join(where) + " ORDER BY received_at, seq", args
        )
        return [Job.model_validate_json(r[0]) for r in rows]

    def chained_ingest(self, before: str | None = None) -> Job | None:
        """The newest ingest that passed and carries the chain's option, received before ``before`` (none: the
        newest of all)."""
        row = self._db.fetchone(
            "SELECT data FROM jobs WHERE type = 'INGEST' AND state = 'done' "
            "AND (data::jsonb)->'options'->>'chain' = '1' AND (? = '' OR received_at < ?) "
            "ORDER BY received_at DESC, seq DESC LIMIT 1",
            (before or "", before or ""),
        )
        return Job.model_validate_json(row[0]) if row else None

    def with_option(self, type_: str, key: str, value: str) -> list[Job]:
        """Every job of ``type_`` whose options carry ``key`` = ``value``, oldest first (NEW-PERF-2: the INGEST
        jobs that are on one adapter run)."""
        rows = self._db.fetchall(
            "SELECT data FROM jobs WHERE type = ? AND (data::jsonb)->'options'->>? = ? ORDER BY received_at, seq",
            (type_, key, value),
        )
        return [Job.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------------ the run's lease (NEW-B-11, D-532)
    def lease(self, job_id: str) -> JobLease:
        """The lease of the worker that runs ``job_id``: held from the run's start to its end, on a connection of
        its own, given up with that connection (a worker that dies holds nothing). :class:`JobLeased` when another
        worker, in this process or any other on the database, holds it."""
        return JobLease(self.url, self._db.store, self._db.schema, job_id)

    def leased(self, job_id: str) -> bool:
        """Whether a live worker runs ``job_id`` now. Read from the database's own list of locks: asking takes no
        lock, so it never stands in a worker's way (review MED-4)."""
        k1, k2 = lease_keys(self._db.schema, job_id)
        row = self._db.fetchone(
            "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted AND objsubid = 2 "
            "AND classid = ? AND objid = ? "
            "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())",
            (k1 & 0xFFFFFFFF, k2 & 0xFFFFFFFF),
        )
        return row is not None

    def claim(self, only: tuple[str, ...] = ()) -> str | None:
        """Take the oldest queued job; ``only``: of these types (T-704, D-458: the worker kept for the ingest)."""
        types = " AND type = ANY(?)" if only else ""
        with self.tx() as con:
            row = con.fetchone(
                f"SELECT job_id FROM jobs WHERE queued = 1{types} ORDER BY received_at, job_id LIMIT 1 "
                "FOR UPDATE SKIP LOCKED",
                (list(only),) if only else (),
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

    def count_restart(self, job_id: str) -> int:
        """One more restart found this job interrupted (T-689, D-456); returns the new count."""
        with self.tx() as con:
            row = con.fetchone("UPDATE jobs SET attempts = attempts + 1 WHERE job_id = ? RETURNING attempts", (job_id,))
        return int(row[0]) if row else 0

    def restarts(self, job_id: str) -> int:
        row = self._db.fetchone("SELECT attempts FROM jobs WHERE job_id = ?", (job_id,))
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------ kept model answers (T-689, D-456)
    def answer_get(self, job_id: str, key: str) -> str | None:
        row = self._db.fetchone("SELECT answer FROM judge_answers WHERE job_id = ? AND key = ?", (job_id, key))
        return str(row[0]) if row else None

    def answer_put(self, job_id: str, key: str, answer: str, at: str, replace: bool = False) -> None:
        """Keep one answer. The first one stays (two calls with one key in flight together gave the same question),
        unless ``replace``: the kept one is another build's (the caller checked)."""
        with self.tx() as con:
            if replace:
                con.execute(
                    "INSERT INTO judge_answers (job_id, key, answer, at) VALUES (?,?,?,?) ON CONFLICT (job_id, key) "
                    "DO UPDATE SET answer = EXCLUDED.answer, at = EXCLUDED.at",
                    (job_id, key, answer, at),
                )
            else:
                con.execute(
                    "INSERT INTO judge_answers (job_id, key, answer, at) VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                    (job_id, key, answer, at),
                )

    def answer_count(self, job_id: str) -> int:
        return int(self._db.fetchval("SELECT count(*) FROM judge_answers WHERE job_id = ?", (job_id,)) or 0)

    def answers_drop(self, job_id: str) -> int:
        with self.tx() as con:
            return int(con.execute("DELETE FROM judge_answers WHERE job_id = ?", (job_id,)))

    def answers_sweep(self) -> int:
        """Drop the kept answers of every job that is finished or gone (the orchestrator's start)."""
        with self.tx() as con:
            return int(
                con.execute(
                    "DELETE FROM judge_answers a WHERE NOT EXISTS (SELECT 1 FROM jobs j WHERE "
                    "j.job_id = a.job_id AND j.state NOT IN ('done','failed'))"
                )
            )

    # ------------------------------------------------------------------ the judged-pair store (D-908, D-519)
    def pair_get(self, key: str) -> tuple[str, str] | None:
        """``(pid, answer)`` of a stored model answer."""
        row = self._db.fetchone("SELECT pid, answer FROM judged_pairs WHERE key = ?", (key,))
        return (str(row[0]), str(row[1])) if row else None

    def pair_put(self, key: str, pid: str, snapshot: str, role: str, build_sha: str, answer: str, at: str) -> None:
        """Store one model answer; one already stored under the key gives way (the key names its build)."""
        with self.tx() as con:
            con.execute(
                "INSERT INTO judged_pairs (key, pid, snapshot, role, build_sha, answer, at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT (key) DO UPDATE SET snapshot = EXCLUDED.snapshot, answer = EXCLUDED.answer, "
                "at = EXCLUDED.at",
                (key, pid, snapshot, role, build_sha, answer, at),
            )

    def pair_snapshots(self) -> list[str]:
        return [str(r[0]) for r in self._db.fetchall("SELECT DISTINCT snapshot FROM judged_pairs")]

    def pairs_drop_snapshots(self, keep: list[str]) -> int:
        """Delete the answers of every snapshot not in ``keep`` (the snapshots' retention, D-452)."""
        with self.tx() as con:
            return int(con.execute("DELETE FROM judged_pairs WHERE NOT (snapshot = ANY(?))", (list(keep),)))

    def pairs_drop_pids(self, pids: list[str]) -> int:
        """Delete every answer about these patients (an opt-out, D-513)."""
        with self.tx() as con:
            return int(con.execute("DELETE FROM judged_pairs WHERE pid = ANY(?)", (list(pids),)))

    def pair_count(self) -> int:
        return int(self._db.fetchval("SELECT count(*) FROM judged_pairs") or 0)

    def unfinished(self, type_: str, ruleset: str | None) -> list[str]:
        """The jobs of ``type_`` for ``ruleset`` (none: the box-wide jobs, INGEST and RETENTION) that are queued or
        running, oldest first (T-746, D-474: a retry waits for them)."""
        terminal = ",".join("?" for _ in TERMINAL)
        rows = self._db.fetchall(
            f"SELECT job_id FROM jobs WHERE type = ? AND coalesce(ruleset, '') = ? AND state NOT IN ({terminal}) "
            "ORDER BY received_at, seq",
            (type_, ruleset or "", *TERMINAL),
        )
        return [str(r[0]) for r in rows]

    def count_since(self, requested_by: str, since_iso: str, type_: str | None = None) -> int:
        """Jobs ``requested_by`` started since ``since_iso``; of one type only when ``type_`` is given (D-146)."""
        if type_ is None:
            row = self._db.fetchone(
                "SELECT count(*) FROM jobs WHERE requested_by = ? AND received_at >= ?", (requested_by, since_iso)
            )
        else:
            row = self._db.fetchone(
                "SELECT count(*) FROM jobs WHERE requested_by = ? AND received_at >= ? AND type = ?",
                (requested_by, since_iso, type_),
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

    def pool_remove(self, pids: list[str]) -> int:
        """D-441: the opt-out worker takes these patients out of every study's candidate pool (MICROBATCH reads the
        pool; SCREEN drops a patient on the register before the pool is written). Returns the rows removed."""
        if not pids:
            return 0
        with self.tx() as con:
            n = con.fetchval("SELECT count(*) FROM pool WHERE pid = ANY(?)", (list(pids),))
            con.execute("DELETE FROM pool WHERE pid = ANY(?)", (list(pids),))
        return int(n or 0)

    def pool_count(self, pids: list[str]) -> int:
        """T-727: the pool rows of these patients in every study (the opt-out worker's read-back)."""
        if not pids:
            return 0
        return int(self._db.fetchval("SELECT count(*) FROM pool WHERE pid = ANY(?)", (list(pids),)) or 0)

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

    def cohort_store(
        self,
        rows: list[dict[str, Any]],
        job_id: str,
        received_from: str,
        refuse: Callable[[set[str]], str | None] | None = None,
        *,
        verified_by: str | None = None,
        signed_seq: int | None = None,
        signed_sha256: str | None = None,
        stale: Callable[[dict[tuple[str, str], tuple[int | None, str | None]]], str | None] | None = None,
    ) -> str | None:
        """Replace a site's table for each (disease, quarter, definition) it contains, then insert the rows, and
        record what was stored (D-648): one ``cohort_stored`` row per site in ``rows``, in this transaction, so the
        record and the tables cannot differ however the caller ends. One store at a time (the lock), so the
        record's order is the order the tables were committed in.

        ``refuse``: the caller's rule on who may store these rows, asked inside the transaction, under the lock,
        with the addresses whose tables of the rows' sites stand in the store now (all the sites in ``rows``
        together: a caller with a rule per site passes one site's rows). A sentence back: nothing is stored
        and the sentence is returned. A check made before the call can be overtaken by another store (two senders
        of one site, both let in). None is returned when the rows were stored.

        ``verified_by``, ``signed_seq``, ``signed_sha256`` (D-1223): how the table was verified (the signing key's
        fingerprint, ``own``, or None: unverified), and the signed table's sequence and hash. ``stale``: asked in the
        same transaction with, for each (site, rule set) of ``rows``, the highest signed sequence stored and that
        table's hash; a sentence back refuses the store as ``refuse`` does."""
        if not rows:
            return None
        with self.tx() as con:
            con.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"{self.schema}:cohort_store",))
            if refuse is not None:
                senders: set[str] = set()
                for site in sorted({r["site_id"] for r in rows}):
                    got = con.fetchall("SELECT DISTINCT received_from FROM cohort_tables WHERE site_id = ?", (site,))
                    senders |= {str(r[0]) for r in got}
                said = refuse(senders)
                if said:
                    return said
            if stale is not None:
                # D-1223: freshness per (site, rule set), across its versions and quarters: the highest signed
                # sequence stored and that table's hash
                held: dict[tuple[str, str], tuple[int | None, str | None]] = {}
                for site, ruleset in sorted({(r["site_id"], _ruleset_of(r["definition_version"])) for r in rows}):
                    got = con.fetchall(
                        "SELECT definition_version, signed_seq, signed_sha256 FROM cohort_tables WHERE site_id=? "
                        "AND signed_seq IS NOT NULL",
                        (site,),
                    )
                    mine = [(int(g[1]), str(g[2])) for g in got if _ruleset_of(str(g[0])) == ruleset]
                    if mine:
                        held[(site, ruleset)] = max(mine)
                said = stale(held)
                if said:
                    return said
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
                         criterion_label, n, n_contactable, received_from, job_id, verified_by, signed_seq,
                         signed_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                        verified_by,
                        signed_seq,
                        signed_sha256,
                    ),
                )
            for site in sorted({r["site_id"] for r in rows}):
                table = [{c: r[c] for c in self._COHORT_COLS} for r in rows if r["site_id"] == site]
                con.execute(
                    "INSERT INTO cohort_stored (job_id, site_id, received_from, table_sha256, rows, verified_by, "
                    "signed_seq, signed_sha256) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        job_id,
                        site,
                        received_from,
                        cohort_table_hash(table),
                        json.dumps(table, ensure_ascii=False),
                        verified_by,
                        signed_seq,
                        signed_sha256,
                    ),
                )
        return None

    _STORED_COLS = (
        "seq",
        "job_id",
        "site_id",
        "received_from",
        "table_sha256",
        "rows",
        "verified_by",
        "signed_seq",
        "signed_sha256",
    )

    def _stored(self, where: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
        got = self._db.fetchall(f"SELECT {', '.join(self._STORED_COLS)} FROM cohort_stored {where} ORDER BY seq", args)
        return [dict(zip(self._STORED_COLS, r, strict=True)) for r in got]

    def cohort_stored(self, job_id: str) -> list[dict[str, Any]]:
        """The tables the job ``job_id`` stored since the record began, in the order it stored them (D-648): the
        site, who sent it, the table's hash and the table (``rows``, as JSON text)."""
        return self._stored("WHERE job_id = ?", (job_id,))

    def cohort_stored_all(self, upto: int | None = None) -> list[dict[str, Any]]:
        """Every recorded store of a table, in order (D-648); up to and with the store ``upto`` when given."""
        return self._stored("" if upto is None else "WHERE seq <= ?", () if upto is None else (upto,))

    def cohort_read(
        self, job_id: str, keys: list[tuple[str, str]], registered: Mapping[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """The rows of each (disease, quarter) of ``keys`` for the merge ``job_id``'s output, and the record of the
        point it read them at (D-648): the last store before the read, written in the transaction that reads,
        while no store runs. A re-run rebuilds the tables up to that point.

        D-1223: only verified rows: the root's own (``own``), and, with ``registered`` (site -> the key fingerprint
        the register holds now), only a member's rows signed by that key; without it, any verified row. An
        unverified table, or one whose key the register no longer holds, is kept and left out
        (:meth:`cohort_left_out`)."""
        out: list[dict[str, Any]] = []
        with self.tx() as con:
            con.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"{self.schema}:cohort_store",))
            for disease, quarter in keys:
                got = con.fetchall(
                    f"SELECT {', '.join(self._COHORT_COLS)}, verified_by FROM cohort_tables WHERE disease=? "
                    "AND quarter=? AND verified_by IS NOT NULL ORDER BY site_id, seq",
                    (disease, quarter),
                )
                for *r, by in got:
                    if not _counts(str(r[0]), str(by), registered):
                        continue
                    d = dict(zip(self._COHORT_COLS, r, strict=True))
                    d["n"], d["n_contactable"] = json.loads(d["n"]), json.loads(d["n_contactable"])
                    out.append(d)
            con.execute(
                "INSERT INTO cohort_read (job_id, upto) SELECT ?, COALESCE(MAX(seq), 0) FROM cohort_stored", (job_id,)
            )
        return out

    def cohort_read_point(self, job_id: str) -> int | None:
        """The last store before the merge ``job_id`` read the tables for its output (its last read, when it ran
        more than once); None: it never read them, or it did before the record began (D-648)."""
        row = self._db.fetchone(
            "SELECT upto FROM cohort_read WHERE seq = (SELECT MAX(seq) FROM cohort_read WHERE job_id = ?)", (job_id,)
        )
        return int(row[0]) if row else None

    def cohort_before(self) -> list[dict[str, Any]]:
        """The alliance tables as the version that began the record found them, in their order (D-648)."""
        cols = (*self._COHORT_COLS, "received_from", "job_id")
        got = self._db.fetchall(f"SELECT {', '.join(cols)} FROM cohort_tables_before ORDER BY seq")
        out = []
        for r in got:
            d = dict(zip(cols, r, strict=True))
            d["n"], d["n_contactable"] = json.loads(d["n"]), json.loads(d["n_contactable"])
            out.append(d)
        return out

    def cohort_left_out(
        self, keys: list[tuple[str, str]], registered: Mapping[str, str] | None = None
    ) -> tuple[set[str], set[str]]:
        """The sites with a table in a (disease, quarter) of ``keys`` that :meth:`cohort_read` leaves out (D-1223):
        (stored before signatures were required, signed by a key the register no longer holds for the site)."""
        unverified: set[str] = set()
        revoked: set[str] = set()
        for disease, quarter in keys:
            got = self._db.fetchall(
                "SELECT DISTINCT site_id, verified_by FROM cohort_tables WHERE disease=? AND quarter=?",
                (disease, quarter),
            )
            for site, by in got:
                if by is None:
                    unverified.add(str(site))
                elif not _counts(str(site), str(by), registered):
                    revoked.add(str(site))
        return unverified, revoked

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
