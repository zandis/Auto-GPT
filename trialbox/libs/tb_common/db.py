"""The box's one trial database (TB-PLAN-04 step 2, D-126): every store TrialBox owns lives in PostgreSQL
``trialbox_wf``, one schema per store.

    db = Database.connect(os.environ["TB_DB_URL"], "site")      # schema "site" (search_path), created if missing
    db.migrate([V1_DDL, V2_DDL])                               # versioned, checksummed, recorded in _schema_version
    with db.transaction() as tx:
        tx.execute("INSERT INTO marks (pid, mark) VALUES (?, ?)", (pid, "approach"))
        row = tx.fetchone("SELECT mark FROM marks WHERE pid = ?", (pid,))

SQL uses ``?`` placeholders (turned into psycopg's ``%s``; a literal ``%`` is escaped). One connection per
:class:`Database`, used under a lock, so a store behaves like one serialised writer, as the SQLite files did.

**A lost connection is reopened** (D-142, review A-02). A Postgres restart (secrets rotation, an update, an OOM kill)
or a network blip used to leave the store's connection dead and every later call failing until the service was
restarted. Now each transaction first reopens a connection that psycopg reports closed or broken, and when ``BEGIN``
itself fails on a dead connection (the server went away since the last call, so nothing of the transaction ran) the
store reopens and begins once more. A failure inside a transaction is raised as before (it may have run part of the
work, so it is never repeated), and the next call starts on a fresh connection. One connection per store, not a pool:
the stores rely on one serialised connection, and psycopg_pool would be a new dependency in every image.

``TB_DB_URL`` is a ``postgresql://`` DSN. A ``tb_prefix`` query parameter (``...?tb_prefix=t1234_``) is removed
before connecting and put in front of every schema name: the test suite gives each test its own schemas in one
throwaway cluster (``tools/pglocal.py``), the demo and ``e2e_simple`` their own run.

**Migrations are checksummed** (D-204). A store's schema versions are whole scripts, append-only: ``versions[0]`` is
version 1. Each store keeps its own ``_schema_version`` table in its own schema (so two stores that both reach
version 3 never collide), one row per applied version: ``version``, ``applied_at``, ``sha256`` (hex SHA-256 of the
script's UTF-8 text, exactly as passed, see :func:`script_sha256`), ``script_name``, ``backfilled`` and
``backfilled_at``. On every :meth:`Database.migrate`, under a per-schema advisory lock and in one transaction:

1. applied versions must be exactly ``1..n`` (a gap means a script ran out of order) and a caller's list must number
   its scripts ``1..n`` with no gap or duplicate; otherwise :class:`MigrationOrderError`;
2. a row written before D-204 (no ``sha256``) is back-filled (``backfilled = true``, logged) only when the script the
   code passes for it has the D-204 baseline checksum of its store (:mod:`tb_common.migration_baseline`); any other
   script raises :class:`MigrationChanged`. Once every row of a store carries a checksum the table is marked
   (``COMMENT ON TABLE _schema_version``), and a row without one appearing later (an old release applying a version,
   a hand edit) is refused with :class:`MigrationError`; restoring a pre-D-204 dump brings back an unmarked table,
   which is back-filled against the baseline again. A store without a baseline (a test's schema, ``release``) is
   back-filled from the code, logged;
3. every applied version the caller passes is compared with its record: a different script raises
   :class:`MigrationChanged` naming the store (schema) and the version, and nothing is applied;
4. the versions not yet applied run in order, each recorded with its checksum and name.

A caller that passes fewer versions than are applied (an older release, ``migrate([])`` to read the version) is not
refused here: downgrades are the update path's decision (T-111), which reads :meth:`Database.applied`.
:meth:`Database.migrate_dir` reads a directory of ``NNN_<name>.sql`` files (``001_init.sql``, ``002_...``) as the
version list. The PostgreSQL extensions ``vector`` and ``pgroonga`` exist only on the box's ``db`` image (created by
``deploy/docker/db-init/``, never by a store); :func:`extensions` lists the ones installed.

**One role per service** (D-378, CR-037). On the box each service logs in as its own role (``tb_<service>``) and
reaches only the schemas its list in ``deploy/docker/db-init/30-service-roles.sh`` names. Each of those schemas is
owned by a group role ``tbs_<schema>``; a connection to a schema whose owner is such a group, and whose user is a
member, runs ``SET ROLE`` to the group, so the tables a migration makes belong to the group, not to the one service
that happened to start first. A schema that does not exist yet is created only then (``CREATE SCHEMA`` needs the
database's CREATE right even when the schema exists). Anywhere else (the test clusters, a tool as ``trialbox``
before D-378) nothing changes.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import logging
import re
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

Row = tuple[Any, ...]
ENV = "TB_DB_URL"
_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class DatabaseError(RuntimeError):
    """The trial database is not configured or not reachable."""


class MigrationError(DatabaseError):
    """A store's migrations cannot be applied as given (D-204); the store must not start."""

    def __init__(self, store: str, message: str) -> None:
        super().__init__(f"store {store!r}: {message}")
        self.store = store


