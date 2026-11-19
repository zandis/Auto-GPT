"""The break-glass grants' store (D-280, D-430): the tables, the rows and the rules of one grant, and nothing else.

It stands apart from the page (``console.breakglass``) since T-716 (D-484): the orchestrator opens this store to
read a grant and to write its use. A process that loads the store must not load the console's pages, their sign-in
code and their audit events with it (the table of who writes which audit family, T-721, reads what a process
loads).

10K-15 (D-1364): the same schema keeps the support sessions (:class:`SupportSessionStore`), the other exception to
routine access, which closes patient pages instead of opening one."""

from __future__ import annotations

import re
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
SCHEMA_V3 = """
CREATE TABLE support_sessions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  started_by TEXT COLLATE "C" NOT NULL,
  started_at TEXT COLLATE "C" NOT NULL,
  ticket TEXT NOT NULL DEFAULT '',
  ended_at TEXT COLLATE "C",
  ended_by TEXT,
  how TEXT
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
        note = " ".join((note or "").split())
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
_TICKET = re.compile(r"^[A-Za-z0-9#._/-]{0,40}$")  # a ticket number, never a name or a sentence
HOWS = ("hand", "auto")  # ended by the administrator, or by itself after SUPPORT_SESSION_MINUTES
_SCOLS = "id, started_by, started_at, ticket, ended_at, ended_by, how"


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

    @property
    def ends_at(self) -> str:
        """The latest end: the stored start plus ``SUPPORT_SESSION_MINUTES`` (no stored end that could drift)."""
        return _iso(datetime.fromisoformat(self.started_at) + timedelta(minutes=SUPPORT_SESSION_MINUTES))

    def active(self, now: datetime) -> bool:
        return self.ended_at is None and now < datetime.fromisoformat(self.ends_at)


def _session(r: Any) -> SupportSession:
    return SupportSession(int(r[0]), r[1], r[2], r[3] or "", r[4], r[5], r[6])


class SupportSessionStore:
    """The ``support_sessions`` table of schema ``breakglass``. At most one session is open; the console asks
    :meth:`current` at every request, which also ends a session whose 2 hours are over (once: the row says so)."""

    def __init__(self, url: str | None = None) -> None:
        self.db = open_db(url, "breakglass", MIGRATIONS)

    def close(self) -> None:
        self.db.close()

    def current(self, now: datetime) -> tuple[SupportSession | None, list[SupportSession]]:
        """The open session (None when there is none) and the sessions this call ended because their time was over:
        each is ended at its latest end (``ends_at``), with ``how`` "auto", by exactly one caller."""
        rows = self.db.fetchall(f"SELECT {_SCOLS} FROM support_sessions WHERE ended_at IS NULL ORDER BY id")
        lapsed: list[SupportSession] = []
        live: SupportSession | None = None
        for s in (_session(r) for r in rows):
            if s.active(now):
                live = s
                continue
            if self.db.execute("UPDATE support_sessions SET ended_at = ?, ended_by = '', how = 'auto' "
                               "WHERE id = ? AND ended_at IS NULL", (s.ends_at, s.id)):  # fmt: skip
                lapsed.append(self.get(s.id) or s)
        return live, lapsed

    def get(self, sid: int) -> SupportSession | None:
        row = self.db.fetchone(f"SELECT {_SCOLS} FROM support_sessions WHERE id = ?", (sid,))
        return _session(row) if row else None

    def recent(self) -> list[SupportSession]:
        """Every session, newest first (a few a month at most: one per supervised session)."""
        rows = self.db.fetchall(f"SELECT {_SCOLS} FROM support_sessions ORDER BY id DESC")
        return [_session(r) for r in rows]

    def start(self, username: str, ticket: str, now: datetime) -> SupportSession:
        """Start a session for ``username`` (the administrator); refused while one is open."""
        ticket = (ticket or "").strip()
        if not _TICKET.match(ticket):
            raise SupportError("support.err.ticket")
        with self.db.transaction() as tx:
            tx.execute("LOCK TABLE support_sessions IN EXCLUSIVE MODE")  # two starts at once: one wins
            for r in tx.fetchall(f"SELECT {_SCOLS} FROM support_sessions WHERE ended_at IS NULL"):
                if _session(r).active(now):
                    raise SupportError("support.err.on")
            sid = int(tx.fetchval("INSERT INTO support_sessions (started_by, started_at, ticket) VALUES (?, ?, ?) "
                                  "RETURNING id", (username, _iso(now), ticket)))  # fmt: skip
        got = self.get(sid)
        assert got is not None
        return got

    def end(self, sid: int, by: str, now: datetime) -> SupportSession:
        """End the open session ``sid`` by hand; refused when it is not open (ended, or its time is over)."""
        s = self.get(sid)
        if s is None or not s.active(now):
            raise SupportError("support.err.none")
        if not self.db.execute("UPDATE support_sessions SET ended_at = ?, ended_by = ?, how = 'hand' "
                               "WHERE id = ? AND ended_at IS NULL", (_iso(now), by, sid)):  # fmt: skip
            raise SupportError("support.err.none")
        got = self.get(sid)
        assert got is not None
        return got
