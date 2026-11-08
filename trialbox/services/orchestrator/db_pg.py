"""Durable workflow steps and the outbox table (spec v4 §11.0, FR-WF-1/3/9; sprint task S1-05).

They live in the trial database (PostgreSQL ``trialbox_wf``, D-126), schema ``wf``; the recall ledger
(:mod:`orchestrator.recall.ledger`) uses the same backend class on schema ``recall``. :class:`PostgresBackend` sits on
:class:`tb_common.db.Database`: SQL takes ``?`` placeholders, and a claim locks its row with ``FOR UPDATE SKIP LOCKED``
(``FOR UPDATE`` for a row that must be locked whoever holds it).

**Durable steps.** A step is identified by ``(job_id, step, input_hash)``. :meth:`StepStore.run_step`:

1. returns the recorded output when a ``done`` row exists (replay; the step body is never executed again);
2. otherwise takes a lease on the step row (another live owner makes it raise :class:`StepBusy`);
3. runs the step body, which must have **no external effect of its own**: effects are returned as outbox messages;
4. writes the step result and its outbox rows **in one transaction**.

A crash before step 4 commits leaves no outbox row, so the re-run recomputes the body and enqueues exactly once; a
crash after it commits replays the recorded output. Delivery of the rows is :mod:`orchestrator.outbox`.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from tb_common import timeutil
from tb_common.db import ENV as DB_URL_ENV
from tb_common.db import Database

Clock = Callable[[], datetime]
Row = tuple[Any, ...]
Dialect = Literal["postgres"]
WF_SCHEMA = "wf"


# --------------------------------------------------------------------------------------------- canonical JSON
def canonical_json(obj: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace, UTF-8 text, shortest round-trip floats, NaN/inf refused."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def epoch_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return int(dt.timestamp() * 1000)


# --------------------------------------------------------------------------------------------- backend
class Tx(Protocol):
    """One open transaction. SQL uses ``?`` placeholders."""

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run a statement; return the affected row count."""
        ...

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Row | None: ...

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Row]: ...


class SqlBackend(Protocol):
    dialect: Dialect

    @property
    def schema(self) -> str:
        """The schema the backend's statements run in (with the run's ``tb_prefix``)."""
        ...

    @property
    def lock_suffix(self) -> str:
        """Appended to a claim ``SELECT``: ``FOR UPDATE SKIP LOCKED``."""
        ...

    @property
    def row_lock(self) -> str:
        """Appended to a ``SELECT`` that must lock its row: ``FOR UPDATE``."""
        ...

    def transaction(self) -> AbstractContextManager[Tx]: ...

    def migrate(self, versions: Sequence[str]) -> int: ...

    def close(self) -> None: ...


class PostgresBackend:
    """One schema of the trial database on its own connection. A new backend is a new connection: what the
    crash tests call a new process."""

    dialect: Dialect = "postgres"
    lock_suffix = " FOR UPDATE SKIP LOCKED"
    row_lock = " FOR UPDATE"

    def __init__(self, url: str | None = None, schema: str = WF_SCHEMA) -> None:
        """``url``: a ``postgresql://`` URL, ``TB_DB_URL`` when None (:class:`tb_common.db.DatabaseError` if unset)."""
        self.db = Database.connect(url if url is not None else os.environ.get(DB_URL_ENV), schema)

    @property
    def schema(self) -> str:
        return self.db.schema

    @property
    def url(self) -> str:
        return self.db.url

    def transaction(self) -> AbstractContextManager[Tx]:
        return self.db.transaction()

    def migrate(self, versions: Sequence[str]) -> int:
        return self.db.migrate(versions)

    def close(self) -> None:
        self.db.close()


def open_backend(url: str | None = None, schema: str = WF_SCHEMA) -> SqlBackend:
    """The ``schema`` of the trial database at ``url`` (``TB_DB_URL`` when None)."""
    return PostgresBackend(url, schema)


