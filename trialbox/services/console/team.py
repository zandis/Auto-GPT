"""Whole-hospital screening, sub-investigators and referral (owner decisions 2026-11-09, D-147).

* **Rights by delegation** (:func:`standing`, :func:`may`): the PI adds sub-investigators to the study's delegation
  log (``/studies/{rs}/team``) and ticks what each may do: ``screen`` (see the candidates and their candidate page),
  ``approach`` (mark Approach), ``refer`` (ask a treating doctor), ``enter_data``. Only the PI approves the criteria
  and keeps the log. Until a study's log names a PI, every investigator of the study acts as its PI, as before.
  Coordinators and administrators keep their role's rights. Every action records who did it (the audit trail and the
  rows' ``by``).
* **Candidates** (``/studies/{rs}/candidates``): every candidate the study's screening run found, whoever the treating
  doctor is. A candidate's page opens only with a purpose, is logged with the study and the purpose, and is
  rate-limited per person (``TB_CANDIDATE_VIEWS_PER_HOUR``, default 60). On it the PI and delegated sub-PIs see the
  cited record, why the patient fits or not and, through D-143's reveal (a reason, audited on both sides, the
  orchestrator's per-person cap), the chart number; the view's purpose is added to that record.
* **Referral**: the treating doctor may be unknown. TrialBox only *suggests* the attending the data names; the PI or
  sub-PI confirms it, picks from the steward's staff directory (``/site/staff``), types a name, chooses "arranged
  outside TrialBox", or falls back to the department contact. A missing field never stops the request. The CRC
  records the doctor's answer (agree to introduce / decline with a reason / discuss), so the doctor needs no account.
  While a referral waits or was declined, Approach is refused: the PI contacts the patient only after agreement.
* **IRB approval and the current consent-form version** (``/studies/{rs}/irb``): missing or expired gives a warning
  before Approach, not a gate; every override is recorded.
* **Opt-out register** (``/site/opt-outs``, kept by the research office or the steward): an opted-out patient leaves
  screening, every candidate list and later exports (``tb_common.optout``); each registration is audited.

The same actions are on ``/api/v1`` (D-125) with the same rules.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from tb_common.authz import study_tasks
from tb_common.optout import SOURCES, OptOutError, OptOutRegister

from console import s28
from console import studies as st
from console.auth import REVEAL_REASONS, Session, User
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.studies import known_study
from console.teamstore import (
    ANSWERS,
    CHANNELS,
    CHECK_RESULTS,
    DECLINE_REASONS,
    LOG_ROLES,
    ROUTES,
    TASKS,
    VIEW_PURPOSES,
    Entry,
    Irb,
    TeamError,
    TeamStore,
)
from console.timefmt import local_date, site_zone

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_CHART = re.compile(r"^[A-Za-z0-9-]{1,40}$")
CHECK_DAYS = 30  # the copy is compared with the office's signed log every month


@dataclass(frozen=True)
class Standing:
    """What one account may do in one study."""

    pi: bool  # the study's PI (or, before the log names one, any investigator of the study)
    tasks: frozenset[str]
    logged: bool  # the study's log names a PI
    entry: Entry | None = None  # the account's own active entry, if any


def standing(team: TeamStore, user: User, rs: str, today: date) -> Standing:
    """The one permission function of D-147: pages and ``/api/v1`` both ask it. The rights per role come from the
    role table (``tb_common.authz.study_tasks``); this reads the study's delegation log into it."""
    if not user.sees_study(rs) or user.aggregate_only:
        return Standing(False, frozenset(), False)
    entries = team.entries(rs)
    pi = next((e for e in reversed(entries) if e.role == "pi" and e.active_on(today)), None)
    mine = [e for e in entries if e.username == user.username and e.active_on(today)]
    own = mine[-1] if mine else None
    is_pi = user.role == "investigator" and (pi is None or pi.username == user.username)
    ticked = frozenset(t for e in mine if e.role == "sub_pi" for t in e.tasks)
    tasks = study_tasks(user.role, log_names_pi=pi is not None, is_pi=is_pi, ticked=ticked)
    return Standing(is_pi, tasks, pi is not None, pi if is_pi and pi is not None else own)


def check_due(team: TeamStore, rs: str, today: date, tz: ZoneInfo) -> bool:
    """The monthly comparison with the office's signed log is due (or was never made) for a study with a log.

    ``today`` is the site's date; a check's stored time is a UTC instant, so it is read on the site's calendar too
    (D-270: a check at 08:00 in Tokyo is the day before in UTC)."""
    if not team.entries(rs):
        return False
    checks = team.checks(rs)
    return not checks or local_date(checks[0].at, tz) < (today - timedelta(days=CHECK_DAYS)).isoformat()


class ApiReferral(BaseModel):
    route: str = ""
    staff_id: int | None = None
    name: str = Field(default="", max_length=120)
    department: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=300)


