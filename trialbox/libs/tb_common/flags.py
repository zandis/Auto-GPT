"""Feature flags (MR-090, T-008, D-207): one audited table, read by every service without a restart.

    flags = Flags(Database.connect(os.environ["TB_DB_URL"], SCHEMA), audit=open_audit(audit_dir))
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

**Reading creates nothing.** :meth:`Flags.row`, :meth:`Flags.get`, :func:`read` and :func:`env_drift` (``trialbox
doctor``, the lake rebuild) create no schema and no table: a read-only role can read a flag, and looking at a database
never changes it. :meth:`Flags.all` and :meth:`Flags.events` (the ``/ops/flags`` page) create no table. Only
:meth:`Flags.seed` and :meth:`Flags.set` install the store.

**A commit that fails after the audit event is named.** The audit event of a change is written inside the
transaction, so a failed audit write rolls the change back. When the commit itself then fails, the audit trail holds a
``flag.set`` for a change that did not happen; :meth:`Flags.set` appends a ``flag.set.failed`` event naming it.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from tb_common.db import ENV as DB_URL_ENV
from tb_common.db import Database, DatabaseError, split_url

log = logging.getLogger("tb.flags")

SCHEMA = "app"
CACHE_SECONDS = 5.0
SEED_ACTOR = "install:seed"
MAX_REASON = 500
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")  # a schema name, as tb_common.db accepts it

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
    "derived.stored_read": Declared(
        values=("off", "on"),
        default="off",
        seed_env=None,  # switched on by the administrator with a reason once a real run proved it (D-442)
        help="Screening reads the stored derived rows (D-442): on, a decided answer on CDAI, SDAI, DAS28 or eGFR "
        "stands only on the stored row of the snapshot's derive batch, on every path (SCREEN, MICROBATCH, NAV, CASE, "
        "COHORT), else it is 'needs information'; off, no path reads the store. Off until the age rule, the pinned "
        "reads and the missing-batch warnings are proven on a real run.",
    ),
    "demo.mode": Declared(
        values=("off", "on"),
        default="off",
        seed_env="TB_DEMO_MODE",
        help="PoC demonstration mode (T-502, D-328): uploads and pasted chart text are refused, a banner says "
        "synthetic data only and not a medical device on every page, and each account accepts the acknowledgement "
        "once (audit event demo.ack) before it opens any other page.",
    ),
    "layout.phone_first": Declared(
        values=("off", "on"),
        default="off",
        seed_env=None,  # what a phone shows first changes only by a person's ruling, with a reason (D-1222)
        help="The console's phone-first layout (J-3, D-1222): on a phone the week list comes first under the title "
        "and the study's links fold into one 'Study' fold below it, the list's rows are cards, the menu's 'More' folds "
        "in two levels, and the patient sheet shows the evidence before the mark's note and reason. Off: the pages "
        "as before. A page uses the value last read: the console reads the layout flags at its start and then in "
        "the background at most every 5 seconds, so a change shows within about 5 seconds; no restart.",
    ),
    "layout.home_today": Declared(
        values=("off", "on"),
        default="off",
        seed_env=None,  # what the opening page shows first changes only by a person's ruling, with a reason (D-1225)
        help="The opening page's 'Needs you today' and 'Next' (J-6, D-1225): on, /home gives the coordinator, the "
        "investigator, the CRO and the viewer at most five lines of what needs them today (safety first, then "
        "overdue, then due today), then one 'Next' line per study, from start-up to archive. Off: the opening pages "
        "as before. A page uses the value last read: the console reads the layout flags at its start and then in "
        "the background at most every 5 seconds, so a change shows within about 5 seconds; no restart.",
    ),
    "lake.source": Declared(
        values=("legacy", "omop"),
        default="legacy",
        seed_env="TB_LAKE_SOURCE",
        help="Where the screening lake's rows come from at the next rebuild: flattened from the FHIR snapshot "
        "(legacy) or exported from the OMOP store of record (omop). D-151, WS-03.5.",
    ),
    "notes.reading": Declared(
        values=("on", "off"),
        default="on",
        seed_env=None,  # a hold is an operator's act with a reason, never a value left in an environment file
        help="Note reading by the models (T-609, OPS-042): off holds it. Every note-stage call after the change asks "
        "no model (the answer is unknown, not evaluated, and the patient goes to review), no note answer excludes, "
        "and a run whose note stage ends under the hold drops its note answers. Hold and release with `trialbox "
        "model hold|release` (release needs a passing pair canary run after the hold; RUNBOOK §19).",
    ),
    "screening.after_restore": Declared(
        values=("released", "held"),
        default="released",
        seed_env=None,  # set by a restore that is not complete, released by a person with a reason; never by a file
        help="The hold after a restore (NEW-B-3, D-522): a restore that is not complete (audit events after the "
        "backup's snapshot to re-apply, opt-outs that could not be put back or are unknown) sets it to held. While "
        "it is held the scheduler starts no list job (SCREEN, MICROBATCH, COHORT, NAV) and a list job a person asks "
        "for fails at its first step. A person releases it on /ops/flags with the reason, after the events were "
        "re-applied (RUNBOOK §5).",
    ),
    "vec.s2b": Declared(
        values=("off", "on"),
        default="off",
        seed_env=None,  # switched on /ops/flags with a reason, after the S2b threshold refit of D-429, never by a file
        help="S2b of the screening cascade ranks a patient's window sentences from the vector store (schema vec, "
        "T-203b, D-449) instead of embedding them on the fly. Read once when a run starts. A store that is "
        "unavailable, not indexed from the run's pinned snapshot or of another model falls back to the on-the-fly "
        "path for that pair, and the patient's trace records it; S2b never excludes in screening either way.",
    ),
    "steps.acting_role": Declared(
        values=("off", "on"),
        default="off",
        seed_env=None,  # switched on with a reason on a test box only (STEPS-ROLE, D-877); never by a file
        help="A test box (TB_ENV DEV or TEST) only: an account granted extra roles at boot (console.steps_roles) may "
        "switch the role it acts in from the top bar, each switch audited (role.acting). Every permission check reads "
        "the acting role; the person stays named in the audit trail and the delegation log. Refused, and the console "
        "refuses to start with it on, when TB_ENV is VALIDATION or PRODUCTION (D-1063).",
    ),
    "omop.dual_write": Declared(
        values=("off", "on"),
        default="off",
        seed_env="TB_OMOP_DUAL_WRITE",
        help="The adapter also loads each night's passed snapshot into the OMOP store of record as soon as its NDJSON "
        "is written, before and apart from the lake rebuild; a failed load never holds the night (T-106, D-339).",
    ),
}


#: flags that may leave their default only on a test box (STEPS-ROLE, D-877): refused when TB_ENV is VALIDATION or
#: PRODUCTION (unset is PRODUCTION)
TEST_BOX_ONLY = frozenset({"steps.acting_role"})


def test_box(env: dict[str, str] | None = None) -> bool:
    """Whether this box is a test box (TB_ENV DEV or TEST; D-127's rule: unset is PRODUCTION)."""
    from tb_common.config import environment_name

    return environment_name(env if env is not None else dict(os.environ)) in ("DEV", "TEST")


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
        """The stored value, None when the flag has no row (or the store is not installed). Raises on errors
        (``LookupError`` when no store is configured). Reads only: it creates no schema and no table."""
        return self.rows([name]).get(name)

    def rows(self, names: Sequence[str]) -> dict[str, str]:
        """The stored values of ``names`` in one read (a flag with no row is left out; an empty dict when the store is
        not installed). Raises on errors, as :meth:`row` does. The console's layout flags (D-1222, D-1225) are read
        together this way, so reading two costs what reading one did."""
        wanted = list(names)
        for n in wanted:
            declared(n)
        if self._db is not None:
            with self._db.transaction() as tx:
                if tx.fetchval("SELECT to_regclass('flag')") is None:
                    return {}
                got = tx.fetchall("SELECT name, value FROM flag WHERE name = ANY(?)", (wanted,))
            return {str(r[0]): str(r[1]) for r in got if r[1] is not None}
        if not self._url:
            raise LookupError(f"{DB_URL_ENV} is not set: no flag store")
        import psycopg
        from psycopg import sql as pgsql

        # not Database.connect: that creates the schema, and a read must leave the database as it found it
        dsn, prefix = split_url(self._url)
        schema = prefix + SCHEMA
        if not _NAME_RE.match(schema):
            raise DatabaseError(f"bad schema name {schema!r}")
        query = pgsql.SQL("SELECT name, value FROM {} WHERE name = ANY(%s)").format(pgsql.Identifier(schema, "flag"))
        with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as con:
            reg = con.execute("SELECT to_regclass(%s)", (f'"{schema}".flag',)).fetchone()
            if not reg or reg[0] is None:
                return {}
            got = con.execute(query, (wanted,)).fetchall()
        return {str(r[0]): str(r[1]) for r in got if r[1] is not None}

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
            rows: dict[str, dict[str, Any]] = {}
            with db.transaction() as tx:  # reads only: no install on the read path
                if tx.fetchval("SELECT to_regclass('flag')") is not None:
                    found = tx.fetchdicts("SELECT name, value, changed_at, changed_by, reason FROM flag")
                    rows = {r["name"]: r for r in found}
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
            where, params = ("WHERE name = ?", [name]) if name else ("", [])
            with db.transaction() as tx:  # reads only: no install on the read path
                if tx.fetchval("SELECT to_regclass('flag_event')") is None:
                    return []
                return tx.fetchdicts(
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
        reason and an actor are required; the value must be one of the declared ones and differ from the stored.

        The audit event is written inside the transaction, so a failed audit write (a full disk) rolls the change
        back. The other way round, a commit that fails after the audit event was written leaves an event for a change
        that did not happen: a ``flag.set.failed`` event naming it is appended, and the error is raised."""
        v = check_value(name, value)
        if name in TEST_BOX_ONLY and v != DECLARED[name].default and not test_box():
            raise ValueError(f"{name} is for a test box only (TB_ENV DEV or TEST)")
        why = " ".join((reason or "").split())[:MAX_REASON]
        if not why:
            raise ValueError("a flag change needs a reason")
        if not (actor or "").strip():
            raise ValueError("a flag change needs an actor")
        if self.audit is None:
            raise ValueError("a flag change must be audited: give Flags an audit log")
        db, close = self._open()
        written: dict[str, Any] | None = None  # the audit event's detail, once it is written
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
                written = detail
        except BaseException as e:
            if written is not None:  # the audit event is written, the commit failed: say so in the audit trail
                try:
                    self.audit.append("flag.set.failed", actor=actor,
                                      detail={**written, "error": type(e).__name__})  # fmt: skip
                except Exception:
                    log.exception("flag %s: the change was not committed and flag.set.failed was not written", name)
            raise
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
