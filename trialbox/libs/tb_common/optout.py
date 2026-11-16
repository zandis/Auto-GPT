"""The research-use opt-out register (owner decision 2026-11-09, D-147), schema ``optout`` of the trial database.

The research office or the data steward records each patient who opted out, by pseudonym (a chart number typed at
the door is turned into the pseudonym by the box and never stored). From then on the patient is removed from
screening runs, from every candidate list and page, and from later exports; the console and the orchestrator read the
same register. The register is an event log: an opt-out and, when the patient takes it back, a lift. Who is opted out
*at a time* is the last event at or before that time, so a re-run of an old job (D-82) uses the register as it stood
when the job was received and stays byte-identical.

    reg = OptOutRegister()                                  # TB_DB_URL, migrated
    reg.add(pid, "paper form", "", "console:office1", now)
    reg.active()                                            # {pid, ...} now
    opted_out(as_of=job.received_at.isoformat())            # read-only, for the orchestrator

The hospital's own registry reaches the box as the lake's ``consent`` table (FHIR Consent, scope research). The
opt-out worker (``services/datacore/optout_worker.py``, D-441) copies a registry refusal into this register (source
``emr``, by :data:`REGISTRY_ACTOR`), so every path that reads the register also honours the hospital's refusal;
:func:`registry_state` is the one reading of that table (the same rule as COHORT's ``n_contactable``).

Nothing here holds a chart number or a name.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from tb_common.db import ENV, Database, DatabaseError

SCHEMA = "optout"
ACTIONS = ("opt_out", "lift")
SOURCES = ("paper", "office", "web", "phone", "emr", "other")
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
#: who records the opt-outs copied from the hospital's registry (D-441); only these are lifted by the registry again
REGISTRY_ACTOR = "worker:registry"
#: the lake's consent rows on or before a day, oldest first per patient (an undated row counts as the oldest); a row
#: entered in error is no statement (the rule of COHORT's ``n_contactable``, PR #257). Dates are whole days, so two
#: statements of one day are ordered fail-closed: an active consent first, a refusal last, so the refusal wins and a
#: same-day withdrawal beats a consent (review MED-2). ``undated`` (review of T-708): a refusal whose date is unknown
#: cannot be shown to be older than a consent, so :func:`registry_rule` keeps the patient out whatever came later
REGISTRY_SQL = (
    "SELECT pid, status, contact_ok, date IS NULL AS undated FROM consent "
    "WHERE coalesce(status, '') <> 'entered-in-error' "
    "AND (date IS NULL OR date <= CAST($1 AS DATE)) "
    "ORDER BY pid, date NULLS FIRST, CASE status WHEN 'active' THEN 0 WHEN 'rejected' THEN 2 ELSE 1 END, "
    "coalesce(contact_ok, true) DESC, coalesce(contact_ok, false) DESC"
)  # the last key (D-477): of two same-day statements one that does not say "contact allowed" sorts after one that does

SCHEMA_V1 = """
CREATE TABLE optout_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  pid TEXT NOT NULL,
  action TEXT NOT NULL,
  source TEXT,
  note TEXT,
  by TEXT NOT NULL,
  at TEXT COLLATE "C" NOT NULL
);
CREATE INDEX optout_events_pid ON optout_events (pid, at)
"""
MIGRATIONS: tuple[str, ...] = (SCHEMA_V1,)


class OptOutError(ValueError):
    pass


@dataclass(frozen=True)
class OptOutEvent:
    pid: str
    action: str
    source: str
    note: str
    by: str
    at: str


def _norm_at(at: str) -> str:
    """ISO-8601 in UTC with an offset, so text order is time order (``at`` columns sort byte by byte)."""
    dt = datetime.fromisoformat(at)
    if dt.tzinfo is None:
        raise OptOutError("times carry an offset")
    return dt.astimezone(UTC).isoformat()


def _active(events: list[tuple[str, str]]) -> set[str]:
    """``events``: (pid, action) in time order -> the pids whose last event is an opt-out."""
    last: dict[str, str] = {}
    for pid, action in events:
        last[pid] = action
    return {p for p, a in last.items() if a == "opt_out"}


def with_survivors(db: Database, pids: set[str]) -> set[str]:
    """``pids`` and the surviving pid of every one merged into another chart (``pidmap.pid_alias``, T-659b): an
    opt-out typed under a chart number that was later merged, or before the merge, hides the surviving patient too
    (review MED-4). Read only when the store exists and this service may read it (the adapter's map); every merge
    counts, whatever ``as_of`` (fail closed: the same person)."""
    if not pids:
        return pids
    schema = db.schema[: -len(SCHEMA)] + "pidmap"
    # D-683: asked for the service itself (session_user), not for the role this connection works as: the register's
    # connection is its group role (D-378), which may never use the pid map, so on a box with roles a merge was
    # never followed. The catalog answers every role; the map is then read on its own connection
    ok = db.fetchval(
        "SELECT has_schema_privilege(session_user, n.oid, 'USAGE') AND EXISTS (SELECT 1 FROM pg_catalog.pg_class c "
        "WHERE c.relnamespace = n.oid AND c.relname = 'pid_alias' AND c.relkind IN ('r', 'p')) "
        "FROM pg_catalog.pg_namespace n WHERE n.nspname = ?",
        (schema,),
    )
    if not ok:
        return pids
    pm = Database.connect(db.url, "pidmap")  # the schema exists (checked above), so nothing is created
    try:
        raw = {str(a): str(b) for a, b in pm.fetchall("SELECT old_pid, pid FROM pid_alias")}
    finally:
        pm.close()
    out = set(pids)
    for p in pids:
        seen = {p}
        while p in raw and raw[p] not in seen:  # every pid on the way: each is the same patient
            p = raw[p]
            seen.add(p)
        out |= seen
    return out


class OptOutRegister:
    """Schema ``optout`` of the trial database. ``url`` defaults to ``TB_DB_URL``."""

    def __init__(self, url: str | None = None) -> None:
        self.db = Database.connect(url if url is not None else os.environ.get(ENV), SCHEMA)
        self.db.migrate(MIGRATIONS)

    def close(self) -> None:
        self.db.close()

    def _add(self, pid: str, action: str, source: str, note: str, by: str, at: str,
             before_commit: Callable[[], None] | None = None) -> None:  # fmt: skip
        if not _PID.match(pid):
            raise OptOutError("bad pseudonym")
        if action not in ACTIONS:
            raise OptOutError(f"action must be one of {', '.join(ACTIONS)}")
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO optout_events (pid, action, source, note, by, at) VALUES (?,?,?,?,?,?)",
                (pid, action, source[:20] or None, note.strip()[:300] or None, by, _norm_at(at)),
            )
            if before_commit is not None:  # D-273 (CR-055): the audit append; if it fails, nothing is kept
                before_commit()

    def add(self, pid: str, source: str, note: str, by: str, at: str,
            before_commit: Callable[[], None] | None = None) -> bool:  # fmt: skip
        """Record an opt-out; True when the patient was not opted out before. A person's opt-out is written as its
        own event even when the patient is already opted out (by the registry, say), so the register knows the
        person asked and the feed never lifts it (D-441, review HIGH-2); only the registry's own repeat writes
        nothing. ``before_commit`` (the caller's audit append) runs inside the write's transaction, so a failed append
        keeps nothing."""
        was = pid in self.active()
        if was and by == REGISTRY_ACTOR:
            return False
        self._add(pid, "opt_out", source if source in SOURCES else "other", note, by, at, before_commit)
        return not was

    def lift(self, pid: str, note: str, by: str, at: str, before_commit: Callable[[], None] | None = None) -> bool:
        """The patient takes the opt-out back; False when they were not opted out. ``before_commit`` as in add."""
        if pid not in self.active():
            return False
        self._add(pid, "lift", "", note, by, at, before_commit)
        return True

    def events(self, pid: str | None = None) -> list[OptOutEvent]:
        q = "SELECT pid, action, source, note, by, at FROM optout_events"
        rows = self.db.fetchall(q + (" WHERE pid = ?" if pid else "") + " ORDER BY at, id", (pid,) if pid else ())
        return [OptOutEvent(str(r[0]), str(r[1]), str(r[2] or ""), str(r[3] or ""), str(r[4]), str(r[5])) for r in rows]

    def active(self, as_of: str | None = None) -> set[str]:
        if as_of is None:
            rows = self.db.fetchall("SELECT pid, action FROM optout_events ORDER BY at, id")
        else:
            rows = self.db.fetchall(
                "SELECT pid, action FROM optout_events WHERE at <= ? ORDER BY at, id", (_norm_at(as_of),)
            )
        return _active([(str(p), str(a)) for p, a in rows])

    def effective(self, as_of: str | None = None) -> set[str]:
        """Who is kept out: :meth:`active` and the surviving pid of each merged one (:func:`with_survivors`)."""
        return with_survivors(self.db, self.active(as_of))

    def current(self) -> list[OptOutEvent]:
        """The opt-out event behind each patient opted out now, newest first."""
        on = self.active()
        last: dict[str, OptOutEvent] = {}
        for e in self.events():
            if e.action == "opt_out" and e.pid in on:
                last[e.pid] = e
        return sorted(last.values(), key=lambda e: e.at, reverse=True)


@dataclass(frozen=True)
class RegistryState:
    """What the hospital's registry says now, per patient, by the latest statement: ``refused`` (FHIR Consent
    ``rejected``: no research use), ``no_contact`` (a latest statement that denies contact) and ``consenting`` (a
    latest ``active`` statement: the only one that may lift the registry's own opt-out). ``contactable`` (D-477):
    a latest ``active`` statement that allows contact, COHORT's ``n_contactable``."""

    refused: frozenset[str]
    no_contact: frozenset[str]
    consenting: frozenset[str] = frozenset()
    contactable: frozenset[str] = frozenset()


def registry_rule(rows: Sequence[tuple[Any, ...]]) -> RegistryState:
    """``rows``: (pid, status, contact_ok[, undated]) oldest first. The patient's latest statement decides: a later
    withdrawal ends an earlier active consent, and a later active consent ends an earlier refusal.

    **Except an undated refusal** (``undated`` true on a ``rejected`` row): its date is unknown, so no consent can
    be shown to be later. The patient is refused, and is neither consenting nor contactable, whatever else the
    registry holds (D-477: the owner's ruling of 2026-11-12, raised by the review of T-708)."""
    last: dict[str, tuple[str, bool | None]] = {}
    undated_refusal: set[str] = set()
    for pid, status, contact, *rest in rows:
        last[pid] = (status, contact)
        if status == "rejected" and rest and rest[0]:
            undated_refusal.add(pid)
    return RegistryState(
        frozenset(p for p, (st, _) in last.items() if st == "rejected" or p in undated_refusal),
        frozenset(p for p, (_, ok) in last.items() if ok is False),
        frozenset(p for p, (st, _) in last.items() if st == "active" and p not in undated_refusal),
        frozenset(p for p, (st, ok) in last.items() if st == "active" and ok is True and p not in undated_refusal),
    )


#: what a run says when it stops for a snapshot without a consent table (D-654); no name, date or id in it
NO_REGISTRY_TABLE = (
    "The lake snapshot has no consent table. A snapshot built by TrialBox always has one, so this snapshot was made "
    "by hand or by other software. The run stops: without the table no opt-out could be applied."
)
#: the boxes on which a snapshot without a consent table still reads as "no registry" (``TB_ENV``): tests and tools
#: build small lakes there. Every other name refuses: PRODUCTION, VALIDATION, unset (which is PRODUCTION) and any
#: name this code does not know.
NO_REGISTRY_ALLOWED = ("DEV", "TEST")


class NoRegistryTable(RuntimeError):
    """A PRODUCTION box was asked to read the opt-out registry of a snapshot that has no consent table (D-654)."""

    def __init__(self) -> None:
        super().__init__(NO_REGISTRY_TABLE)


def registry_state(lake: Any, snapshot: str | None, day: str) -> RegistryState | None:
    """The lake's ``consent`` table read by :func:`registry_rule` as of ``day`` (ISO date). None: the lake has no
    consent table (the site's registry was never ingested), **on a DEV or TEST box only**. Any other failure
    raises (D-127: fail closed).

    Whether the lake has no such table is asked of the lake (:mod:`tb_common.lakeprobe`, D-651): after the query
    failed, how many tables or views named ``consent`` the snapshot has, and only one row with the integer 0 is
    "none". It used to be read from the failure's text ("consent" with "does not exist"): another failure whose
    text held those words then read as "no registry", and every caller takes that for "no opt-out to apply".

    D-654 (the owner's decision): on a PRODUCTION box (``TB_ENV`` unset, or any name but DEV and TEST) "none" is
    not an answer either. The lake's own store builds the table on every rebuild, empty when there is no Consent
    feed, so a snapshot without it was made by hand or by other software: :class:`NoRegistryTable`."""
    import os

    from tb_common import lakeprobe
    from tb_common.config import environment_name

    rows = lakeprobe.rows_or_no_table(lake, REGISTRY_SQL, [day], snapshot, "consent")
    if rows is None:
        if environment_name(os.environ) not in NO_REGISTRY_ALLOWED:
            raise NoRegistryTable
        return None
    return registry_rule(
        [(str(r["pid"]), str(r["status"] or ""), r["contact_ok"], bool(r.get("undated"))) for r in rows if r["pid"]]
    )


def sync_registry(reg: OptOutRegister, state: RegistryState, at: str) -> tuple[int, int]:
    """Copy the registry's refusals into the register (source ``emr``, by :data:`REGISTRY_ACTOR`) and lift one only
    when the registry's latest statement for the patient is ``active`` (a missing row, a withdrawn or proposed one
    lifts nothing: review HIGH-1, MED-1), and only when every opt-out since the patient's last lift came from the
    registry: an opt-out a person typed is never lifted by the feed (review HIGH-2). Returns (added, lifted)."""
    on = reg.active()
    since: dict[str, set[str]] = {}  # pid -> who opted the patient out since the last lift
    for e in reg.events():
        if e.action == "lift":
            since.pop(e.pid, None)
        else:
            since.setdefault(e.pid, set()).add(e.by)
    added = lifted = 0
    for pid in sorted(state.refused - on):
        if _PID.match(pid):
            added += reg.add(pid, "emr", "the hospital registry: research use refused", REGISTRY_ACTOR, at)
    for pid in sorted((on - state.refused) & state.consenting):
        if since.get(pid) == {REGISTRY_ACTOR}:
            lifted += reg.lift(pid, "the hospital registry records an active consent", REGISTRY_ACTOR, at)
    return added, lifted


def opted_out(url: str | None = None, as_of: str | None = None) -> frozenset[str]:
    """Read-only: the pseudonyms opted out at ``as_of`` (now when None). No trial database configured -> empty (there
    is no register without one). A database that does not answer raises: skipping the register would list patients
    who said no (D-127 fails closed in the same way for the feed's consent table)."""
    url = url if url is not None else os.environ.get(ENV)
    if not url:
        return frozenset()
    db = Database.connect(url, SCHEMA)
    try:
        if db.fetchval("SELECT to_regclass(?)", (f'"{db.schema}".optout_events',)) is None:
            return frozenset()
        if as_of is None:
            rows = db.fetchall("SELECT pid, action FROM optout_events ORDER BY at, id")
        else:
            rows = db.fetchall(
                "SELECT pid, action FROM optout_events WHERE at <= ? ORDER BY at, id", (_norm_at(as_of),)
            )
        return frozenset(with_survivors(db, _active([(str(p), str(a)) for p, a in rows])))
    finally:
        db.close()


__all__ = [
    "ACTIONS",
    "REGISTRY_ACTOR",
    "SOURCES",
    "DatabaseError",
    "OptOutError",
    "OptOutEvent",
    "OptOutRegister",
    "RegistryState",
    "opted_out",
    "registry_rule",
    "registry_state",
    "sync_registry",
]


def register_now() -> frozenset[str]:
    """The register as it stands now (with merged charts), for code that runs outside a job and outside the
    orchestrator (T-708, D-477): a timer, an export of another service. A job reads its decision context; the
    orchestrator's own routes call ``orchestrator.decision_context.register_now``, which is this function. Raises
    when the register does not answer (D-127: fail closed)."""
    return opted_out()
