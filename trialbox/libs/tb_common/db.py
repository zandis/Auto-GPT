"""The box's one trial database (TB-PLAN-04 step 2, D-126): every store TrialBox owns lives in PostgreSQL
``trialbox_wf``, one schema per store.

    db = Database.connect(os.environ["TB_DB_URL"], "site")      # schema "site" (search_path), created if missing
    db.migrate([V1_DDL, V2_DDL])                               # versioned, idempotent, recorded in _schema_version
    with db.transaction() as tx:
        tx.execute("INSERT INTO marks (pid, mark) VALUES (?, ?)", (pid, "approach"))
        row = tx.fetchone("SELECT mark FROM marks WHERE pid = ?", (pid,))

SQL uses ``?`` placeholders (turned into psycopg's ``%s``; a literal ``%`` is escaped). One connection per
:class:`Database`, used under a lock, so a store behaves like one serialised writer, as the SQLite files did.

``TB_DB_URL`` is a ``postgresql://`` DSN. A ``tb_prefix`` query parameter (``...?tb_prefix=t1234_``) is removed
before connecting and put in front of every schema name: the test suite gives each test its own schemas in one
throwaway cluster (``tools/pglocal.py``), the demo and ``e2e_simple`` their own run.
"""

from __future__ import annotations

import importlib
import re
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

Row = tuple[Any, ...]
ENV = "TB_DB_URL"
_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class DatabaseError(RuntimeError):
    """The trial database is not configured or not reachable."""


def split_url(url: str) -> tuple[str, str]:
    """``(dsn without tb_prefix, prefix)``."""
    if not url.startswith(("postgresql://", "postgres://")):
        raise DatabaseError(f"{ENV} must be a postgresql:// URL, got {url.split(':', 1)[0] or 'nothing'}")
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    prefix = "".join(v for k, v in query if k == "tb_prefix")
    rest = urlencode([(k, v) for k, v in query if k != "tb_prefix"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, rest, parts.fragment)), prefix


def sql(text: str) -> str:
    """``?`` placeholders -> ``%s``; literal ``%`` escaped."""
    return text.replace("%", "%%").replace("?", "%s")


class Tx:
    """One open transaction."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    def execute(self, text: str, params: Sequence[Any] = ()) -> int:
        """Run a statement; return the affected row count."""
        self._cur.execute(sql(text), tuple(params))
        return int(self._cur.rowcount)

    def executemany(self, text: str, rows: Sequence[Sequence[Any]]) -> None:
        if rows:
            self._cur.executemany(sql(text), [tuple(r) for r in rows])

    def copy_rows(self, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
        """``COPY table (columns) FROM STDIN`` (bulk loads, e.g. the reference data pack); return the row count."""
        if not (_SCHEMA_RE.match(table) and all(_SCHEMA_RE.match(c) for c in columns)):
            raise DatabaseError(f"bad table or column name in COPY {table}")
        n = 0
        with self._cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(tuple(r))
                n += 1
        return n

    def fetchone(self, text: str, params: Sequence[Any] = ()) -> Row | None:
        self._cur.execute(sql(text), tuple(params))
        row = self._cur.fetchone()
        return tuple(row) if row is not None else None

    def fetchall(self, text: str, params: Sequence[Any] = ()) -> list[Row]:
        self._cur.execute(sql(text), tuple(params))
        return [tuple(r) for r in self._cur.fetchall()]

    def fetchval(self, text: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = self.fetchone(text, params)
        return default if row is None else row[0]

    def fetchdicts(self, text: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Rows as ``{column: value}`` (the column names of the query)."""
        self._cur.execute(sql(text), tuple(params))
        names = [d.name for d in self._cur.description or []]
        return [dict(zip(names, r, strict=True)) for r in self._cur.fetchall()]


class Database:
    """One store's schema in the trial database, on its own connection."""

    def __init__(self, con: Any, schema: str, url: str) -> None:
        self._con = con
        self.schema = schema
        self.url = url  # with tb_prefix, so a store can open a sibling schema on the same run
        self._lock = threading.RLock()

    @classmethod
    def connect(cls, url: str | None, name: str) -> Database:
        """Connect to the trial database and select (creating if needed) the schema ``<tb_prefix><name>``."""
        if not url:
            raise DatabaseError(f"{ENV} is not set: TrialBox keeps its trial data in PostgreSQL (D-126)")
        dsn, prefix = split_url(url)
        schema = prefix + name
        if not _SCHEMA_RE.match(schema):
            raise DatabaseError(f"bad schema name {schema!r}")
        try:
            psycopg = importlib.import_module("psycopg")
        except ImportError as e:  # pragma: no cover - the package is a hard dependency
            raise DatabaseError("the 'psycopg' package (psycopg 3) is missing") from e
        try:
            con = psycopg.connect(dsn, autocommit=True, connect_timeout=10)
        except Exception as e:  # psycopg.OperationalError and friends
            raise DatabaseError(f"cannot reach the trial database: {type(e).__name__}") from e
        con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        con.execute(f'SET search_path TO "{schema}"')
        return cls(con, schema, url)

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        with self._lock, self._con.transaction(), self._con.cursor() as cur:
            yield Tx(cur)

    # one-statement helpers (each its own transaction)
    def execute(self, text: str, params: Sequence[Any] = ()) -> int:
        with self.transaction() as tx:
            return tx.execute(text, params)

    def fetchone(self, text: str, params: Sequence[Any] = ()) -> Row | None:
        with self.transaction() as tx:
            return tx.fetchone(text, params)

    def fetchall(self, text: str, params: Sequence[Any] = ()) -> list[Row]:
        with self.transaction() as tx:
            return tx.fetchall(text, params)

    def fetchval(self, text: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        with self.transaction() as tx:
            return tx.fetchval(text, params, default)

    def fetchdicts(self, text: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.transaction() as tx:
            return tx.fetchdicts(text, params)

    def migrate(self, versions: Sequence[str]) -> int:
        """Apply the DDL versions not yet applied (each a ``;``-separated script); return the schema version.

        Versions are append-only: ``versions[0]`` is version 1. A version runs in one transaction with its record.
        """
        with self.transaction() as tx:
            tx.execute(
                "CREATE TABLE IF NOT EXISTS _schema_version (version BIGINT PRIMARY KEY, applied_at TIMESTAMPTZ "
                "NOT NULL DEFAULT now())"
            )
            # one migrator at a time per schema (two services starting together)
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (self.schema,))
            have = int(tx.fetchval("SELECT COALESCE(MAX(version), 0) FROM _schema_version", default=0))
            for n, script in enumerate(versions, start=1):
                if n <= have:
                    continue
                for stmt in (s.strip() for s in script.split(";")):
                    if stmt:
                        tx.execute(stmt)
                tx.execute("INSERT INTO _schema_version (version) VALUES (?)", (n,))
            return len(versions)

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
