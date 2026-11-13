"""The orchestrator's backend on one schema of the trial database (PostgreSQL ``trialbox_wf``, D-126).

:class:`PostgresBackend` sits on :class:`tb_common.db.Database`: SQL takes ``?`` placeholders, and a claim locks its
row with ``FOR UPDATE SKIP LOCKED`` (``FOR UPDATE`` for a row that must be locked whoever holds it). The recall
ledger (:mod:`orchestrator.recall.ledger`) uses it on schema ``recall``.

The durable step engine (``StepStore``) and the outbox table that lived here, with their schema ``wf``, were never
called by a job and are removed (NEW-ARCH-2, D-524; deep review ARCH-004). How a job resumes is the job row and its
kept answers (D-456); how a mail is sent once is the mail gateway's send keys (D-401).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Literal, Protocol

from tb_common.db import ENV as DB_URL_ENV
from tb_common.db import AppliedVersion, Database, Migration, MigrationChanged, MigrationOrderError

Clock = Callable[[], datetime]
Row = tuple[Any, ...]
Dialect = Literal["postgres"]


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

    def migrate(self, versions: Sequence[str | Migration]) -> int:
        """Checksummed, append-only schema versions (:meth:`tb_common.db.Database.migrate`, D-204)."""
        ...

    def close(self) -> None: ...


class PostgresBackend:
    """One schema of the trial database on its own connection. A new backend is a new connection: what the
    crash tests call a new process."""

    dialect: Dialect = "postgres"
    lock_suffix = " FOR UPDATE SKIP LOCKED"
    row_lock = " FOR UPDATE"

    def __init__(self, url: str | None, schema: str) -> None:
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

    def migrate(self, versions: Sequence[str | Migration]) -> int:
        """:meth:`tb_common.db.Database.migrate`: a changed applied version raises :class:`MigrationChanged`."""
        return self.db.migrate(versions)

    def migrate_dir(self, path: str | os.PathLike[str]) -> int:
        """:meth:`tb_common.db.Database.migrate_dir`: the ``NNN_<name>.sql`` scripts of ``path``."""
        return self.db.migrate_dir(os.fspath(path))

    def applied(self) -> list[AppliedVersion]:
        """This schema's ``_schema_version`` rows (version, checksum, script name, back-filled)."""
        return self.db.applied()

    def close(self) -> None:
        self.db.close()


def open_backend(url: str | None, schema: str) -> SqlBackend:
    """The ``schema`` of the trial database at ``url`` (``TB_DB_URL`` when None)."""
    return PostgresBackend(url, schema)


__all__ = [
    "Clock",
    "MigrationChanged",
    "MigrationOrderError",
    "PostgresBackend",
    "SqlBackend",
    "Tx",
    "canonical_json",
    "epoch_ms",
    "open_backend",
    "sha256_text",
]