class MigrationChanged(MigrationError):
    """An applied schema version's script differs from the one recorded when it ran (D-204)."""

    def __init__(self, store: str, version: int, script_name: str | None, recorded: str, current: str) -> None:
        super().__init__(
            store,
            f"schema version {version} ({script_name or 'unnamed'}) was applied with sha256 {recorded[:12]}... but "
            f"the code now carries sha256 {current[:12]}...: an applied migration was changed; add a new version "
            "instead (D-204)",
        )
        self.version = version
        self.script_name = script_name
        self.recorded = recorded
        self.current = current


class MigrationOrderError(MigrationError):
    """Versions out of order: a gap or a duplicate in the scripts, or a gap in what is applied (D-204)."""


#: D-378: the group role that owns a store's schema on the box is ``tbs_<schema>``; a service role that is a member
#: works in the schema as the group (see ``deploy/docker/db-init/30-service-roles.sh``)
GROUP_PREFIX = "tbs_"


class _NotOurs(Exception):
    """A missing schema that has an owner role this session is not a member of (D-486)."""


# the owner role of a schema exists in this cluster and the session's user is not a member of it
_NOT_OWNER_SQL = "SELECT 1 FROM pg_roles WHERE rolname = %s AND NOT pg_has_role(session_user, oid, 'MEMBER')"
_GROUP_SQL = (
    "SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner "
    "WHERE n.nspname = %s AND r.rolname = %s AND pg_has_role(current_user, r.oid, 'MEMBER')"
)
_OWNING_GROUP_SQL = (
    "SELECT r.rolname FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner "
    "WHERE n.nspname = %s AND r.rolname LIKE %s AND NOT r.rolcanlogin AND pg_has_role(current_user, r.oid, 'MEMBER')"
)
#: D-486 (T-718): a schema on the role script's ``owned`` list belongs to ``tbo_<schema>`` (its one member is
#: ``trialbox``); a service is a member of ``tbw_<schema>`` (rows) or ``tbr_<schema>`` (reads) and makes nothing there
OWNER_PREFIX = "tbo_"
WRITER_PREFIX = "tbw_"
READER_PREFIX = "tbr_"
_OWNER_SQL = (
    "SELECT r.rolname, pg_has_role(session_user, r.oid, 'MEMBER') FROM pg_namespace n "
    "JOIN pg_roles r ON r.oid = n.nspowner WHERE n.nspname = ?"
)
#: the PostgreSQL extensions the box's ``db`` image provides (D-204; ``deploy/docker/db-init/``)
IMAGE_EXTENSIONS = ("vector", "pgroonga")
#: the comment on ``_schema_version`` once every row carries a checksum (D-204): a row without one is refused after it
_COMPLETE = "D-204: every version checksummed"
_log = logging.getLogger(__name__)
_MIGRATION_FILE = re.compile(r"^(\d{3})_[A-Za-z0-9][A-Za-z0-9_.-]*\.sql$")


