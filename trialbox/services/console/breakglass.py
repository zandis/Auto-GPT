"""Break-glass (D-280, owner decision OD-5; TB-REG-01 CR-023, CR-029).

The administrator (the IT operator) sees no patient data on the routine pages: ``User.can_view_phi`` and
``User.can_reveal`` leave the role out, and so do the study-task and SAE tables of ``tb_common.authz``. When the
operator must look at one patient or one job (a support call, a data fix, an opt-out request, an incident), the
operator opens a **grant** on ``/breakglass``:

* a reason from a fixed list (``tb_common.authz.BREAK_GLASS_REASONS``) and a written note of 10 characters or more;
* one patient (study and pseudonym) or one job, never more; a new grant ends the one before;
* 60 minutes from the moment it opens, then it ends by itself; the operator may end it sooner.

Under the grant the operator may open that patient's page or that job's page and reveal a chart number on it, through
the console's one reveal path (``home.apply_reveal``). The reveal is signed with the account's own role and the
grant's id (T-716, D-484): the orchestrator reads the row and writes the use, and there is no ``breakglass`` role.
Every opening, every use and every end is an audit event with the
person, the reason, the pseudonym and the time.

The steward and the study's PI are told at once: the grant is on their list on this page from the moment it opens,
and a mail notice goes to their mailboxes (best effort; a mail that fails is an audit event, the list still shows it).
The steward reviews each grant; an unreviewed grant stays on the steward's list, marked overdue after 7 days.

Who sees this page: the administrator (open, end, own history), the steward (every grant, review) and an investigator
who is the PI of a study (that study's grants, read only). Anyone else gets 403.

T-309 (D-430): **one rule** for every reader. An account reads a study's patients by its own rights
(``Helpers.reads``: the ``phi.view`` row, then the delegation log) or, outside them, only under a grant of its own for
that patient or that job; the ``breakglass.open`` row says who may hold one: the administrator and the investigator
(an investigator the study's log does not reach, or a study with no PI named yet). There is no second person (the old
contract of TB-PLAN-05 WS-06.6 is void). A grant for what the account already reads is refused (``bg.err.needless``).
Every use is a row of the ``uses`` table and shows, one line each, on the steward's review list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from tb_common.authz import (
    BREAK_GLASS_MINUTES,
    BREAK_GLASS_NOTE_MIN,
    BREAK_GLASS_REASONS,
    BREAK_GLASS_REVIEW_DAYS,
    conditional,
    permit,
)

from console import i18n_breakglass
from console.auth import Session, User
from console.home import Helpers
from console.i18n import CATALOGUES
from console.storedb import open_db

for _lang, _cat in (("en", i18n_breakglass.EN), ("ja", i18n_breakglass.JA), ("zh-TW", i18n_breakglass.ZH)):
    CATALOGUES[_lang].update(_cat)

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
MIGRATIONS = (SCHEMA_V1, SCHEMA_V2)
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


def study_of(h: Helpers, g: Grant) -> str:
    """The study a grant is about: its own for a patient grant, the job's for a job grant ('' when unknown)."""
    return g.ruleset if g.kind == "patient" else job_study(h, g.job_id)


def job_study(h: Helpers, job_id: str) -> str:
    """A job's study ('' when the job or its study is unknown)."""
    try:
        job = h.bk.get_job(job_id)
    except Exception:
        return ""
    return str(getattr(job, "ruleset", "") or "")


