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

Nothing here holds a chart number or a name.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from tb_common.db import ENV, Database, DatabaseError

SCHEMA = "optout"
ACTIONS = ("opt_out", "lift")
SOURCES = ("paper", "office", "web", "phone", "emr", "other")
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

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


class OptOutRegister:
    """Schema ``optout`` of the trial database. ``url`` defaults to ``TB_DB_URL``."""

    def __init__(self, url: str | None = None) -> None:
        self.db = Database.connect(url if url is not None else os.environ.get(ENV), SCHEMA)
        self.db.migrate(MIGRATIONS)

    def close(self) -> None:
        self.db.close()

    def _add(self, pid: str, action: str, source: str, note: str, by: str, at: str) -> None:
        if not _PID.match(pid):
            raise OptOutError("bad pseudonym")
        if action not in ACTIONS:
            raise OptOutError(f"action must be one of {', '.join(ACTIONS)}")
        self.db.execute(
            "INSERT INTO optout_events (pid, action, source, note, by, at) VALUES (?,?,?,?,?,?)",
            (pid, action, source[:20] or None, note.strip()[:300] or None, by, _norm_at(at)),
        )

    def add(self, pid: str, source: str, note: str, by: str, at: str) -> bool:
        """Record an opt-out; False when the patient is already opted out (nothing is written)."""
        if pid in self.active():
            return False
        self._add(pid, "opt_out", source if source in SOURCES else "other", note, by, at)
        return True

    def lift(self, pid: str, note: str, by: str, at: str) -> bool:
        """The patient takes the opt-out back; False when they were not opted out."""
        if pid not in self.active():
            return False
        self._add(pid, "lift", "", note, by, at)
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

    def current(self) -> list[OptOutEvent]:
        """The opt-out event behind each patient opted out now, newest first."""
        on = self.active()
        last: dict[str, OptOutEvent] = {}
        for e in self.events():
            if e.action == "opt_out" and e.pid in on:
                last[e.pid] = e
        return sorted(last.values(), key=lambda e: e.at, reverse=True)


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
        return frozenset(_active([(str(p), str(a)) for p, a in rows]))
    finally:
        db.close()


__all__ = ["ACTIONS", "SOURCES", "DatabaseError", "OptOutError", "OptOutEvent", "OptOutRegister", "opted_out"]
