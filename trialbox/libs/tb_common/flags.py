"""Feature flags (MR-090, T-008, D-207): one audited table, read by every service without a restart.

    flags = Flags(Database.connect(os.environ["TB_DB_URL"], SCHEMA), audit=AuditLog(audit_dir))
    flags.seed()                                         # at a service's start: the first start pins each flag
    flags.get("lake.source", "legacy")                   # never raises for a declared name; a 5-second cache
    flags.set("lake.source", "omop", actor="console:admin", reason="WS-03.5 flip after the goldens held")

**Where.** Schema ``app`` of the trial database (``TB_DB_URL``, ``tb_prefix`` honoured): ``flag`` holds the value of
each flag that was ever seeded or set, ``flag_event`` every seed and every change (old value, new value, actor,
reason). A change is one ``flag_event`` row and one audit event (``flag.set``, with actor and reason), in one
transaction: if the audit write fails the change is rolled back.

**Declared names only.** :data:`DECLARED` lists every flag with its values, its default and the environment variable
that may seed it; any other name is refused with ``ValueError`` (a programming error, not a runtime one), as is a value
outside the declared ones.

**The environment seeds, it is not read at call time.** :meth:`Flags.seed` (called when a service starts: the console
at ``create_app``) writes, for each declared flag that has no row yet, the value of its seed variable
(``TB_LAKE_SOURCE`` for ``lake.source``) or the declared default, as a ``seed`` event. After that first start the
variable is ignored: a different value in the environment is logged at every start and reported by ``trialbox
doctor`` (:func:`env_drift`). Before any service has started (a fresh test database, a tool run on its own lakes)
there is no row, and the caller's default applies.

**Reading never raises.** :meth:`Flags.get` returns the caller's default when the flag has no row, when the store is
not installed, and on any error (logged). Values are cached for :data:`CACHE_SECONDS` per process, so a change made
on ``/ops/flags`` reaches every service within five seconds, without a restart. A reader that must not change its
behaviour mid-work reads the flag once when the work starts and keeps the value (the lake rebuild does).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tb_common.db import ENV as DB_URL_ENV
from tb_common.db import Database

log = logging.getLogger("tb.flags")

SCHEMA = "app"
CACHE_SECONDS = 5.0
SEED_ACTOR = "install:seed"
MAX_REASON = 500

#: ``migrate`` versions of schema ``app`` (append-only)
MIGRATIONS = (
    """