def register(app: FastAPI, h: Helpers, store: BreakGlassStore | None = None) -> BreakGlassStore:
    bg = store if store is not None else BreakGlassStore()
    au = h.au

    def now() -> datetime:
        return h.clock()

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def pi_studies(user: User) -> set[str]:
        """The studies whose delegation log names this investigator as PI today."""
        if not conditional(user.role, "breakglass.study") or h.team is None:  # T-102c: the row's "pi" condition
            return set()
        out = set()
        for s in h.bk.rulesets():
            pi = h.team.pi_of(s.id, h.today())
            if pi is not None and pi.username == user.username and user.sees_study(s.id):
                out.add(s.id)
        return out

    def find(sess: Session, *, ruleset: str = "", pid: str = "", job_id: str = "") -> Grant | None:
        """The account's open grant that covers this patient or job, without using it. T-716 (D-484): the reveal
        path asks this; the orchestrator reads the same row and writes the use when it gives the chart number."""
        if not permit(sess.user.role, "breakglass.open"):
            return None
        return bg.covering(sess.user.username, now(), ruleset=ruleset, pid=pid, job_id=job_id)

    def use(sess: Session, *, ruleset: str = "", pid: str = "", job_id: str = "", what: str = "") -> Grant | None:
        """The account's open grant that covers this patient or job; each use is one audit event and one row of
        ``uses``. The callers ask only where the account does not read by its own rights (``Helpers.reads``)."""
        g = find(sess, ruleset=ruleset, pid=pid, job_id=job_id)
        if g is None:
            return None
        bg.used(g.id, what=what.replace(" ", "_")[:40], now=now(), ruleset=ruleset, pid=pid, job_id=job_id)
        note(sess, g, ruleset=ruleset, pid=pid, job_id=job_id, what=what)
        return g

    def note(sess: Session, g: Grant, *, ruleset: str = "", pid: str = "", job_id: str = "", what: str = "") -> None:
        """The audit event of one use. For a chart number (T-716, D-484) the row of ``uses`` is the orchestrator's,
        written when it gives the number; the console writes this event after it, so the trail still has every use."""
        au.append("console.breakglass_use", actor=h.actor(sess), ruleset=ruleset or None, job_id=job_id or None,
                  detail={"grant": g.id, "reason": g.reason, "kind": g.kind, "what": what[:80],
                          **({"pid": pid} if pid else {})})  # fmt: skip

    h.breakglass = use
    h.breakglass_find = find
    h.breakglass_note = note

    def tell(sess: Session, g: Grant) -> None:
        """The steward and the study's PI are told at once by mail (internal addresses, pseudonym only)."""
        rid = study_of(h, g)
        to = {u.mailbox for u in h.users.users() if permit(u.role, "breakglass.review") and u.mailbox}
        if rid and h.team is not None:
            pi = h.team.pi_of(rid, h.today())
            for u in h.users.users():
                if pi is not None and u.username == pi.username and u.mailbox:
                    to.add(u.mailbox)
        if not to:
            au.append("console.breakglass_notice", actor=h.actor(sess), detail={"grant": g.id, "sent": 0})
            return
        what = f"{rid} · {g.pid[:8]}" if g.kind == "patient" else f"{rid or '-'} · job {g.job_id[-8:]}"
        body = (f"Break-glass grant #{g.id} opened by {sess.user.username} at {g.opened_at} (UTC), "
                f"for {BREAK_GLASS_MINUTES} minutes.\n\nReason: {g.reason}\n\nCovers: {what}\n\n"
                f"Review it on the console's break-glass page (/breakglass).")  # fmt: skip
        try:
            h.bk.send_notice("BG", sorted(to), f"TrialBox break-glass #{g.id}: {rid or 'job'}", body,
                             h.actor(sess))  # fmt: skip
            sent = len(to)
        except Exception as exc:
            au.append("console.breakglass_notice", actor=h.actor(sess),
                      detail={"grant": g.id, "sent": 0, "error": type(exc).__name__})  # fmt: skip
            return
        au.append("console.breakglass_notice", actor=h.actor(sess), detail={"grant": g.id, "sent": sent})

    def view(sess: Session, path: str) -> dict[str, Any]:
        t = now()
        user = sess.user
        if permit(user.role, "breakglass.review"):  # the steward: every grant, unreviewed first
            rows = bg.grants()
            rows.sort(key=lambda g: (g.reviewed_at is not None, g.id * -1))
            return {"mode": "steward", "grants": rows, "active": [], "help": "bg.help.steward"}
        mine = bg.of(user.username) if permit(user.role, "breakglass.open") else []
        studies = pi_studies(user)  # the PI: also the grants that touched its studies
        theirs = [g for g in bg.grants() if g.username != user.username and study_of(h, g) in studies]
        if not mine and not theirs and not permit(user.role, "breakglass.read"):
            raise deny(sess, path)
        rows = sorted(mine + theirs, key=lambda g: -g.id)
        can_open = permit(user.role, "breakglass.open").allowed
        hint = "bg.help.admin" if user.is_admin else "bg.help.reader" if can_open else "bg.help.pi"
        return {"mode": "open" if can_open else "pi", "grants": rows, "active": [g for g in mine if g.active(t)],
                "help": hint}  # fmt: skip

    def reads_target(user: User, kind: str, ruleset: str, job_id: str) -> tuple[str, bool]:
        """The study of the target and whether the account reads it by its own rights (then no grant is needed)."""
        rid = ruleset.strip().upper() if kind == "patient" else job_study(h, job_id.strip()) if kind == "job" else ""
        return rid, bool(rid) and h.reads(user, rid)

    @app.get("/breakglass")
    def page(request: Request, done: str = "", err: str = "") -> Response:
        sess = h.need(request)
        ctx = view(sess, request.url.path)
        uses = bg.uses_of([g.id for g in ctx["grants"]])
        return h.page(request, "breakglass.html", sess, **ctx, uses=uses, whats=WHATS, now=now(),
                      reasons=BREAK_GLASS_REASONS, minutes=BREAK_GLASS_MINUTES, note_min=BREAK_GLASS_NOTE_MIN,
                      review_days=BREAK_GLASS_REVIEW_DAYS,
                      done=done if done in ("open", "end", "review") else "",
                      err=err if err.startswith("bg.err.") else "")  # fmt: skip

    @app.post("/breakglass")
    def open_grant(request: Request, csrf: str = Form(""), reason: str = Form(""), note: str = Form(""),
                   kind: str = Form(""), ruleset: str = Form(""), pid: str = Form(""),
                   job_id: str = Form("")) -> Response:  # fmt: skip
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not permit(sess.user.role, "breakglass.open"):
            raise deny(sess, request.url.path)
        try:
            # T-309 (D-430): a study the account sees, and only outside its own rights (the one rule)
            rid, own = reads_target(sess.user, kind, ruleset[:40], job_id[:80])
            if rid and not sess.user.sees_study(rid):
                raise BreakGlassError("bg.err.target")
            if own:
                raise BreakGlassError("bg.err.needless")
            g, ended = bg.open(sess.user.username, reason=reason, note=note[:NOTE_MAX * 2], kind=kind,
                               ruleset=ruleset[:40], pid=pid[:80], job_id=job_id[:80], now=now())  # fmt: skip
        except BreakGlassError as exc:
            return RedirectResponse(f"/breakglass?err={exc}", status_code=303)
        for e in ended:
            au.append("console.breakglass_end", actor=h.actor(sess), detail={"grant": e.id, "why": "replaced"})
        au.append("console.breakglass_open", actor=h.actor(sess), ruleset=g.ruleset or None, job_id=g.job_id or None,
                  detail={"grant": g.id, "reason": g.reason, "note": g.note, "kind": g.kind, "ends_at": g.ends_at,
                          **({"pid": g.pid} if g.pid else {})})  # fmt: skip
        tell(sess, g)
        return RedirectResponse("/breakglass?done=open", status_code=303)

    @app.post("/breakglass/{gid}/end")
    def end_grant(request: Request, gid: int, csrf: str = Form("")) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not permit(sess.user.role, "breakglass.open"):
            raise deny(sess, request.url.path)
        try:
            bg.end(gid, sess.user.username, now())
        except BreakGlassError as exc:
            return RedirectResponse(f"/breakglass?err={exc}", status_code=303)
        au.append("console.breakglass_end", actor=h.actor(sess), detail={"grant": gid, "why": "by hand"})
        return RedirectResponse("/breakglass?done=end", status_code=303)

    @app.post("/breakglass/{gid}/review")
    def review_grant(request: Request, gid: int, csrf: str = Form(""), note: str = Form("")) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not permit(sess.user.role, "breakglass.review"):
            raise deny(sess, request.url.path)
        try:
            g = bg.review(gid, sess.user.username, note, now())
        except BreakGlassError as exc:
            return RedirectResponse(f"/breakglass?err={exc}", status_code=303)
        au.append("console.breakglass_review", actor=h.actor(sess), detail={"grant": g.id, "uses": g.uses})
        return RedirectResponse("/breakglass?done=review", status_code=303)

    return bg
