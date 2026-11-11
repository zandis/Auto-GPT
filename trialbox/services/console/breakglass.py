"""Break-glass (D-280, owner decision OD-5; TB-REG-01 CR-023, CR-029).

The administrator (the IT operator) sees no patient data on the routine pages: ``User.can_view_phi`` and
``User.can_reveal`` leave the role out, and so do the study-task and SAE tables of ``tb_common.authz``. When the
operator must look at one patient or one job (a support call, a data fix, an opt-out request, an incident), the
operator opens a **grant** on ``/breakglass``:

* a reason from a fixed list (``tb_common.authz.BREAK_GLASS_REASONS``) and a written note of 10 characters or more;
* one patient (study and pseudonym) or one job, never more; a new grant ends the one before;
* 60 minutes from the moment it opens, then it ends by itself; the operator may end it sooner.

Under the grant the operator may open that patient's page or that job's page and reveal a chart number on it, through
the console's one reveal path (``home.apply_reveal``). The reveal is signed with ``BREAK_GLASS_ROLE``, the only
administrator role the orchestrator accepts. Every opening, every use and every end is an audit event with the
person, the reason, the pseudonym and the time.

The steward and the study's PI are told at once: the grant is on their list on this page from the moment it opens,
and a mail notice goes to their mailboxes (best effort; a mail that fails is an audit event, the list still shows it).
The steward reviews each grant; an unreviewed grant stays on the steward's list, marked overdue after 7 days.

Who sees this page: the administrator (open, end, own history), the steward (every grant, review) and an investigator
who is the PI of a study (that study's grants, read only). Anyone else gets 403.
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
MIGRATIONS = (SCHEMA_V1,)
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

    def used(self, gid: int) -> None:
        self.db.execute("UPDATE grants SET uses = uses + 1 WHERE id = ?", (gid,))

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
    if g.kind == "patient":
        return g.ruleset
    try:
        job = h.bk.get_job(g.job_id)
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
        if user.role != "investigator" or h.team is None:
            return set()
        out = set()
        for s in h.bk.rulesets():
            pi = h.team.pi_of(s.id, h.today())
            if pi is not None and pi.username == user.username and user.sees_study(s.id):
                out.add(s.id)
        return out

    def use(sess: Session, *, ruleset: str = "", pid: str = "", job_id: str = "", what: str = "") -> Grant | None:
        """The administrator's open grant that covers this patient or job; each use is one audit event."""
        if not sess.user.is_admin:
            return None
        g = bg.covering(sess.user.username, now(), ruleset=ruleset, pid=pid, job_id=job_id)
        if g is None:
            return None
        bg.used(g.id)
        au.append("console.breakglass_use", actor=h.actor(sess), ruleset=ruleset or None, job_id=job_id or None,
                  detail={"grant": g.id, "reason": g.reason, "kind": g.kind, "what": what[:80],
                          **({"pid": pid} if pid else {})})  # fmt: skip
        return g

    h.breakglass = use

    def tell(sess: Session, g: Grant) -> None:
        """The steward and the study's PI are told at once by mail (internal addresses, pseudonym only)."""
        rid = study_of(h, g)
        to = {u.mailbox for u in h.users.users() if u.role == "steward" and u.mailbox}
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
        role = sess.user.role
        if role == "admin":
            mine = bg.of(sess.user.username)
            return {"mode": "admin", "grants": mine, "active": [g for g in mine if g.active(t)]}
        if role == "steward":
            rows = bg.grants()
            rows.sort(key=lambda g: (g.reviewed_at is not None, g.id * -1))
            return {"mode": "steward", "grants": rows, "active": []}
        studies = pi_studies(sess.user)
        if studies:
            rows = [g for g in bg.grants() if study_of(h, g) in studies]
            return {"mode": "pi", "grants": rows, "active": []}
        raise deny(sess, path)

    @app.get("/breakglass")
    def page(request: Request, done: str = "", err: str = "") -> Response:
        sess = h.need(request)
        ctx = view(sess, request.url.path)
        return h.page(request, "breakglass.html", sess, **ctx, now=now(), reasons=BREAK_GLASS_REASONS,
                      minutes=BREAK_GLASS_MINUTES, note_min=BREAK_GLASS_NOTE_MIN, review_days=BREAK_GLASS_REVIEW_DAYS,
                      done=done if done in ("open", "end", "review") else "",
                      err=err if err.startswith("bg.err.") else "")  # fmt: skip

    @app.post("/breakglass")
    def open_grant(request: Request, csrf: str = Form(""), reason: str = Form(""), note: str = Form(""),
                   kind: str = Form(""), ruleset: str = Form(""), pid: str = Form(""),
                   job_id: str = Form("")) -> Response:  # fmt: skip
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.is_admin:
            raise deny(sess, request.url.path)
        try:
            if kind == "patient" and not sess.user.sees_study(ruleset.strip().upper()):
                raise BreakGlassError("bg.err.target")
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
        if not sess.user.is_admin:
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
        if sess.user.role != "steward":
            raise deny(sess, request.url.path)
        try:
            g = bg.review(gid, sess.user.username, note, now())
        except BreakGlassError as exc:
            return RedirectResponse(f"/breakglass?err={exc}", status_code=303)
        au.append("console.breakglass_review", actor=h.actor(sess), detail={"grant": g.id, "uses": g.uses})
        return RedirectResponse("/breakglass?done=review", status_code=303)

    return bg