CREATE TABLE IF NOT EXISTS flag (
  name TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  changed_by TEXT NOT NULL,
  reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flag_event (
  id BIGSERIAL PRIMARY KEY,
  at TIMESTAMPTZ NOT NULL DEFAULT now(),
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('seed', 'set')),
  old_value TEXT,
  new_value TEXT NOT NULL,
  actor TEXT NOT NULL,
  reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS flag_event_name ON flag_event (name, id)
""",
)


@dataclass(frozen=True)
class Declared:
    values: tuple[str, ...]
    default: str
    seed_env: str | None
    help: str


#: every flag the box knows; an undeclared name is refused
DECLARED: dict[str, Declared] = {
    "lake.source": Declared(
        values=("legacy", "omop"),
        default="legacy",
        seed_env="TB_LAKE_SOURCE",
        help="Where the screening lake's rows come from at the next rebuild: flattened from the FHIR snapshot "
        "(legacy) or exported from the OMOP store of record (omop). D-151, WS-03.5.",
    ),
}


def declared(name: str) -> Declared:
    d = DECLARED.get(name)
    if d is None:
        raise ValueError(f"undeclared flag {name!r}: declare it in tb_common.flags.DECLARED")
    return d


def check_value(name: str, value: str) -> str:
    d = declared(name)
    v = (value or "").strip().lower()
    if v not in d.values:
        raise ValueError(f"{name}={value!r}: use one of {', '.join(d.values)}")
    return v


def seed_value(name: str, env: dict[str, str] | None = None) -> str:
    """The value a flag is seeded with at the first start: its seed variable, else the declared default. A seed
    variable with a value outside the declared ones is refused (never guessed)."""
    d = declared(name)
    raw = (env if env is not None else os.environ).get(d.seed_env or "", "") if d.seed_env else ""
    if not raw.strip():
        return d.default
    try:
        return check_value(name, raw)
    except ValueError as e:
        raise ValueError(f"{d.seed_env}={raw!r}: use one of {', '.join(d.values)}") from e


# one cache per process: (url, name) -> (value or None for "no row", monotonic time read)
_CACHE: dict[tuple[str, str], tuple[str | None, float]] = {}
_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


class Flags:
    """The flag store in ``db`` (schema ``app``), or in ``TB_DB_URL`` opened per read when no ``db`` is given (so a
    process that only reads a flag now and then holds no connection)."""

    def __init__(
        self,
        db: Database | None = None,
        *,
        url: str | None = None,
        audit: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = db
        self._url = url or (db.url if db is not None else None) or os.environ.get(DB_URL_ENV) or ""
        self.audit = audit
        self.clock = clock

    # ------------------------------------------------------------------ plumbing
    def _open(self) -> tuple[Database, bool]:
        if self._db is not None:
            return self._db, False
        if not self._url:
            raise LookupError(f"{DB_URL_ENV} is not set: no flag store")
        return Database.connect(self._url, SCHEMA), True

    def install(self, db: Database) -> None:
        db.migrate(MIGRATIONS)

    def _key(self, name: str) -> tuple[str, str]:
        return (self._url, name)

    # ------------------------------------------------------------------ read
    def row(self, name: str) -> str | None:
        """The stored value, None when the flag has no row (or the store is not installed). Raises on errors."""
        declared(name)
        db, close = self._open()
        try:
            with db.transaction() as tx:
                if tx.fetchval("SELECT to_regclass('flag')") is None:
                    return None
                v = tx.fetchval("SELECT value FROM flag WHERE name = ?", (name,))
        finally:
            if close:
                db.close()
        return None if v is None else str(v)

    def get(self, name: str, default: str | None = None) -> str | None:
        """The flag's value; ``default`` when it has no row, when the store is unreachable or on any error (logged).
        Never raises for a declared name; an undeclared one is a ``ValueError``."""
        d = declared(name)
        key = self._key(name)
        now = self.clock()
        with _CACHE_LOCK:
            hit = _CACHE.get(key)
        if hit is not None and now - hit[1] < CACHE_SECONDS:
            return hit[0] if hit[0] is not None else default
        try:
            value = self.row(name)
        except Exception as e:  # never raise: the default, logged (the store is down, not installed, no URL)
            if isinstance(e, LookupError):
                log.debug("flag %s: %s; using the default %r", name, e, default)
            else:
                log.warning("flag %s unreadable (%s: %s); using the default %r", name, type(e).__name__, e, default)
            return default
        if value is not None and value not in d.values:
            log.error("flag %s holds %r, not one of %s; using the default %r", name, value, d.values, default)
            return default
        with _CACHE_LOCK:
            _CACHE[key] = (value, now)
        return value if value is not None else default

    def all(self) -> list[dict[str, Any]]:
        """Every declared flag with its stored value (None when never seeded) and when, by whom and why it changed."""
        db, close = self._open()
        try:
            self.install(db)
            rows = {r["name"]: r for r in db.fetchdicts("SELECT name, value, changed_at, changed_by, reason FROM flag")}
        finally:
            if close:
                db.close()
        out = []
        for name, d in sorted(DECLARED.items()):
            r = rows.get(name) or {}
            out.append({"name": name, "values": list(d.values), "default": d.default, "help": d.help,
                        "seed_env": d.seed_env, "value": r.get("value"), "changed_at": r.get("changed_at"),
                        "changed_by": r.get("changed_by"), "reason": r.get("reason")})  # fmt: skip
        return out

    def events(self, name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        db, close = self._open()
        try:
            self.install(db)
            where, params = ("WHERE name = ?", [name]) if name else ("", [])
            return db.fetchdicts(
                "SELECT id, at, name, kind, old_value, new_value, actor, reason FROM flag_event "
                f"{where} ORDER BY id DESC LIMIT ?",
                (*params, int(limit)),
            )
        finally:
            if close:
                db.close()

    # ------------------------------------------------------------------ write
    def seed(self, env: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """The first start: every declared flag without a row gets its seed value (one ``seed`` event and one audit
        event each). A flag that has a row keeps it; a seed variable that now says otherwise is logged (doctor
        reports it too). Returns what was seeded."""
        environ = env if env is not None else dict(os.environ)
        if self.audit is None:
            raise ValueError("a flag seed must be audited: give Flags an audit log")
        db, close = self._open()
        seeded: list[dict[str, Any]] = []
        try:
            self.install(db)
            for name, d in sorted(DECLARED.items()):
                value = seed_value(name, environ)
                origin = d.seed_env if d.seed_env and (environ.get(d.seed_env) or "").strip() else "the default"
                reason = f"seeded at the first start from {origin}"
                with db.transaction() as tx:
                    n = tx.execute(
                        "INSERT INTO flag (name, value, changed_by, reason) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT (name) DO NOTHING",
                        (name, value, SEED_ACTOR, reason),
                    )
                    if n == 1:
                        tx.execute(
                            "INSERT INTO flag_event (name, kind, old_value, new_value, actor, reason) "
                            "VALUES (?, 'seed', NULL, ?, ?, ?)",
                            (name, value, SEED_ACTOR, reason),
                        )
                        self.audit.append("flag.seed", actor=SEED_ACTOR,
                                          detail={"flag": name, "value": value, "reason": reason})  # fmt: skip
                        seeded.append({"name": name, "value": value, "origin": origin})
                    else:
                        have = tx.fetchval("SELECT value FROM flag WHERE name = ?", (name,))
                        if d.seed_env and (environ.get(d.seed_env) or "").strip() and have != value:
                            log.warning("%s=%s in the environment is ignored: the flag %s is %s (change it on "
                                        "/ops/flags)", d.seed_env, environ.get(d.seed_env), name, have)  # fmt: skip
        finally:
            if close:
                db.close()
        with _CACHE_LOCK:
            for s in seeded:
                _CACHE.pop(self._key(s["name"]), None)
        return seeded

    def set(self, name: str, value: str, actor: str, reason: str) -> dict[str, Any]:
        """Change a flag: one ``flag_event`` row and one audit event with the actor and the reason, or nothing. A
        reason and an actor are required; the value must be one of the declared ones and differ from the stored."""
        v = check_value(name, value)
        why = " ".join((reason or "").split())[:MAX_REASON]
        if not why:
            raise ValueError("a flag change needs a reason")
        if not (actor or "").strip():
            raise ValueError("a flag change needs an actor")
        if self.audit is None:
            raise ValueError("a flag change must be audited: give Flags an audit log")
        db, close = self._open()
        try:
            self.install(db)
            with db.transaction() as tx:
                tx.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (f"flag:{name}",))
                old = tx.fetchval("SELECT value FROM flag WHERE name = ?", (name,))
                if old == v:
                    raise ValueError(f"{name} is already {v}")
                tx.execute(
                    "INSERT INTO flag (name, value, changed_by, reason) VALUES (?, ?, ?, ?) ON CONFLICT (name) DO "
                    "UPDATE SET value = EXCLUDED.value, changed_at = now(), changed_by = EXCLUDED.changed_by, "
                    "reason = EXCLUDED.reason",
                    (name, v, actor, why),
                )
                event_id = tx.fetchval(
                    "INSERT INTO flag_event (name, kind, old_value, new_value, actor, reason) "
                    "VALUES (?, 'set', ?, ?, ?, ?) RETURNING id",
                    (name, old, v, actor, why),
                )
                # inside the transaction: an audit write that fails (a full disk) rolls the change back
                detail = {"flag": name, "old": old, "new": v, "reason": why, "event": event_id}
                self.audit.append("flag.set", actor=actor, detail=detail)
        finally:
            if close:
                db.close()
        with _CACHE_LOCK:
            _CACHE.pop(self._key(name), None)
        return {"name": name, "old": old, "new": v, "actor": actor, "reason": why, "event": event_id}


def read(name: str, url: str | None = None) -> str | None:
    """The stored value of a declared flag in ``url`` (default ``TB_DB_URL``) through the cache; None when it has no
    row, no store is configured, or the store cannot be read (logged). Never raises for a declared name."""
    return Flags(url=url).get(name, None)


def env_drift(env: dict[str, str], url: str | None = None) -> list[str]:
    """The seed variables set in ``env`` that disagree with their flag (ignored since the first start), or whose flag
    was never seeded (the variable still decides until a service seeds it)."""
    out = []
    for name, d in sorted(DECLARED.items()):
        raw = (env.get(d.seed_env) or "").strip() if d.seed_env else ""
        if not raw:
            continue
        have = Flags(url=url or env.get(DB_URL_ENV)).row(name)
        if have is None:
            out.append(f"{d.seed_env}={raw} still decides: the flag {name} was never seeded (no console start yet)")
        elif have != raw.lower():
            out.append(f"{d.seed_env}={raw} is ignored: the flag {name} is {have} (change it on /ops/flags)")
    return out