def script_sha256(script: str) -> str:
    """Hex SHA-256 of a migration script's UTF-8 text, exactly as passed (no whitespace or newline normalisation)."""
    return hashlib.sha256(script.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Migration:
    """One schema version: its number (1-based), its whole script and a name (a file name, or ``v001``)."""

    version: int
    script: str
    name: str

    @property
    def sha256(self) -> str:
        return script_sha256(self.script)


@dataclass(frozen=True)
class AppliedVersion:
    """One row of a store's ``_schema_version`` (``sha256`` and ``script_name`` are None only before back-fill)."""

    store: str
    version: int
    applied_at: datetime
    sha256: str | None
    script_name: str | None
    backfilled: bool
    backfilled_at: datetime | None = None


def as_migrations(versions: Sequence[str | Migration], store: str = "?") -> list[Migration]:
    """Number a version list ``1..n``: a plain string is version ``i`` named ``v00i``; a :class:`Migration` must
    carry its own position (else :class:`MigrationOrderError`)."""
    out: list[Migration] = []
    for n, v in enumerate(versions, start=1):
        if isinstance(v, Migration):
            if v.version != n:
                raise MigrationOrderError(store, f"script {v.name} is version {v.version} but stands at position {n}")
            out.append(v)
        else:
            out.append(Migration(n, v, f"v{n:03d}"))
    return out


def read_migration_dir(path: Path | str, store: str = "?") -> list[Migration]:
    """The ``NNN_<name>.sql`` files of ``path`` as versions ``1..n`` (read as UTF-8, byte for byte). Any other
    ``.sql`` file, a duplicate number or a gap (``001``, ``003``) is refused with :class:`MigrationOrderError`."""
    d = Path(path)
    if not d.is_dir():
        raise MigrationError(store, f"migration directory {d} does not exist")
    found: dict[int, Path] = {}
    for p in sorted(d.iterdir()):
        looks = p.suffix.lower() == ".sql" or re.match(r"^\d{3}_", p.name)
        if not looks:
            continue
        if p.is_symlink() or not p.is_file():  # a link or a folder could point anywhere: only plain files run
            raise MigrationOrderError(store, f"{p.name}: a migration must be a regular file, not a link or a folder")
        m = _MIGRATION_FILE.match(p.name)
        if not m:
            raise MigrationOrderError(store, f"{p.name}: migration files are named NNN_<name>.sql")
        n = int(m.group(1))
        if n in found:
            raise MigrationOrderError(store, f"two scripts for version {n}: {found[n].name} and {p.name}")
        found[n] = p
    for want, n in enumerate(sorted(found), start=1):
        if n != want:
            raise MigrationOrderError(store, f"version {want} is missing before {found[n].name}")
    out = []
    for n in sorted(found):
        try:
            out.append(Migration(n, found[n].read_bytes().decode("utf-8"), found[n].name))
        except UnicodeDecodeError as e:
            raise MigrationError(store, f"{found[n].name} is not UTF-8 text: {e.reason} at byte {e.start}") from e
    return out


def _lost_errors() -> tuple[type[BaseException], ...]:
    try:
        psycopg = importlib.import_module("psycopg")
    except ImportError:  # pragma: no cover
        return (DatabaseError,)
    return (psycopg.OperationalError, psycopg.InterfaceError)


_LOST = _lost_errors()


def split_url(url: str) -> tuple[str, str]:
    """``(dsn without tb_prefix, prefix)``."""
    if not url.startswith(("postgresql://", "postgres://")):
        raise DatabaseError(f"{ENV} must be a postgresql:// URL, got {url.split(':', 1)[0] or 'nothing'}")
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    prefix = "".join(v for k, v in query if k == "tb_prefix")
    rest = urlencode([(k, v) for k, v in query if k != "tb_prefix"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, rest, parts.fragment)), prefix


def ask_once(url: str, text: str, params: Sequence[Any] = ()) -> tuple[Any, ...] | None:
    """One row of one statement on a connection of its own, as the URL's user and with no schema chosen (nothing is
    made, no role is set): what a caller needs to know before it opens a store. None when the database cannot be
    reached or the statement returns no row."""
    dsn, _prefix = split_url(url)
    try:
        psycopg = importlib.import_module("psycopg")
        con = psycopg.connect(dsn, autocommit=True, connect_timeout=10)
    except Exception:
        return None
    try:
        row = con.execute(text, tuple(params)).fetchone()
        return tuple(row) if row is not None else None
    finally:
        con.close()


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

    def __init__(self, con: Any, schema: str, url: str, store: str | None = None) -> None:
        self._con = con
        self.schema = schema
        self.url = url  # with tb_prefix, so a store can open a sibling schema on the same run
        self.store = store if store is not None else schema  # the name given to connect (the schema less tb_prefix)
        self._lock = threading.RLock()
        self.reconnects = 0  # connections reopened after a loss (health detail, tests)

    @staticmethod
    def _open(dsn: str, schema: str) -> Any:
        try:
            psycopg = importlib.import_module("psycopg")
        except ImportError as e:  # pragma: no cover - the package is a hard dependency
            raise DatabaseError("the 'psycopg' package (psycopg 3) is missing") from e
        try:
            con = psycopg.connect(dsn, autocommit=True, connect_timeout=10)
        except Exception as e:  # psycopg.OperationalError and friends
            raise DatabaseError(f"cannot reach the trial database: {type(e).__name__}") from e
        try:
            if con.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone() is None:
                # D-486: a schema with an owner role in this cluster is made by that owner (the install step), never
                # by a service: a service that made it would own its tables and their triggers
                if con.execute(_NOT_OWNER_SQL, ((OWNER_PREFIX + schema)[:63],)).fetchone() is not None:
                    raise _NotOurs(schema)
                con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            con.execute(f'SET search_path TO "{schema}"')
            # D-378: a schema owned by its group role (tbs_<schema>, deploy/docker/db-init/30-service-roles.sh) is
            # used as that role, so what a migration creates belongs to the group and every member service can use it
            group = (GROUP_PREFIX + schema)[:63]
            if con.execute(_GROUP_SQL, (schema, group)).fetchone() is not None:
                con.execute(f'SET ROLE "{group}"')
            else:
                # D-721: a schema that the admin made for another store's group (a second lake's OMOP store, owned
                # by tbs_omop) is used as that group too, by its members, for the same reason
                row = con.execute(_OWNING_GROUP_SQL, (schema, GROUP_PREFIX.replace("_", r"\_") + "%")).fetchone()
                if row is not None:
                    con.execute(f'SET ROLE "{row[0]}"')
            # D-486: a schema with an owner role of its own. The host tools' admin (a member) works as the owner, so
            # the migrate step's tables are the owner's; a service (no member) stays itself and makes nothing
            owner = (OWNER_PREFIX + schema)[:63]
            if con.execute(_GROUP_SQL, (schema, owner)).fetchone() is not None:
                con.execute(f'SET ROLE "{owner}"')
        except _NotOurs as e:
            con.close()
            raise DatabaseError(
                f"the schema {e} is missing and is not this role's to make: run `trialbox migrate` "
                "(after a restore: the role script first)"
            ) from None
        except Exception as e:
            con.close()
            raise DatabaseError(f"cannot use the trial database: {type(e).__name__}") from e
        return con

    @classmethod
    def connect(cls, url: str | None, name: str) -> Database:
        """Connect to the trial database and select (creating if needed) the schema ``<tb_prefix><name>``."""
        if not url:
            raise DatabaseError(f"{ENV} is not set: TrialBox keeps its trial data in PostgreSQL (D-126)")
        dsn, prefix = split_url(url)
        schema = prefix + name
        if not _SCHEMA_RE.match(schema):
            raise DatabaseError(f"bad schema name {schema!r}")
        return cls(cls._open(dsn, schema), schema, url, name)

    def _dead(self) -> bool:
        return bool(getattr(self._con, "closed", False) or getattr(self._con, "broken", False))

    def _reopen(self) -> None:
        """A new connection in place of a lost one (same DSN, same schema)."""
        with contextlib.suppress(Exception):  # already gone
            self._con.close()
        self._con = self._open(split_url(self.url)[0], self.schema)
        self.reconnects += 1

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        with self._lock:
            if self._dead():
                self._reopen()
            txn = self._con.transaction()
            try:
                txn.__enter__()  # BEGIN: on a connection the server dropped, this is where it fails
            except _LOST as e:
                if not self._dead():
                    raise
                self._reopen()  # nothing of the transaction ran: begin once more on a fresh connection
                txn = self._con.transaction()
                txn.__enter__()
                del e
            try:
                with self._con.cursor() as cur:
                    yield Tx(cur)
            except BaseException as exc:
                swallowed = False
                with contextlib.suppress(Exception):  # the rollback failed too (connection lost): next call reopens
                    swallowed = bool(txn.__exit__(type(exc), exc, exc.__traceback__))
                if swallowed:
                    return  # psycopg.Rollback: rolled back and swallowed, as with the plain context manager
                raise
            txn.__exit__(None, None, None)

    def ping(self) -> dict[str, Any]:
        """``SELECT 1`` on this store's connection (a service's ``/healthz`` check); reopens a lost one."""
        self.fetchval("SELECT 1")
        return {f"db:{self.schema}": "ok"}

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

    def owner_role(self) -> str | None:
        """The owner role of this schema (``tbo_<schema>``, D-486) when it has one and this connection is not it:
        the schema's tables, triggers and versions are then the install step's to make, not this caller's. None for
        a schema this connection may migrate (its group's, its own, or as the owner role itself)."""
        row = self.fetchone(_OWNER_SQL, (self.schema,))
        if row is None or not str(row[0]).startswith(OWNER_PREFIX) or bool(row[1]):
            return None
        return str(row[0])

    def writer_role(self) -> str | None:
        """``tbw_<schema>`` when this schema has an owner role and that writer role exists (D-486), else None."""
        name = (WRITER_PREFIX + self.schema)[:63]
        owned = self.fetchval(
            "SELECT 1 FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner WHERE n.nspname = ? AND r.rolname = ?",
            (self.schema, (OWNER_PREFIX + self.schema)[:63]),
        )
        return name if owned and self.fetchval("SELECT 1 FROM pg_roles WHERE rolname = ?", (name,)) else None

    def adopt(self) -> int:
        """The install step's first act on a schema with an owner role (D-486), as the box's admin: what a restore
        or an earlier release left in the schema under the admin's own name becomes the owner role's, and the
        writer's and reader's rights are given again (a restore without privileges drops them). Returns how many
        objects moved; 0 and nothing done on a schema without an owner role, or for a caller who is not a member."""
        owner = (OWNER_PREFIX + self.schema)[:63]
        if self.fetchval("SELECT current_user") != owner:
            return 0
        moved = 0
        with self.transaction() as tx:
            tx.execute("RESET ROLE")  # the admin owns what the restore made; only an owner gives an object away
            try:
                kinds = {"v": "VIEW", "m": "MATERIALIZED VIEW", "S": "SEQUENCE", "f": "FOREIGN TABLE"}
                for name, kind in tx.fetchall(
                    "SELECT c.relname, c.relkind FROM pg_class c WHERE c.relnamespace = ?::regnamespace "
                    "AND c.relowner = session_user::regrole AND (c.relkind IN ('r', 'p', 'v', 'm', 'f') OR "
                    "(c.relkind = 'S' AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass "
                    "AND d.objid = c.oid AND d.deptype IN ('a', 'i'))))",
                    (self.schema,),
                ):
                    tx.execute(f'ALTER {kinds.get(str(kind), "TABLE")} "{self.schema}"."{name}" OWNER TO "{owner}"')
                    moved += 1
                for (sig,) in tx.fetchall(
                    "SELECT p.oid::regprocedure::text FROM pg_proc p WHERE p.pronamespace = ?::regnamespace "
                    "AND p.proowner = session_user::regrole",
                    (self.schema,),
                ):
                    tx.execute(f'ALTER ROUTINE {sig} OWNER TO "{owner}"')
                    moved += 1
            finally:
                tx.execute(f'SET ROLE "{owner}"')
            for prefix, rights in ((WRITER_PREFIX, "SELECT, INSERT, UPDATE, DELETE"), (READER_PREFIX, "SELECT")):
                role = (prefix + self.schema)[:63]
                if tx.fetchval("SELECT 1 FROM pg_roles WHERE rolname = ?", (role,)):
                    tx.execute(f'GRANT {rights} ON ALL TABLES IN SCHEMA "{self.schema}" TO "{role}"')
                    if prefix == WRITER_PREFIX:
                        tx.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{self.schema}" TO "{role}"')
        return moved

    def _check_versions(self, migs: Sequence[Migration], owner: str) -> int:
        """What a service does in place of migrating a schema it does not own (D-486): the applied versions must be
        the ones this release carries, by checksum. It makes and changes nothing."""
        try:
            rows = self.fetchall("SELECT version, sha256, script_name FROM _schema_version ORDER BY version")
        except Exception as exc:
            raise MigrationError(
                self.schema, f"has no version table yet: its owner ({owner}) makes it; run `trialbox migrate` (D-486)"
            ) from exc
        applied = [int(r[0]) for r in rows]
        if applied != list(range(1, len(applied) + 1)):
            gap = next(n for n, v in enumerate(applied, start=1) if v != n)
            raise MigrationOrderError(
                self.schema, f"applied versions {applied} skip version {gap}: a script was applied out of order"
            )
        for (n, recorded, name), mig in zip(rows, migs, strict=False):
            if recorded is None:
                raise MigrationError(
                    self.schema,
                    f"schema version {n} has no checksum: run `trialbox migrate` as the box's admin (D-486)",
                )
            if recorded != mig.sha256:
                raise MigrationChanged(self.schema, int(n), name, str(recorded), mig.sha256)
        if len(applied) < len(migs):
            raise MigrationError(
                self.schema,
                f"is at version {len(applied)} and this release needs {len(migs)}: its owner ({owner}) applies them; "
                "run `trialbox migrate` (D-486)",
            )
        return len(migs)

    def migrate(self, versions: Sequence[str | Migration]) -> int:
        """Apply the schema versions not yet applied; return ``len(versions)``.

        D-486 (T-718): on a schema with an owner role this connection is not a member of, nothing is applied: the
        versions are checked against this release (:meth:`_check_versions`) and a schema that is behind is refused
        with what to run.

        Versions are append-only: ``versions[0]`` is version 1. A script is split on ``;`` and run statement by
        statement (so no ``;`` inside a literal or a ``$$`` body). The whole call is one transaction under a per-schema
        advisory lock, in this order: the order check (:class:`MigrationOrderError`), the baseline-gated back-fill of
        pre-D-204 rows and the refusal of rows without a checksum after it (:class:`MigrationError`), the checksum
        check of every applied version passed (:class:`MigrationChanged`), then each new version runs and is
        recorded with its ``sha256`` and ``script_name``. Any refusal or failure leaves the store as it was.
        """
        from tb_common.migration_baseline import baseline_for

        migs = as_migrations(versions, self.schema)
        owner = self.owner_role()
        if owner is not None:
            return self._check_versions(migs, owner)
        with self.transaction() as tx:
            # one migrator at a time per schema (two services starting together)
            tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (self.schema,))
            tx.execute(
                "CREATE TABLE IF NOT EXISTS _schema_version (version BIGINT PRIMARY KEY, applied_at TIMESTAMPTZ "
                "NOT NULL DEFAULT now())"
            )
            cols = {
                str(r[0])
                for r in tx.fetchall(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                    "AND table_name = '_schema_version'"
                )
            }
            if not {"sha256", "script_name", "backfilled", "backfilled_at"} <= cols:  # the D-204 columns, once
                tx.execute(
                    "ALTER TABLE _schema_version ADD COLUMN IF NOT EXISTS sha256 TEXT, "
                    "ADD COLUMN IF NOT EXISTS script_name TEXT, "
                    "ADD COLUMN IF NOT EXISTS backfilled BOOLEAN NOT NULL DEFAULT false, "
                    "ADD COLUMN IF NOT EXISTS backfilled_at TIMESTAMPTZ"
                )
            rows = tx.fetchall("SELECT version, sha256, script_name FROM _schema_version ORDER BY version")
            applied = [int(r[0]) for r in rows]
            if applied != list(range(1, len(applied) + 1)):
                gap = next(n for n, v in enumerate(applied, start=1) if v != n)
                raise MigrationOrderError(
                    self.schema, f"applied versions {applied} skip version {gap}: a script was applied out of order"
                )
            complete = tx.fetchval("SELECT obj_description('_schema_version'::regclass, 'pg_class')") == _COMPLETE
            unsummed = [int(r[0]) for r in rows if r[1] is None]
            if unsummed and complete:
                raise MigrationError(
                    self.schema,
                    f"schema version(s) {unsummed} have no checksum although every version had one: a version was "
                    "applied by a release older than D-204 or the record was edited; restore or re-apply (D-204)",
                )
            base = baseline_for(self.store)
            for (n, recorded, name), mig in zip(rows, migs, strict=False):
                if recorded is None:  # applied before D-204: back-fill once, against the baseline when there is one
                    if base is not None:
                        if n > len(base):
                            raise MigrationError(
                                self.schema, f"schema version {n} has no checksum and is newer than the D-204 baseline"
                            )
                        if mig.sha256 != base[n - 1]:
                            raise MigrationChanged(self.schema, int(n), mig.name, base[n - 1], mig.sha256)
                    _log.warning(
                        "store %r: schema version %d back-filled with sha256 %s (%s, D-204)",
                        self.schema,
                        n,
                        mig.sha256,
                        "matches the baseline" if base is not None else "no baseline for this store: code trusted",
                    )
                    tx.execute(
                        "UPDATE _schema_version SET sha256 = ?, script_name = ?, backfilled = true, "
                        "backfilled_at = now() WHERE version = ?",
                        (mig.sha256, mig.name, n),
                    )
                elif recorded != mig.sha256:
                    raise MigrationChanged(self.schema, int(n), name, str(recorded), mig.sha256)
            for mig in migs[len(applied) :]:
                for stmt in (s.strip() for s in mig.script.split(";")):
                    if stmt:
                        tx.execute(stmt)
                tx.execute(
                    "INSERT INTO _schema_version (version, sha256, script_name) VALUES (?, ?, ?)",
                    (mig.version, mig.sha256, mig.name),
                )
            if not complete and not tx.fetchval("SELECT count(*) FROM _schema_version WHERE sha256 IS NULL"):
                tx.execute(f"COMMENT ON TABLE _schema_version IS '{_COMPLETE}'")
            return len(migs)

    def migrate_dir(self, path: Path | str) -> int:
        """:meth:`migrate` with the ``NNN_<name>.sql`` scripts of ``path`` (:func:`read_migration_dir`)."""
        return self.migrate(read_migration_dir(path, self.schema))

    def applied(self) -> list[AppliedVersion]:
        """This store's ``_schema_version`` rows in version order (empty when nothing was ever migrated)."""
        with self.transaction() as tx:
            have = tx.fetchall(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                "AND table_name = '_schema_version'"
            )
            cols = {str(r[0]) for r in have}
            if not cols:
                return []
            if "sha256" not in cols:  # not yet migrated under D-204
                rows = tx.fetchall(
                    "SELECT version, applied_at, NULL, NULL, false, NULL FROM _schema_version ORDER BY 1"
                )
            else:
                bf_at = "backfilled_at" if "backfilled_at" in cols else "NULL"
                rows = tx.fetchall(
                    f"SELECT version, applied_at, sha256, script_name, backfilled, {bf_at} FROM _schema_version "
                    "ORDER BY 1"
                )
        return [
            AppliedVersion(self.schema, int(v), at, sha, name, bool(bf), bfat) for v, at, sha, name, bf, bfat in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def extensions(db: Database, names: Sequence[str] = IMAGE_EXTENSIONS) -> dict[str, str | None]:
    """``{name: installed version or None}`` of the PostgreSQL extensions ``names`` in ``db``'s database."""
    rows: dict[str, str] = {
        str(n): str(v)
        for n, v in db.fetchall("SELECT extname, extversion FROM pg_extension WHERE extname = ANY(?)", (list(names),))
    }
    return {n: rows.get(n) for n in names}


def require_extensions(db: Database, names: Sequence[str] = IMAGE_EXTENSIONS) -> dict[str, str]:
    """``{name: version}`` of ``names`` in ``db``'s database, or :class:`DatabaseError` naming the missing ones: the
    check a start-up, ``doctor`` or a healthcheck runs on the box's database image (D-204; the container's own is
    ``tb-db-check``)."""
    got = extensions(db, names)
    missing = [n for n, v in got.items() if v is None]
    if missing:
        raise DatabaseError(
            f"the trial database lacks the extension(s) {', '.join(missing)}: the box's db image creates them on its "
            "first start (deploy/docker/db-init/20-extensions.sh, D-204)"
        )
    return {n: str(v) for n, v in got.items()}
