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

from datetime import datetime
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse, Response
from tb_common.authz import (
    BEST_STANDING,
    BREAK_GLASS_MINUTES,
    BREAK_GLASS_NOTE_MIN,
    BREAK_GLASS_REASONS,
    BREAK_GLASS_REVIEW_DAYS,
    conditional,
    permit,
)

from console import actor, i18n_breakglass
from console.auth import Session, User
from console.breakglass_store import (
    NOTE_MAX,
    WHATS,
    BreakGlassError,
    BreakGlassStore,
    Grant,
)
from console.home import Helpers
from console.i18n import CATALOGUES

for _lang, _cat in (("en", i18n_breakglass.EN), ("ja", i18n_breakglass.JA), ("zh-TW", i18n_breakglass.ZH)):
    CATALOGUES[_lang].update(_cat)


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
        if not permit(user.role, "breakglass.study", BEST_STANDING):  # 10K-15: refused during a support session
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
                             actor.BREAKGLASS)  # fmt: skip
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