# --------------------------------------------------------------------------------------------- schema (§11.0)
SCHEMA = """
CREATE TABLE IF NOT EXISTS steps (
  job_id TEXT NOT NULL,
  step TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  state TEXT NOT NULL,
  output TEXT,
  output_ref TEXT,
  attempts BIGINT NOT NULL DEFAULT 0,
  started TEXT,
  finished TEXT,
  lease_owner TEXT,
  lease_until BIGINT,
  PRIMARY KEY (job_id, step, input_hash)
);
CREATE TABLE IF NOT EXISTS outbox (
  msg_id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  job_id TEXT NOT NULL,
  step TEXT NOT NULL,
  kind TEXT NOT NULL,
  recipient TEXT NOT NULL,
  channel TEXT NOT NULL,
  payload TEXT NOT NULL,
  payload_ref TEXT,
  state TEXT NOT NULL,
  attempts BIGINT NOT NULL DEFAULT 0,
  created TEXT NOT NULL,
  created_ms BIGINT NOT NULL,
  next_attempt_ms BIGINT NOT NULL,
  lease_owner TEXT,
  lease_until BIGINT,
  delivered_at TEXT,
  receipt TEXT,
  last_error TEXT,
  resolved_by TEXT,
  resolution TEXT
);
CREATE INDEX IF NOT EXISTS outbox_state ON outbox (state, next_attempt_ms, created_ms);
CREATE INDEX IF NOT EXISTS outbox_job ON outbox (job_id)
"""
#: ``migrate`` versions of schema ``wf`` (append-only; version 1 is the schema as it was on SQLite)
MIGRATIONS = (SCHEMA,)

STEP_RUNNING = "running"
STEP_DONE = "done"


@dataclass(frozen=True)
class OutboxMessage:
    """One external effect a step wants. ``key`` distinguishes several messages of one step (default: position)."""

    kind: str
    recipient: str
    channel: str
    payload: Mapping[str, Any]
    key: str | None = None
    payload_ref: str | None = None


@dataclass(frozen=True)
class StepResult:
    output: Mapping[str, Any]
    sends: Sequence[OutboxMessage] = field(default_factory=tuple)
    output_ref: str | None = None


@dataclass(frozen=True)
class StepOutcome:
    output: dict[str, Any]
    replayed: bool
    msg_ids: tuple[str, ...]


class StepBusy(RuntimeError):
    """Another worker holds a live lease on this step."""


def step_input_hash(
    inputs: Mapping[str, Any],
    *,
    workflow: str,
    workflow_version: str,
    code_sha: str,
    model: Mapping[str, str] | None = None,
) -> str:
    """FR-WF-3 step identity: inputs, workflow version and code SHA, plus (when a model is involved) model SHA,
    prompt version, routing-policy version and snapshot id, hashed over canonical JSON."""
    body = {
        "inputs": dict(inputs),
        "workflow": workflow,
        "workflow_version": workflow_version,
        "code_sha": code_sha,
        "model": dict(model) if model else None,
    }
    return sha256_text(canonical_json(body))


def idempotency_key(job_id: str, step: str, input_hash: str, key: str) -> str:
    return hashlib.sha256(canonical_json([job_id, step, input_hash, key]).encode("utf-8")).hexdigest()


