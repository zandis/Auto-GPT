"""The break-glass grants' store (D-280, D-430): the tables, the rows and the rules of one grant, and nothing else.

It stands apart from the page (``console.breakglass``) since T-716 (D-484): the orchestrator opens this store to
read a grant and to write its use. A process that loads the store must not load the console's pages, their sign-in
code and their audit events with it (the table of who writes which audit family, T-721, reads what a process
loads).

10K-15 (D-1364): the same schema keeps the support sessions (:class:`SupportSessionStore`), the other exception to
routine access, which closes patient pages instead of opening one."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from tb_common.authz import (
    BREAK_GLASS_MINUTES,
    BREAK_GLASS_NOTE_MIN,
    BREAK_GLASS_REASONS,
    BREAK_GLASS_REVIEW_DAYS,
    SUPPORT_SESSION_MINUTES,
)
from tb_common.visible_text import visible

from console.storedb import open_db

KINDS = ("patient", "job")
NOTE_MAX = 300
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_JOB = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

SCHEMA_V1 = """
CREATE TABLE grants (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username TEXT COLLATE "C" NOT NULL,
  reason TEXT NOT NULL,
  note TEXT NOT NULL,
  kind TEXT NOT NULL,
  ruleset TEXT NOT NULL DEFAULT '',
  pid TEXT NOT NULL DEFAULT '',
  job_id TEXT NOT NULL DEFAULT '',
  opened_at TEXT COLLATE "C" NOT NULL,
  ends_at TEXT COLLATE "C" NOT NULL,
  ended_at TEXT COLLATE "C",
  uses INTEGER NOT NULL DEFAULT 0,
  reviewed_by TEXT,
  reviewed_at TEXT,
  review_note TEXT
);
CREATE INDEX grants_user ON grants (username, ends_at)
"""
# T-309 (D-430): each use of a grant, so the steward's review list shows every one (page, chart number, time)
SCHEMA_V2 = """
CREATE TABLE uses (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  grant_id BIGINT NOT NULL,
  at TEXT COLLATE "C" NOT NULL,
  what TEXT NOT NULL,
  ruleset TEXT NOT NULL DEFAULT '',
  pid TEXT NOT NULL DEFAULT '',
  job_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX uses_grant ON uses (grant_id, id)
"""
# 10K-15 (D-1364, owner decision 99): the support sessions the hospital's administrator starts; the console reads the
# open one at every request (``console.support_session``). No patient data: who, when, the ticket, how it ended.
# ``end_audited``: the end's audit event is written (an automatic end whose event failed is written again later).
SCHEMA_V3 = """
CREATE TABLE support_sessions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  started_by TEXT COLLATE "C" NOT NULL,
  started_at TEXT COLLATE "C" NOT NULL,
  ticket TEXT NOT NULL DEFAULT '',
  ended_at TEXT COLLATE "C",
  ended_by TEXT,
  how TEXT,
  end_audited BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX support_sessions_open ON support_sessions (ended_at, id)
"""
MIGRATIONS = (SCHEMA_V1, SCHEMA_V2, SCHEMA_V3)
WHATS = ("patient_page", "reveal", "job_page", "case_sheet", "twin")  # twin: T-204 (D-440), the twin API
_COLS = ("id, username, reason, note, kind, ruleset, pid, job_id, opened_at, ends_at, ended_at, uses, reviewed_by, "
         "reviewed_at, review_note")  # fmt: skip


class BreakGlassError(ValueError):
    """A grant that cannot be opened, ended or reviewed: the key of the message to show."""


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Grant:
    id: int
    username: str
    reason: str
    note: str
    kind: str
    ruleset: str
    pid: str
    job_id: str
    opened_at: str
    ends_at: str
    ended_at: str | None
    uses: int
    reviewed_by: str | None
    reviewed_at: str | None
    review_note: str | None

    def active(self, now: datetime) -> bool:
        """Open now: not ended by hand and before its 60-minute end."""
        return self.ended_at is None and _iso(now) < self.ends_at

    def closed_at(self) -> str:
        return self.ended_at or self.ends_at

    def overdue(self, now: datetime) -> bool:
        """Not reviewed within :data:`BREAK_GLASS_REVIEW_DAYS` days of its end."""
        due = datetime.fromisoformat(self.closed_at()) + timedelta(days=BREAK_GLASS_REVIEW_DAYS)
        return self.reviewed_at is None and now >= due

    def covers(self, *, ruleset: str = "", pid: str = "", job_id: str = "") -> bool:
        if self.kind == "patient":
            return bool(pid) and self.pid == pid and self.ruleset == (ruleset or self.ruleset)
        return bool(job_id) and self.job_id == job_id


@dataclass(frozen=True)
class Use:
    grant_id: int
    at: str
    what: str
    ruleset: str
    pid: str
    job_id: str


def _grant(r: Any) -> Grant:
    return Grant(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], int(r[11]), r[12], r[13],
                 r[14])  # fmt: skip


class BreakGlassStore:
    """Schema ``breakglass`` of the trial database (D-126). ``url`` defaults to ``TB_DB_URL``."""

    def __init__(self, url: str | None = None) -> None:
        self.db = open_db(url, "breakglass", MIGRATIONS)

    def close(self) -> None:
        self.db.close()

    def open(self, username: str, *, reason: str, note: str, kind: str, ruleset: str = "", pid: str = "",
             job_id: str = "", now: datetime) -> tuple[Grant, list[Grant]]:  # fmt: skip
        """Open one grant for ``username``; returns it and the grants it ended (one at a time)."""
        note = visible(note)  # D-1232: as before, and a note of invisible characters only has no length
        if reason not in BREAK_GLASS_REASONS:
            raise BreakGlassError("bg.err.reason")
        if len(note) < BREAK_GLASS_NOTE_MIN:
            raise BreakGlassError("bg.err.note")
        if len(note) > NOTE_MAX:
            raise BreakGlassError("bg.err.long")
        if kind == "patient":
            ruleset = ruleset.strip().upper()
            pid, job_id = pid.strip(), ""
            if not _RS.match(ruleset) or not _PID.match(pid):
                raise BreakGlassError("bg.err.target")
        elif kind == "job":
            job_id, ruleset, pid = job_id.strip(), "", ""
            if not _JOB.match(job_id):
                raise BreakGlassError("bg.err.target")
        else:
            raise BreakGlassError("bg.err.target")
        ended = self.active(username, now)
        with self.db.transaction() as tx:
            for g in ended:
                tx.execute("UPDATE grants SET ended_at = ? WHERE id = ?", (_iso(now), g.id))
            gid = int(
                tx.fetchval(
                    "INSERT INTO grants (username, reason, note, kind, ruleset, pid, job_id, opened_at, ends_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (username, reason, note, kind, ruleset, pid, job_id, _iso(now),
                     _iso(now + timedelta(minutes=BREAK_GLASS_MINUTES))),
                )
            )  # fmt: skip
        got = self.get(gid)
        assert got is not None
        return got, ended

    def get(self, gid: int) -> Grant | None:
        row = self.db.fetchone(f"SELECT {_COLS} FROM grants WHERE id = ?", (gid,))
        return _grant(row) if row else None

    def grants(self, limit: int = 200) -> list[Grant]:
        """Newest first."""
        return [_grant(r) for r in self.db.fetchall(f"SELECT {_COLS} FROM grants ORDER BY id DESC LIMIT ?", (limit,))]

    def of(self, username: str, limit: int = 50) -> list[Grant]:
        rows = self.db.fetchall(f"SELECT {_COLS} FROM grants WHERE username = ? ORDER BY id DESC LIMIT ?",
                                (username, limit))  # fmt: skip
        return [_grant(r) for r in rows]

    def active(self, username: str, now: datetime) -> list[Grant]:
        rows = self.db.fetchall(f"SELECT {_COLS} FROM grants WHERE username = ? AND ended_at IS NULL AND ends_at > ?",
                                (username, _iso(now)))  # fmt: skip
        return [_grant(r) for r in rows]

    def covering(self, username: str, now: datetime, *, ruleset: str = "", pid: str = "",
                 job_id: str = "") -> Grant | None:  # fmt: skip
        """The person's grant open now that covers this patient or this job, else None."""
        return next((g for g in self.active(username, now) if g.covers(ruleset=ruleset, pid=pid, job_id=job_id)), None)

    def used(self, gid: int, *, what: str, now: datetime, ruleset: str = "", pid: str = "", job_id: str = "") -> None:
        """One use: the grant's count and a row of ``uses`` (what was opened, when)."""
        with self.db.transaction() as tx:
            tx.execute("UPDATE grants SET uses = uses + 1 WHERE id = ?", (gid,))
            tx.execute("INSERT INTO uses (grant_id, at, what, ruleset, pid, job_id) VALUES (?, ?, ?, ?, ?, ?)",
                       (gid, _iso(now), what, ruleset, pid, job_id))  # fmt: skip

    def uses_of(self, gids: list[int]) -> dict[int, list[Use]]:
        """Every use of these grants, oldest first, by grant."""
        out: dict[int, list[Use]] = {g: [] for g in gids}
        if not gids:
            return out
        marks = ", ".join("?" for _ in gids)
        rows = self.db.fetchall(f"SELECT grant_id, at, what, ruleset, pid, job_id FROM uses WHERE grant_id IN "
                                f"({marks}) ORDER BY id", tuple(gids))  # fmt: skip  # nosec B608 - placeholders only
        for r in rows:
            out[int(r[0])].append(Use(int(r[0]), r[1], r[2], r[3], r[4], r[5]))
        return out

    def end(self, gid: int, username: str, now: datetime) -> Grant:
        g = self.get(gid)
        if g is None or g.username != username:
            raise BreakGlassError("bg.err.none")
        if g.active(now):
            self.db.execute("UPDATE grants SET ended_at = ? WHERE id = ?", (_iso(now), gid))
        got = self.get(gid)
        assert got is not None
        return got

    def review(self, gid: int, by: str, note: str, now: datetime) -> Grant:
        g = self.get(gid)
        if g is None:
            raise BreakGlassError("bg.err.none")
        if g.username == by:
            raise BreakGlassError("bg.err.self")
        if g.active(now):
            raise BreakGlassError("bg.err.open")
        if g.reviewed_at is not None:
            raise BreakGlassError("bg.err.reviewed")
        self.db.execute("UPDATE grants SET reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
                        (by, _iso(now), " ".join((note or "").split())[:NOTE_MAX] or None, gid))  # fmt: skip
        got = self.get(gid)
        assert got is not None
        return got


# ---------------------------------------------------------------------------------------------- 10K-15 (D-1364)
# the shape of a ticket number: an optional short prefix of letters, then digits in up to four groups ("TB-2026-0117",
# "SUP-0042", "#4711"). A pattern cannot prove that no name is typed; it keeps the field to what a number looks like
_TICKET = re.compile(r"^(?:#|[A-Za-z]{1,6}[-#]?)?[0-9]{1,12}(?:[-/.][0-9]{1,12}){0,3}$")
HOWS = ("hand", "auto")  # ended by the administrator, or by itself after SUPPORT_SESSION_MINUTES
_SCOLS = "id, started_by, started_at, ticket, ended_at, ended_by, how, end_audited"


class SupportError(ValueError):
    """A support session that cannot be started or ended: the key of the message to show."""


@dataclass(frozen=True)
class SupportSession:
    id: int
    started_by: str
    started_at: str
    ticket: str
    ended_at: str | None
    ended_by: str | None
    how: str | None
    end_audited: bool = False

    @property
    def start(self) -> datetime | None:
        """The stored start as a time, None when it cannot be read (a damaged row)."""
        try:
            t = datetime.fromisoformat(self.started_at)
        except (TypeError, ValueError):
            return None
        return t if t.tzinfo is not None else t.replace(tzinfo=UTC)

    @property
    def ends_at(self) -> str:
        """The latest end: the stored start plus ``SUPPORT_SESSION_MINUTES`` (no stored end that could drift); ""
        when the start cannot be read."""
        st = self.start
        return _iso(st + timedelta(minutes=SUPPORT_SESSION_MINUTES)) if st is not None else ""

    def active(self, now: datetime) -> bool:
        """Not ended and inside its 2 hours. A start that cannot be read keeps it on (closed on doubt) until the
        administrator ends it by hand (:meth:`SupportSessionStore.end` reads no time)."""
        if self.ended_at is not None:
            return False
        st = self.start
        return st is None or now < st + timedelta(minutes=SUPPORT_SESSION_MINUTES)


def _session(r: Any) -> SupportSession:
    return SupportSession(int(r[0]), r[1], r[2], r[3] or "", r[4], r[5], r[6], bool(r[7]))


class SupportSessionStore:
    """The ``support_sessions`` table of schema ``breakglass``. At most one session is open; the console asks
    :meth:`current` at every request, which also ends a session whose 2 hours are over (once: the row says so).

    The audit trail (D-1364, the review's S1): a start is committed only after its audit event is written (the event
    is written before the insert commits, so a failed event rolls the row back; the audit trail is its own store, so
    a commit that fails after the event leaves a start event with no session), and so is an end by hand; an
    automatic end is a row change first, and its event is written by :meth:`audit_end`, again at every request until
    it is written (``end_audited``)."""

    def __init__(self, url: str | None = None) -> None:
        self.db = open_db(url, "breakglass", MIGRATIONS)

    def close(self) -> None:
        self.db.close()

    def current(self, now: datetime, on_moved: Callable[[SupportSession, SupportSession], None] | None = None
                ) -> tuple[SupportSession | None, list[SupportSession]]:  # fmt: skip
        """The open session (None when there is none) and the ended sessions whose end event is not written yet.
        A session whose 2 hours are over is ended here at its latest end (``ends_at``), ``how`` "auto". A start
        later than ``now`` (the clock was moved back) is set to ``now``: the session then lasts at most 2 hours from
        this request, never 2 hours from a time the clock has not reached. ``on_moved(before, after)`` (its audit
        event) runs inside that update's transaction: when it fails the start is not moved and the error goes to the
        caller (the console then answers as on doubt, closed), so a start never moves without its event."""
        rows = self.db.fetchall(f"SELECT {_SCOLS} FROM support_sessions WHERE ended_at IS NULL OR NOT end_audited "
                                "ORDER BY id")  # fmt: skip
        live: SupportSession | None = None
        unaudited: list[SupportSession] = []
        for s in (_session(r) for r in rows):
            if s.ended_at is not None:
                unaudited.append(s)
                continue
            st = s.start
            if st is not None and st > now:
                with self.db.transaction() as tx:  # a second process moving the same start at once: one moves it
                    row = tx.fetchone(f"SELECT {_SCOLS} FROM support_sessions WHERE id = ? AND ended_at IS NULL "
                                      "AND started_at = ? FOR UPDATE SKIP LOCKED", (s.id, s.started_at))  # fmt: skip
                    if row is not None:
                        tx.execute("UPDATE support_sessions SET started_at = ? WHERE id = ?", (_iso(now), s.id))
                        after = _session(tx.fetchone(f"SELECT {_SCOLS} FROM support_sessions WHERE id = ?", (s.id,)))
                        if on_moved is not None:
                            on_moved(_session(row), after)
                s = self.get(s.id) or s
            if s.active(now):
                live = s
                continue
            if self.db.execute("UPDATE support_sessions SET ended_at = ?, ended_by = '', how = 'auto' "
                               "WHERE id = ? AND ended_at IS NULL", (s.ends_at, s.id)):  # fmt: skip
                got = self.get(s.id)
                if got is not None and not got.end_audited:
                    unaudited.append(got)
        return live, unaudited

    def audit_end(self, sid: int, write: Callable[[SupportSession], None]) -> bool:
        """Write the end event of ended session ``sid`` once: ``write`` runs inside the transaction that marks the
        row ``end_audited``, so a failing ``write`` leaves it to the next request, and two requests never both write
        it. True when this call wrote it."""
        with self.db.transaction() as tx:
            row = tx.fetchone(f"SELECT {_SCOLS} FROM support_sessions WHERE id = ? AND ended_at IS NOT NULL "
                              "AND NOT end_audited FOR UPDATE SKIP LOCKED", (sid,))  # fmt: skip
            if row is None:
                return False
            write(_session(row))
            tx.execute("UPDATE support_sessions SET end_audited = true WHERE id = ?", (sid,))
        return True

    def open_rows(self) -> list[SupportSession]:
        """The sessions not ended, read without their times (the page offers each one's end, even a damaged row)."""
        rows = self.db.fetchall(f"SELECT {_SCOLS} FROM support_sessions WHERE ended_at IS NULL ORDER BY id DESC")
        return [_session(r) for r in rows]

    def get(self, sid: int) -> SupportSession | None:
        row = self.db.fetchone(f"SELECT {_SCOLS} FROM support_sessions WHERE id = ?", (sid,))
        return _session(row) if row else None

    def recent(self) -> list[SupportSession]:
        """Every session, newest first (a few a month at most: one per supervised session)."""
        rows = self.db.fetchall(f"SELECT {_SCOLS} FROM support_sessions ORDER BY id DESC")
        return [_session(r) for r in rows]

    def start(self, username: str, ticket: str, now: datetime,
              before_commit: Callable[[SupportSession], None]) -> SupportSession:  # fmt: skip
        """Start a session for ``username`` (the administrator); refused while one is open. ``before_commit`` (the
        start's audit event) runs inside the insert's transaction: when it fails nothing is stored, so a session is
        never on without its start event."""
        ticket = (ticket or "").strip()
        if ticket and not _TICKET.match(ticket):
            raise SupportError("support.err.ticket")
        with self.db.transaction() as tx:
            tx.execute("LOCK TABLE support_sessions IN EXCLUSIVE MODE")  # two starts at once: one wins
            for r in tx.fetchall(f"SELECT {_SCOLS} FROM support_sessions WHERE ended_at IS NULL"):
                if _session(r).active(now):
                    raise SupportError("support.err.on")
            sid = int(tx.fetchval("INSERT INTO support_sessions (started_by, started_at, ticket) VALUES (?, ?, ?) "
                                  "RETURNING id", (username, _iso(now), ticket)))  # fmt: skip
            got = _session(tx.fetchone(f"SELECT {_SCOLS} FROM support_sessions WHERE id = ?", (sid,)))
            before_commit(got)
        return got

    def end(self, sid: int, by: str, now: datetime,
            before_commit: Callable[[SupportSession], None]) -> SupportSession:  # fmt: skip
        """End the open session ``sid`` by hand; refused when it is already ended. Reads no stored time, so a row
        whose start cannot be read is ended too. ``before_commit`` (the end's audit event) runs inside the update's
        transaction: when it fails the session stays on (closed) and the end can be tried again."""
        with self.db.transaction() as tx:
            done = tx.execute("UPDATE support_sessions SET ended_at = ?, ended_by = ?, how = 'hand', "
                              "end_audited = true WHERE id = ? AND ended_at IS NULL", (_iso(now), by, sid))  # fmt: skip
            if not done:
                raise SupportError("support.err.none")
            got = _session(tx.fetchone(f"SELECT {_SCOLS} FROM support_sessions WHERE id = ?", (sid,)))
            before_commit(got)
        return got