class ApiAnswer(BaseModel):
    answer: str
    reason: str = ""
    channel: str = ""
    note: str = Field(default="", max_length=300)


class ApiIrb(BaseModel):
    approval_no: str = Field(default="", max_length=60)
    approved_on: str = ""
    expires_on: str = ""
    icf_version: str = Field(default="", max_length=40)
    icf_date: str = ""


class ApiOptOut(BaseModel):
    pid: str = ""
    chart_no: str = ""
    source: str = "office"
    note: str = Field(default="", max_length=300)
    lift: bool = False


def register(app: FastAPI, h: Helpers, env: Mapping[str, str]) -> None:
    bk, au, store = h.bk, h.au, h.store
    team = TeamStore()  # schema team of the trial database (TB_DB_URL, D-126)
    optout = OptOutRegister()  # schema optout, read by the orchestrator too
    h.team, h.optout = team, optout
    per_hour = int(env.get("TB_CANDIDATE_VIEWS_PER_HOUR") or 60)
    # D-273 (PV-6): chart numbers turned into pseudonyms at the opt-out door, per person and hour
    lookups_per_hour = int(env.get("TB_OPTOUT_LOOKUPS_PER_HOUR") or 30)

    def today() -> date:
        return h.today()  # the site's date, not the UTC date (D-270)

    def now() -> str:
        return h.clock().isoformat()

    def stand(user: User, rid: str) -> Standing:
        return standing(team, user, rid, today())

    def may(user: User, rid: str, task: str) -> bool:
        return task in stand(user, rid).tasks

    def may_approve(user: User, rid: str) -> bool:
        """FR-AUTH-13 and D-147: the investigator approves, and once the log names a PI, only that PI."""
        s = stand(user, rid)
        return user.can_approve and (s.pi or not s.logged)

    h.may, h.may_approve, h.stand = may, may_approve, stand  # T-512: h.may_run reads the standing too
    h.team_due = lambda rid: check_due(team, rid, today(), site_zone(bk))

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def study_or_404(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not known_study(bk, rid):
            if _RS.match(rid):
                au.append("console.denied", actor=h.actor(sess), detail={"action": f"study {rid}"})
            raise h.problem(404, "notfound")
        return rid

    def refused(exc: Exception) -> Exception:
        return h.problem(400, "request.refused", reason=str(exc))

    def need_csrf(sess: Session, form: Mapping[str, Any]) -> None:
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")

    def need_task(sess: Session, rid: str, task: str, path: str) -> Standing:
        s = stand(sess.user, rid)
        if task not in s.tasks:
            raise deny(sess, path)
        return s

    # ------------------------------------------------------------------ candidates
    def candidate_rows(sess: Session, rid: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        wk = h.week_bundle(sess, rid) if h.week_bundle else None
        if wk is None:
            return None, []
        names = (wk["summary"] or {}).get("practitioner_names") or {}
        reg = h.registry_map(rid) if h.registry_map else {}
        rows = st.weekly_rows(wk["cl"], h.crit_of(rid, sess.lang) if h.crit_of else {}, reg, store.latest_marks(rid),
                              {}, wk["job"].job_id, names, include_closed=True, today=today())  # fmt: skip
        refs = team.latest_referrals(rid)
        staff = {s.practitioner_id: s for s in team.staff() if s.practitioner_id}
        nos = store.screening_nos(rid)
        for r in rows:
            r["referral"] = refs.get(r["pid"])
            r["doctor"] = suggestion(r, names, staff)
            r["n_open"] = st.n_open(r)
            r["screening_no"] = nos.get(r["pid"])
        return wk, rows

    def suggestion(row: Mapping[str, Any], names: Mapping[str, str], staff: Mapping[str, Any]) -> dict[str, Any]:
        """The attending the data names, as a *suggestion* with its source, or unknown (owner decision 2026-11-09)."""
        prac = str(row.get("practitioner_id") or "")
        if not prac:
            return {"known": False, "id": "", "name": "", "department": str(row.get("department") or "")}
        member = staff.get(prac)
        return {
            "known": True,
            "id": prac,
            "name": member.name if member else names.get(prac, prac),
            "department": str(row.get("department") or (member.department if member else "")),
            "contact": member.contact if member else "",
            "in_directory": member is not None,
        }

    def rate(sess: Session, rid: str, pid: str, purpose: str) -> None:
        """Candidate pages opened per person and hour (the chart number itself is under D-143's cap). D-273: the view
        is recorded and counted in one transaction (``TeamStore.take``), so parallel requests cannot all pass."""
        since = (h.clock() - timedelta(hours=1)).isoformat()
        if not team.take(rid, pid, purpose, "view", sess.user.username, now(), since, per_hour):
            au.append("console.rate_limited", actor=h.actor(sess), detail={"action": "view", "limit": per_hour})
            raise h.problem(429, "candidate.rate_limited", n=per_hour)

    def chart_lookup(sess: Session, purpose: str) -> None:
        """D-273 (PV-6): one chart number turned into a pseudonym, at the opt-out door or by a pasted chart. The use
        is taken before the lookup, counted and recorded in one transaction; over the cap it is refused and audited.
        The caller writes ``console.chart_lookup`` once the lookup is done."""
        since = (h.clock() - timedelta(hours=1)).isoformat()
        if not team.take("-", "-", purpose, "chart_lookup", sess.user.username, now(), since, lookups_per_hour):
            au.append("console.rate_limited", actor=h.actor(sess),
                      detail={"action": "chart_lookup", "limit": lookups_per_hour})  # fmt: skip
            raise h.problem(429, "optout.rate_limited", n=lookups_per_hour)

    h.chart_lookup = chart_lookup

    def candidate_ctx(sess: Session, rid: str, pid: str) -> dict[str, Any]:
        if not _PID.match(pid) or h.patient_ctx is None:
            raise h.problem(404, "notfound")
        ctx = h.patient_ctx(sess, rid, pid)
        wk = h.week_bundle(sess, rid) if h.week_bundle else None
        names = ((wk or {}).get("summary") or {}).get("practitioner_names") or {}
        staff = {s.practitioner_id: s for s in team.staff() if s.practitioner_id}
        s = stand(sess.user, rid)
        refs = team.referrals(rid, pid)
        ctx.update(
            doctor=suggestion(ctx["row"], names, staff),
            referrals=refs,
            referral=refs[-1] if refs else None,
            ref_events=team.referral_events(rid, pid),
            staff=team.staff(),
            contacts=team.contacts(),
            routes=ROUTES,
            purposes=VIEW_PURPOSES,
            standing=s,
            may_refer=("refer" in s.tasks),
            may_reveal=("screen" in s.tasks) and sess.user.sees_ids(rid),
            reveal_reasons=REVEAL_REASONS,
            views=team.views(rid, pid)[:10],
            irb_warn=team.irb(rid).warnings(today()),
        )
        return ctx

    def view_candidate(sess: Session, path: str, rs: str, pid: str, purpose: str) -> tuple[str, dict[str, Any]]:
        rid = study_or_404(sess, rs)
        need_task(sess, rid, "screen", path)
        if purpose not in VIEW_PURPOSES:
            raise h.problem(400, "candidate.purpose")
        ctx = candidate_ctx(sess, rid, pid)
        rate(sess, rid, pid, purpose)
        au.append("console.candidate_view", job_id=ctx["job"].job_id, ruleset=rid, actor=h.actor(sess),
                  detail={"pid": pid, "purpose": purpose, "role": sess.user.role,
                          "pi": ctx["standing"].pi})  # fmt: skip
        ctx["purpose"] = purpose
        return rid, ctx

    def reveal_candidate(sess: Session, path: str, rs: str, pid: str, purpose: str, reason: str,
                         note: str = "") -> dict[str, Any]:  # fmt: skip
        """The chart number of one candidate through D-143's reveal (``h.apply_reveal``): identifier authority for
        the study and, for an investigator, the delegation log's "screen"; the D-143 reason; the audit record on both
        sides and the orchestrator's per-person cap. The candidate page adds only the view's purpose to the record."""
        rid = study_or_404(sess, rs)
        if purpose not in VIEW_PURPOSES:
            raise h.problem(400, "candidate.purpose")
        if h.apply_reveal is None:
            raise deny(sess, path)
        _ctx, mrn = h.apply_reveal(sess, path, rid, pid, reason, via="candidates", purpose=purpose, note=note)
        team.record_view(rid, pid, purpose, "reveal", sess.user.username, now())
        ctx = candidate_ctx(sess, rid, pid)
        ctx["mrn"] = mrn
        ctx["purpose"] = purpose
        return ctx

    @app.get("/studies/{rs}/candidates")
    def candidates(request: Request, rs: str, page: int = 1, show: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        need_task(sess, rid, "screen", request.url.path)
        wk, rows = candidate_rows(sess, rid)
        if show == "unknown":
            rows = [r for r in rows if not r["doctor"]["known"]]
        elif show == "open":
            rows = [r for r in rows if r["referral"] is not None and r["referral"].open]
        n_all = len(rows)
        shown, page_no, pages = st.paged(rows, page)
        removed = len((wk or {}).get("removed") or ())  # only the count: who opted out is itself private
        return h.page(request, "team_candidates.html", sess, rs=rid, wk=wk, rows=shown, n_all=n_all, page_no=page_no,
                      pages=pages, show=show, removed=removed, standing=stand(sess.user, rid),
                      purposes=VIEW_PURPOSES)  # fmt: skip

    @app.get("/studies/{rs}/candidates/{pid}")
    def candidate(request: Request, rs: str, pid: str, purpose: str = "") -> Response:
        sess = h.need(request)
        if purpose not in VIEW_PURPOSES:  # nothing patient-level before the purpose is given
            rid = study_or_404(sess, rs)
            need_task(sess, rid, "screen", request.url.path)
            if not _PID.match(pid):
                raise h.problem(404, "notfound")
            return h.page(request, "team_purpose.html", sess, rs=rid, pid=pid, purposes=VIEW_PURPOSES)
        rid, ctx = view_candidate(sess, request.url.path, rs, pid, purpose)
        return h.page(request, "team_candidate.html", sess, **ctx)

    @app.post("/studies/{rs}/candidates/{pid}/reveal")
    async def candidate_reveal(request: Request, rs: str, pid: str) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        ctx = reveal_candidate(sess, request.url.path, rs, pid, str(form.get("purpose") or ""),
                               str(form.get("reason") or ""), str(form.get("note") or "")[:200])  # fmt: skip
        return h.page(request, "team_candidate.html", sess, **ctx)

    # ------------------------------------------------------------------ referral
    def request_referral(sess: Session, path: str, rs: str, pid: str, body: ApiReferral) -> tuple[str, int, str]:
        rid = study_or_404(sess, rs)
        need_task(sess, rid, "refer", path)
        if not _PID.match(pid) or h.patient_ctx is None:
            raise h.problem(404, "notfound")
        ctx = h.patient_ctx(sess, rid, pid)  # 404 unless the study's run lists the patient (opt-outs never)
        wk = h.week_bundle(sess, rid) if h.week_bundle else None
        names = ((wk or {}).get("summary") or {}).get("practitioner_names") or {}
        staff = {s.practitioner_id: s for s in team.staff() if s.practitioner_id}
        sug = suggestion(ctx["row"], names, staff)
        route = body.route or ("suggested" if sug["known"] else "department")
        if route not in ROUTES:
            raise refused(TeamError("choose how the treating doctor is asked"))
        physician, physician_id, dept = "", "", body.department.strip() or sug["department"]
        if route == "suggested" and sug["known"]:
            physician, physician_id = sug["name"], sug["id"]
        elif route == "directory" and body.staff_id is not None:
            member = team.staff_member(body.staff_id)
            if member is not None:
                physician, physician_id = member.name, member.practitioner_id
                dept = member.department or dept
        elif route in ("typed", "outside"):
            physician = body.name.strip()
        elif route == "department":
            c = next((c for c in team.contacts() if c.department == dept), None)
            physician = c.name if c else ""
        # a referral never stalls on a missing field: an unnamed doctor is recorded as unknown and the CRC finds them
        try:
            ref_id = team.add_referral(rid, pid, route=route, physician=physician, physician_id=physician_id,
                                       department=dept, suggested=sug["name"] if sug["known"] else "",
                                       suggested_source="data" if sug["known"] else "", note=body.note,
                                       by=sess.user.username, at=now())  # fmt: skip
        except TeamError as exc:
            raise refused(exc) from exc
        settings = h.settings_of(rid) if h.settings_of else None
        no = store.assign_screening_no(rid, pid, settings, now()) if settings is not None else None
        au.append("console.referral", job_id=ctx["job"].job_id, ruleset=rid, actor=h.actor(sess),
                  detail={"pid": pid, "action": "requested", "route": route, "known": bool(physician),
                          "suggested": sug["known"], "changed": route != "suggested" and sug["known"],
                          "run": no or "", "id": ref_id})  # fmt: skip
        return rid, ref_id, no or ""

    @app.post("/studies/{rs}/candidates/{pid}/referral")
    async def referral_form(request: Request, rs: str, pid: str) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        sid = str(form.get("staff_id") or "").strip()
        body = ApiReferral(route=str(form.get("route") or ""), staff_id=int(sid) if sid.isdigit() else None,
                           name=str(form.get("name") or "")[:120], department=str(form.get("department") or "")[:40],
                           note=str(form.get("note") or "")[:300])  # fmt: skip
        rid, ref_id, _ = request_referral(sess, request.url.path, rs, pid, body)
        return RedirectResponse(f"/studies/{rid}/referrals?done=requested#r{ref_id}", status_code=303)

    def answer_referral(sess: Session, path: str, rs: str, ref_id: int, body: ApiAnswer) -> tuple[str, Any]:
        """The doctor's answer, recorded by the CRC (who asked by phone, in person or by EMR message) or, for a
        referral arranged outside TrialBox, by the PI or sub-PI who asked."""
        rid = study_or_404(sess, rs)
        if not (sess.user.role == "coordinator" or may(sess.user, rid, "refer")):
            raise deny(sess, path)
        if body.answer not in ANSWERS:
            raise refused(TeamError("choose the doctor's answer: agree, decline or discuss"))
        try:
            ref = team.answer(rid, ref_id, body.answer, body.reason, body.channel, body.note, sess.user.username, now())
        except TeamError as exc:
            raise h.problem(409, "request.refused", reason=str(exc)) from exc
        au.append("console.referral", ruleset=rid, actor=h.actor(sess),
                  detail={"pid": ref.pid, "action": "answered", "to": ref.state, "reason": ref.reason,
                          "channel": ref.channel, "route": ref.route, "id": ref.id})  # fmt: skip
        return rid, ref

    @app.get("/studies/{rs}/referrals")
    def referrals(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        s = stand(sess.user, rid)
        if "screen" not in s.tasks:
            raise deny(sess, request.url.path)
        on = optout.active()
        refs = [r for r in team.referrals(rid) if r.pid not in on]
        latest = team.latest_referrals(rid)
        open_refs = [r for r in refs if r.open and latest[r.pid].id == r.id]
        counts: dict[str, int] = {}
        for r in refs:
            counts[f"route.{r.route}"] = counts.get(f"route.{r.route}", 0) + 1
            counts[f"state.{r.state}"] = counts.get(f"state.{r.state}", 0) + 1
        nos = store.screening_nos(rid)
        may_answer = sess.user.role == "coordinator" or "refer" in s.tasks
        return h.page(request, "team_referrals.html", sess, rs=rid, refs=list(reversed(refs)), open_refs=open_refs,
                      counts=counts, nos=nos, routes=ROUTES, answers=ANSWERS, channels=CHANNELS,
                      reasons=DECLINE_REASONS, may_answer=may_answer, contacts=team.contacts())  # fmt: skip

    @app.post("/studies/{rs}/referrals/{ref_id}/answer")
    async def referral_answer(request: Request, rs: str, ref_id: int) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        body = ApiAnswer(answer=str(form.get("answer") or ""), reason=str(form.get("reason") or ""),
                         channel=str(form.get("channel") or ""), note=str(form.get("note") or "")[:300])  # fmt: skip
        rid, ref = answer_referral(sess, request.url.path, rs, ref_id, body)
        return RedirectResponse(f"/studies/{rid}/referrals?done={ref.state}#r{ref.id}", status_code=303)

    # ------------------------------------------------------------------ delegation log
    def accounts(rid: str) -> list[User]:
        return [u for u in h.users.users() if u.role in ("investigator", "coordinator") and u.sees_study(rid)]

    @app.get("/studies/{rs}/team")
    def team_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if sess.user.aggregate_only:
            raise deny(sess, request.url.path)
        s = stand(sess.user, rid)
        entries = team.entries(rid)
        return h.page(request, "team_log.html", sess, rs=rid, entries=entries, standing=s, tasks=TASKS,
                      log_roles=LOG_ROLES, accounts=accounts(rid), checks=team.checks(rid)[:12],
                      due=check_due(team, rid, today(), site_zone(bk)), history=team.history(rid)[-30:], today=today(),
                      can_edit=sess.user.role == "investigator" and s.pi,
                      can_check=sess.user.role == "coordinator" or (sess.user.role == "investigator" and s.pi),
                      results=CHECK_RESULTS, has_pi=team.pi_of(rid, today()) is not None)  # fmt: skip

    @app.post("/studies/{rs}/team")
    async def team_add(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        rid = study_or_404(sess, rs)
        s = stand(sess.user, rid)
        if not (sess.user.role == "investigator" and s.pi):
            raise deny(sess, request.url.path)
        username = str(form.get("username") or "").strip().lower() or None
        role = str(form.get("role") or "")
        acct = next((u for u in accounts(rid) if u.username == username), None) if username else None
        if username and acct is None:
            raise refused(TeamError("no such account for this study"))
        if role in ("pi", "sub_pi") and acct is not None and acct.role != "investigator":
            raise refused(TeamError("a sub-investigator signs in with an investigator account"))
        try:
            eid = team.add_entry(rid, username=username, name=str(form.get("name") or "").strip() or (username or ""),
                                 role=role, tasks=form.getlist("tasks"), start=str(form.get("start") or ""),
                                 end=str(form.get("end") or ""), training_day=str(form.get("training_day") or ""),
                                 training_ref=str(form.get("training_ref") or ""), by=sess.user.username,
                                 at=now())  # fmt: skip
        except TeamError as exc:
            raise refused(exc) from exc
        e = team.entry(rid, eid)
        au.append("console.delegation", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "add", "id": eid, "role": role, "username": username or "",
                          "tasks": ",".join(e.tasks) if e else ""})  # fmt: skip
        return RedirectResponse(f"/studies/{rid}/team?done=add#e{eid}", status_code=303)

    @app.post("/studies/{rs}/team/check")
    async def team_check(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        rid = study_or_404(sess, rs)
        s = stand(sess.user, rid)
        if not (sess.user.role == "coordinator" or (sess.user.role == "investigator" and s.pi)):
            raise deny(sess, request.url.path)
        result = str(form.get("result") or "")
        try:
            team.add_check(rid, result, str(form.get("note") or ""), sess.user.username, now())
        except TeamError as exc:
            raise refused(exc) from exc
        au.append("console.delegation", ruleset=rid, actor=h.actor(sess), detail={"action": "compare", "to": result})
        return RedirectResponse(f"/studies/{rid}/team?done=check", status_code=303)

    @app.post("/studies/{rs}/team/{eid}")
    async def team_edit(request: Request, rs: str, eid: int) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        rid = study_or_404(sess, rs)
        s = stand(sess.user, rid)
        if not (sess.user.role == "investigator" and s.pi):
            raise deny(sess, request.url.path)
        try:
            e = team.update_entry(rid, eid, tasks=form.getlist("tasks"), end=str(form.get("end") or ""),
                                  training_day=str(form.get("training_day") or ""),
                                  training_ref=str(form.get("training_ref") or ""), by=sess.user.username,
                                  at=now())  # fmt: skip
        except TeamError as exc:
            raise refused(exc) from exc
        au.append("console.delegation", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "update", "id": eid, "tasks": ",".join(e.tasks), "to": e.end or ""})  # fmt: skip
        return RedirectResponse(f"/studies/{rid}/team?done=update#e{eid}", status_code=303)

    # ------------------------------------------------------------------ IRB approval and consent-form version
    def may_edit_irb(sess: Session, rid: str) -> bool:
        return sess.user.role in ("coordinator", "admin") or (sess.user.role == "investigator" and stand(
            sess.user, rid).pi)  # fmt: skip

    def save_irb(sess: Session, path: str, rs: str, body: ApiIrb) -> tuple[str, Irb]:
        rid = study_or_404(sess, rs)
        if not may_edit_irb(sess, rid):
            raise deny(sess, path)
        try:
            rec = team.save_irb(rid, Irb(body.approval_no, body.approved_on, body.expires_on, body.icf_version,
                                         body.icf_date), sess.user.username, now())  # fmt: skip
        except TeamError as exc:
            raise refused(exc) from exc
        au.append("console.irb", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "save", "approved_on": rec.approved_on, "expires_on": rec.expires_on,
                          "icf_version": rec.icf_version})  # fmt: skip
        return rid, rec

    @app.get("/studies/{rs}/irb")
    def irb_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if sess.user.aggregate_only:
            raise deny(sess, request.url.path)
        rec = team.irb(rid)
        on = optout.active()
        return h.page(request, "team_irb.html", sess, rs=rid, irb=rec, warnings=rec.warnings(today()),
                      can_edit=may_edit_irb(sess, rid),
                      overrides=[o for o in team.overrides(rid) if o[0] not in on][-50:])  # fmt: skip

    @app.post("/studies/{rs}/irb")
    async def irb_save(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        body = ApiIrb(**{k: str(form.get(k) or "")[:60] for k in ApiIrb.model_fields})
        rid, _ = save_irb(sess, request.url.path, rs, body)
        return RedirectResponse(f"/studies/{rid}/irb?done=1", status_code=303)

    # ------------------------------------------------------------------ staff directory (kept by the steward)
    def can_keep(user: User) -> bool:
        """The steward's lists (staff directory, department contacts, opt-outs): the research office's coordinator
        or the administrator, as the site set-up (``site_pages.can_setup``)."""
        return user.role in ("coordinator", "admin")

    @app.get("/site/staff")
    def staff_page(request: Request) -> Response:
        sess = h.need(request)
        if not sess.user.can_view_phi:
            raise deny(sess, request.url.path)
        return h.page(request, "site_staff.html", sess, staff=team.staff(active_only=False), contacts=team.contacts(),
                      can_edit=can_keep(sess.user))  # fmt: skip

    @app.post("/site/staff")
    async def staff_add(request: Request) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        if not can_keep(sess.user):
            raise deny(sess, request.url.path)
        try:
            if form.get("kind") == "contact":
                f = {k: str(form.get(k) or "") for k in ("department", "name", "contact")}
                team.save_contact(f["department"], f["name"], f["contact"], sess.user.username, now())
                action = "contact"
            elif form.get("kind") == "active":
                sid = str(form.get("id") or "")
                team.set_staff_active(int(sid) if sid.isdigit() else -1, form.get("active") == "1",
                                      sess.user.username, now())  # fmt: skip
                action = "active" if form.get("active") == "1" else "inactive"
            else:
                f = {k: str(form.get(k) or "") for k in ("name", "department", "practitioner_id", "role", "contact",
                                                         "username")}  # fmt: skip
                team.add_staff(f["name"], f["department"], f["practitioner_id"], f["role"], f["contact"],
                               f["username"], sess.user.username, now())  # fmt: skip
                action = "add"
        except TeamError as exc:
            raise refused(exc) from exc
        au.append("console.staff", actor=h.actor(sess), detail={"action": action})
        return RedirectResponse(f"/site/staff?done={action}", status_code=303)

    # ------------------------------------------------------------------ opt-out register
    def to_pid(chart_no: str, pid: str) -> str:
        pid = pid.strip()
        if pid:
            if not _PID.match(pid):
                raise refused(OptOutError("bad pseudonym"))
            return pid
        chart = chart_no.strip()
        if not chart:
            raise refused(TeamError("give a chart number or a pseudonym"))
        if not _CHART.match(chart):
            raise refused(TeamError("chart numbers are letters, digits or '-'"))
        try:  # the box turns the chart number into the pseudonym at the door; the number is never stored
            out = s28.call(bk, "POST", "/setup/pseudonym", {"chart_no": chart})
        except (Problem, Unavailable) as exc:
            raise h.problem(409, "request.refused",
                            reason="the box could not turn the chart number into a pseudonym") from exc  # fmt: skip
        got = str((out or {}).get("pid") or "")
        if not _PID.match(got):
            raise h.problem(409, "request.refused", reason="the box could not turn the chart number into a pseudonym")
        return got

    def change_optout(sess: Session, path: str, body: ApiOptOut) -> tuple[str, bool]:
        """One opt-out or lift. D-273 (PV-6): a chart number typed at the door is a lookup of a patient's
        pseudonym, so it is capped per person and hour and audited as its own event, changed or not, and neither
        the page nor ``/api/v1`` gives the pseudonym back. D-273 (CR-055): the change's audit event is written inside
        the register's transaction, so a failed append keeps no opt-out without its event."""
        if not can_keep(sess.user):
            raise deny(sess, path)
        by_chart = bool(body.chart_no.strip()) and not body.pid.strip()
        if by_chart:
            chart_lookup(sess, "optout")
        pid = to_pid(body.chart_no, body.pid)
        if by_chart:
            au.append(
                "console.chart_lookup",
                actor=h.actor(sess),
                detail={"pid": pid, "for": "lift" if body.lift else "opt_out", "role": sess.user.role},
            )
        detail = {"pid": pid, "action": "lift" if body.lift else "opt_out",
                  "source": "" if body.lift else (body.source if body.source in SOURCES else "other"),
                  "removed_from": "" if body.lift else "screening, candidate lists, exports"}  # fmt: skip

        def audit() -> None:
            au.append("console.opt_out", actor=h.actor(sess), detail=detail)

        try:
            if body.lift:
                changed = optout.lift(pid, body.note, sess.user.username, now(), before_commit=audit)
            else:
                changed = optout.add(pid, body.source, body.note, sess.user.username, now(), before_commit=audit)
        except OptOutError as exc:
            raise refused(exc) from exc
        return pid, changed

    @app.get("/site/opt-outs")
    def optout_page(request: Request) -> Response:
        sess = h.need(request)
        if not can_keep(sess.user):
            raise deny(sess, request.url.path)
        return h.page(request, "site_optouts.html", sess, rows=optout.current(), events=optout.events()[-30:][::-1],
                      sources=SOURCES)  # fmt: skip

    @app.post("/site/opt-outs")
    async def optout_add(request: Request) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        body = ApiOptOut(pid=str(form.get("pid") or "")[:64], chart_no=str(form.get("chart_no") or "")[:40],
                         source=str(form.get("source") or "office")[:20], note=str(form.get("note") or "")[:300],
                         lift=form.get("lift") == "1")  # fmt: skip
        _pid, changed = change_optout(sess, request.url.path, body)
        done = ("lifted" if body.lift else "added") if changed else "same"
        return RedirectResponse(f"/site/opt-outs?done={done}", status_code=303)  # D-273 (PV-6): no pseudonym back

    # ------------------------------------------------------------------ /api/v1 (D-125): the same rules
    def api(request: Request) -> Session:
        assert h.api_session is not None
        return h.api_session(request)

    def ref_json(r: Any, nos: Mapping[str, str]) -> dict[str, Any]:
        return {"id": r.id, "pid": r.pid, "screening_no": nos.get(r.pid), "state": r.state, "route": r.route,
                "physician": r.physician or None, "department": r.department or None, "suggested": r.suggested or None,
                "answer": r.answer or None, "reason": r.reason or None, "channel": r.channel or None,
                "requested_by": r.requested_by, "requested_at": r.requested_at, "answered_by": r.answered_by or None,
                "answered_at": r.answered_at or None}  # fmt: skip

    @app.get("/api/v1/studies/{rs}/delegation")
    def api_delegation(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs)
        if sess.user.aggregate_only:
            raise deny(sess, request.url.path)
        s = stand(sess.user, rid)
        return {
            "study": rid,
            "you": {"pi": s.pi, "tasks": sorted(s.tasks)},
            "check_due": check_due(team, rid, today(), site_zone(bk)),
            "entries": [
                {"id": e.id, "username": e.username, "name": e.name, "role": e.role, "tasks": list(e.tasks),
                 "start": e.start, "end": e.end, "training_day": e.training_day, "signed_by": e.signed_by}
                for e in team.entries(rid)
            ],
        }  # fmt: skip

    @app.get("/api/v1/studies/{rs}/candidates")
    def api_candidates(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs)
        need_task(sess, rid, "screen", request.url.path)
        wk, rows = candidate_rows(sess, rid)
        return {
            "study": rid,
            "job_id": wk["job"].job_id if wk else None,
            "candidates": [
                {"pid": r["pid"], "tier": r["tier"], "status": r["status"], "screening_no": r["screening_no"],
                 "doctor": {"known": r["doctor"]["known"], "name": r["doctor"]["name"] or None,
                            "source": "data" if r["doctor"]["known"] else None},
                 "department": r["department"] or None, "open_items": r["n_open"],
                 "referral": r["referral"].state if r["referral"] else None,
                 "mark": r["mark"].mark if r["mark"] else None}
                for r in rows
            ],
        }  # fmt: skip

    @app.get("/api/v1/studies/{rs}/candidates/{pid}")
    def api_candidate(request: Request, rs: str, pid: str, purpose: str = "") -> dict[str, Any]:
        sess = api(request)
        rid, ctx = view_candidate(sess, request.url.path, rs, pid, purpose)
        fit = ctx["fit"]
        return {
            "study": rid,
            "pid": pid,
            "purpose": purpose,
            "tier": ctx["row"].get("tier"),
            "screening_no": ctx["screening_no"],
            "doctor": ctx["doctor"],
            "why": {"met": fit.inc_met + fit.exc_clear, "total": fit.inc_total + fit.exc_total,
                    "not_met": list(fit.not_met), "open": list(fit.open), "person": list(fit.person)},
            "criteria": [{"id": c["id"], "verdict": c["verdict"], "quote": c.get("quote"), "date": c.get("date"),
                          "source": c.get("source")} for c in ctx["crits"]],
            "referral": ref_json(ctx["referral"], {}) if ctx["referral"] else None,
            "irb_warnings": ctx["irb_warn"],
        }  # fmt: skip

    @app.post("/api/v1/studies/{rs}/candidates/{pid}/referral")
    def api_referral(request: Request, rs: str, pid: str, body: ApiReferral) -> dict[str, Any]:
        sess = api(request)
        rid, ref_id, no = request_referral(sess, request.url.path, rs, pid, body)
        ref = team.referral(rid, ref_id)
        return {"study": rid, **ref_json(ref, {pid: no})}

    @app.get("/api/v1/studies/{rs}/referrals")
    def api_referrals(request: Request, rs: str) -> list[dict[str, Any]]:
        sess = api(request)
        rid = study_or_404(sess, rs)
        need_task(sess, rid, "screen", request.url.path)
        on = optout.active()
        nos = store.screening_nos(rid)
        return [ref_json(r, nos) for r in team.referrals(rid) if r.pid not in on]

    @app.post("/api/v1/studies/{rs}/referrals/{ref_id}/answer")
    def api_answer(request: Request, rs: str, ref_id: int, body: ApiAnswer) -> dict[str, Any]:
        sess = api(request)
        rid, ref = answer_referral(sess, request.url.path, rs, ref_id, body)
        return {"study": rid, **ref_json(ref, store.screening_nos(rid))}

    @app.get("/api/v1/studies/{rs}/irb")
    def api_irb(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs)
        if sess.user.aggregate_only:
            raise deny(sess, request.url.path)
        rec = team.irb(rid)
        return {"study": rid, **{k: getattr(rec, k) or None for k in ApiIrb.model_fields},
                "warnings": rec.warnings(today())}  # fmt: skip

    @app.post("/api/v1/studies/{rs}/irb")
    def api_irb_save(request: Request, rs: str, body: ApiIrb) -> dict[str, Any]:
        sess = api(request)
        rid, rec = save_irb(sess, request.url.path, rs, body)
        return {"study": rid, **{k: getattr(rec, k) or None for k in ApiIrb.model_fields},
                "warnings": rec.warnings(today())}  # fmt: skip

    @app.get("/api/v1/site/opt-outs")
    def api_optouts(request: Request) -> dict[str, Any]:
        sess = api(request)
        if not can_keep(sess.user):
            raise deny(sess, request.url.path)
        rows = optout.current()
        return {"count": len(rows), "opted_out": [{"pid": e.pid, "since": e.at, "source": e.source, "by": e.by}
                                                  for e in rows]}  # fmt: skip

    @app.post("/api/v1/site/opt-outs")
    def api_optout(request: Request, body: ApiOptOut) -> dict[str, Any]:
        sess = api(request)
        _pid, changed = change_optout(sess, request.url.path, body)
        return {"opted_out": not body.lift, "changed": changed}  # D-273 (PV-6): no pseudonym back