class StepStore:
    """Durable steps over a :class:`SqlBackend` with an injected clock."""

    def __init__(
        self,
        backend: SqlBackend,
        owner: str,
        clock: Clock = timeutil.now,
        lease_ms: int = 60_000,
    ) -> None:
        self.backend = backend
        self.owner = owner
        self.clock = clock
        self.lease_ms = lease_ms
        backend.migrate(MIGRATIONS)

    # --------------------------------------------------------------------------------------------- queries
    def get(self, job_id: str, step: str, input_hash: str) -> Row | None:
        with self.backend.transaction() as tx:
            return tx.fetchone(
                "SELECT state, output, attempts, lease_owner, lease_until FROM steps"
                " WHERE job_id = ? AND step = ? AND input_hash = ?",
                (job_id, step, input_hash),
            )

    # --------------------------------------------------------------------------------------------- run
    def _claim(self, job_id: str, step: str, input_hash: str) -> dict[str, Any] | None:
        """Return the recorded output if done; otherwise take the lease (or raise StepBusy) and return None."""
        now = self.clock()
        now_ms = epoch_ms(now)
        with self.backend.transaction() as tx:
            tx.execute(
                "INSERT INTO steps (job_id, step, input_hash, state, attempts) VALUES (?, ?, ?, ?, 0)"
                " ON CONFLICT (job_id, step, input_hash) DO NOTHING",
                (job_id, step, input_hash, STEP_RUNNING),
            )
            row = tx.fetchone(
                "SELECT state, output, lease_owner, lease_until FROM steps"
                " WHERE job_id = ? AND step = ? AND input_hash = ?" + self.backend.row_lock,
                (job_id, step, input_hash),
            )
            assert row is not None
            state, output, lease_owner, lease_until = row
            if state == STEP_DONE:
                return dict(json.loads(output))
            if (
                lease_owner is not None
                and lease_owner != self.owner
                and lease_until is not None
                and lease_until > now_ms
            ):
                raise StepBusy(f"{job_id}/{step} is leased by {lease_owner}")
            tx.execute(
                "UPDATE steps SET lease_owner = ?, lease_until = ?, attempts = attempts + 1, started = ?"
                " WHERE job_id = ? AND step = ? AND input_hash = ?",
                (self.owner, now_ms + self.lease_ms, timeutil.iso(now), job_id, step, input_hash),
            )
        return None

    def run_step(
        self,
        job_id: str,
        step: str,
        input_hash: str,
        body: Callable[[], StepResult],
    ) -> StepOutcome:
        recorded = self._claim(job_id, step, input_hash)
        if recorded is not None:
            return StepOutcome(recorded, True, self._msg_ids(job_id, step, input_hash))
        result = body()
        return self._complete(job_id, step, input_hash, result)

    def _msg_ids(self, job_id: str, step: str, input_hash: str) -> tuple[str, ...]:
        with self.backend.transaction() as tx:
            return self._msg_ids_tx(tx, job_id, step, input_hash)

    def _complete(self, job_id: str, step: str, input_hash: str, result: StepResult) -> StepOutcome:
        now = self.clock()
        now_ms = epoch_ms(now)
        output = canonical_json(dict(result.output))
        msg_ids: list[str] = []
        with self.backend.transaction() as tx:
            row = tx.fetchone(
                "SELECT state, output, lease_owner FROM steps WHERE job_id = ? AND step = ? AND input_hash = ?"
                + self.backend.row_lock,
                (job_id, step, input_hash),
            )
            if row is None:
                raise RuntimeError(f"step row {job_id}/{step} vanished")
            if row[0] == STEP_DONE:  # another worker finished first after our lease expired: keep its result
                return StepOutcome(dict(json.loads(row[1])), True, self._msg_ids_tx(tx, job_id, step, input_hash))
            if row[2] != self.owner:
                raise StepBusy(f"{job_id}/{step}: lease lost to {row[2]}")
            for i, msg in enumerate(result.sends):
                key = msg.key if msg.key is not None else str(i)
                idem = idempotency_key(job_id, step, input_hash, key)
                msg_id = f"{job_id}:{step}:{input_hash}:{key}"
                tx.execute(
                    "INSERT INTO outbox (msg_id, idempotency_key, job_id, step, kind, recipient, channel, payload,"
                    " payload_ref, state, attempts, created, created_ms, next_attempt_ms)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)"
                    " ON CONFLICT (idempotency_key) DO NOTHING",
                    (
                        msg_id,
                        idem,
                        job_id,
                        step,
                        msg.kind,
                        msg.recipient,
                        msg.channel,
                        canonical_json(dict(msg.payload)),
                        msg.payload_ref,
                        timeutil.iso(now),
                        now_ms,
                        now_ms,
                    ),
                )
                msg_ids.append(msg_id)
            tx.execute(
                "UPDATE steps SET state = ?, output = ?, output_ref = ?, finished = ?, lease_owner = NULL,"
                " lease_until = NULL WHERE job_id = ? AND step = ? AND input_hash = ?",
                (STEP_DONE, output, result.output_ref, timeutil.iso(now), job_id, step, input_hash),
            )
        return StepOutcome(dict(json.loads(output)), False, tuple(sorted(msg_ids)))

    @staticmethod
    def _msg_ids_tx(tx: Tx, job_id: str, step: str, input_hash: str) -> tuple[str, ...]:
        prefix = f"{job_id}:{step}:{input_hash}:"
        rows = tx.fetchall("SELECT msg_id FROM outbox WHERE job_id = ? AND step = ? ORDER BY msg_id", (job_id, step))
        return tuple(r[0] for r in rows if str(r[0]).startswith(prefix))


__all__ = [
    "MIGRATIONS",
    "SCHEMA",
    "WF_SCHEMA",
    "Clock",
    "OutboxMessage",
    "PostgresBackend",
    "SqlBackend",
    "StepBusy",
    "StepOutcome",
    "StepResult",
    "StepStore",
    "Tx",
    "canonical_json",
    "epoch_ms",
    "idempotency_key",
    "open_backend",
    "sha256_text",
    "step_input_hash",
]
