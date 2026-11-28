"""Whole-hospital screening, sub-investigators and referral (owner decisions 2026-11-09, D-147).

* **Rights by delegation** (:func:`standing`, :func:`may`): the PI adds sub-investigators to the study's delegation
  log (``/studies/{rs}/team``) and ticks what each may do: ``screen`` (see the candidates and their candidate page),
  ``approach`` (mark Approach), ``refer`` (ask a treating doctor), ``enter_data``. Only the PI approves the criteria
  and keeps the log. D-380 (ROLE-008): the study's first PI entry is written by the steward from the signed log;
  until the log names a PI, nobody acts as PI and an investigator has no right in the study. Coordinators keep their
  role's rights. Every action records who did it (the audit trail and the rows' ``by``).
* **Monitor grant** (D-380, FIT-002 grant half): the PI or the steward gives a CRO account a ``monitor`` entry of the
  log for the visit dates, with the monitoring-visit id. Under it the account reads the study's *enrolled* subjects
  only, read-only; a candidate, a screen failure or another study is refused; each view is audited with the visit
  id. The monitor's pages are ``console.sdv_page`` (D-436).
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
  before Approach, not a gate; every override is recorded. D-380 (ROLE-015): kept by a hospital coordinator or the
  logged PI (never an SMO account or the administrator); an approval date needs its approval number, a change needs
  a written reason, and the audit event holds the old and the new values.
* **The IRB text's coverage** (D-395, RSK-42): a candidate's page and its chart number open only while the study's PI
  has recorded, on the study set-up page (``/studies/{rs}/state``), that the approved IRB text covers "identified
  pre-screening across departments by the investigator before referral". Without it: 403 with the reason, audited.
  ``TB_IRB_TEXT_GATE``: ``auto`` (default: on in VALIDATION and PRODUCTION), ``on`` or ``off`` (refused there).
* **Approved consent-form versions** (D-399, FIT-009, LIFE-018) on the same page: a list with history (version, its
  date, the IRB's approval, the first day it is used, re-consent asked or not). The consent form's version is checked
  against it on save (``entry_pages``); ``/studies/{rs}/reconsent`` lists the subjects on study still on an older
  version than the newest in force that asks for re-consent.
* **Opt-out register** (``/site/opt-outs``, kept by the steward or the privacy office only, D-380, ROLE-005): an
  opted-out patient leaves screening, every candidate list and later exports (``tb_common.optout``); each
  registration is audited; a lift needs a written reason.

The same actions are on ``/api/v1`` (D-125) with the same rules.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from datacore.lifecycle import reconsent_due
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from tb_common import chartno
from tb_common.authz import STUDY_TASKS, conditional, permit
from tb_common.authz import Standing as Grant
from tb_common.config import environment_name
from tb_common.optout import SOURCES, OptOutError, OptOutRegister

from console import actor as acting
from console import s28
from console import studies as st
from console.api_first import before_body, page_twin
from console.auth import REVEAL_REASONS, Session, User
from console.backend import Problem, Unavailable
from console.data_pages import err_of
from console.home import Helpers
from console.i18n import translate
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
    IcfVersion,
    Irb,
    Referral,
    TeamError,
    TeamStore,
)
from console.timefmt import local_date, site_zone

DOCTOR_LANGS = ("ja", "zh-TW", "en")  # D-407 (UX-034): the languages of the request for the treating doctor

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
log = logging.getLogger("console.team")
_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_WHOLE_PID = re.compile(r"^[0-9a-f]{32}$")  # tb_common.crypto.PID_HEX_LEN hex characters: a whole pseudonym
WHOLE_PID_WHY = (
    "type the whole pseudonym (32 characters), or the chart number: the 8 characters a page shows name no patient"
)
_CHART = re.compile(r"^[A-Za-z0-9-]{1,40}$")
_REC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")  # a screening number (record id), as on the lifecycle pages
API_PAGE = 100  # P-20: the candidates API's page when a page is asked for
API_PAGE_MAX = 1000
CHECK_DAYS = 30  # the copy is compared with the office's signed log every month
IRB_REASON_MIN = 10  # D-380 (ROLE-015): the written reason for a change to a study's IRB record
LIFT_REASON_MIN = 10  # D-380 (ROLE-005): the written reason for lifting an opt-out
# NEW-DIN-3 (D-544): an opt-out typed by chart number for a pseudonym the pid map does not hold is registered only
# with a written reason of this length; without one the desk says this
UNKNOWN_REASON_MIN = 10
NOT_A_PATIENT = (
    "this chart number is not a patient of this box: check the number; to register it anyway, write why "
    f"(at least {UNKNOWN_REASON_MIN} characters)"
)
# the box could not answer (the map is away, a release that does not answer): the keeper is not told to doubt the number
CANNOT_CHECK = (
    "TrialBox cannot check this chart number now: to register it without the check, write why "
    f"(at least {UNKNOWN_REASON_MIN} characters)"
)
KNOWN_WORD = {True: "yes", False: "no", None: "cannot_say"}
IRB_FIELDS = ("approval_no", "approved_on", "expires_on", "icf_version", "icf_date")  # the stored IRB record


@dataclass(frozen=True)
class Standing:
    """What one account may do in one study."""

    pi: bool  # the PI the study's log names (D-380: no PI named, nobody is PI)
    tasks: frozenset[str]
    logged: bool  # the study's log names a PI
    entry: Entry | None = None  # the account's own active entry, if any
    monitor: Entry | None = None  # the account's monitor grant in the study today (FIT-002)

    def grant(self) -> Grant:
        """This standing as ``tb_common.authz.permit`` reads it."""
        return Grant(is_pi=self.pi, tasks=self.tasks, log_names_pi=self.logged, monitor=self.monitor is not None)


def log_account(user: User) -> bool:
    """An account whose study tasks the delegation log gives (the matrix's ``task.*`` conditions: the investigator,
    as PI or sub-investigator; T-102c, D-425)."""
    return conditional(user.role, "task.screen")


def monitor_account(user: User) -> bool:
    """An account that reads a study only under a monitor grant (the matrix's ``monitor.read`` condition: a CRO
    account, FIT-002)."""
    return conditional(user.role, "monitor.read")


def on_log(user: User) -> bool:
    """An account a delegation-log entry may name: one with a study task (by role or by the log: the coordinator, the
    investigator) or a monitor grant (a CRO account)."""
    return permit(user.role, "task.screen").allowed or log_account(user) or monitor_account(user)


def standing(team: TeamStore, user: User, rs: str, today: date) -> Standing:
    """The one permission function of D-147: pages and ``/api/v1`` both ask it. The rights per role come from the
    matrix's ``task.*`` rows (``tb_common.authz.permit``); this reads the study's delegation log into them."""
    if not user.sees_study(rs):
        return Standing(False, frozenset(), False)
    entries = team.entries(rs)
    pi = next((e for e in reversed(entries) if e.role == "pi" and e.active_on(today)), None)
    mine = [e for e in entries if e.username == user.username and e.active_on(today)]
    if user.aggregate_only:  # a CRO account: only a monitor grant (FIT-002), never a study task
        grant = next((e for e in reversed(mine) if e.role == "monitor"), None) if monitor_account(user) else None
        return Standing(False, frozenset(), pi is not None, grant, grant)
    own = mine[-1] if mine else None
    # D-380 (ROLE-008): the bootstrap is closed. Only the PI the log names is PI; with no PI named, nobody is.
    is_pi = log_account(user) and pi is not None and pi.username == user.username
    ticked = frozenset(t for e in mine if e.role == "sub_pi" for t in e.tasks)
    held = Grant(is_pi=is_pi, tasks=ticked, log_names_pi=pi is not None)  # the log as the ``task.*`` rows read it
    tasks = frozenset(t for t in STUDY_TASKS if permit(user.role, f"task.{t}", held))
    return Standing(is_pi, tasks, pi is not None, pi if is_pi else own)


def check_due(team: TeamStore, rs: str, today: date, tz: ZoneInfo) -> bool:
    """The monthly comparison with the office's signed log is due (or was never made) for a study with a log.

    ``today`` is the site's date; a check's stored time is a UTC instant, so it is read on the site's calendar too
    (D-270: a check at 08:00 in Tokyo is the day before in UTC)."""
    if not team.entries(rs):
        return False
    checks = team.checks(rs)
    return not checks or local_date(checks[0].at, tz) < (today - timedelta(days=CHECK_DAYS)).isoformat()


GATE_ENVS = ("VALIDATION", "PRODUCTION")  # where the IRB-text gate is on by default and cannot be turned off


def irb_text_gate(env: Mapping[str, str]) -> bool:
    """D-395: is the candidate view held until the study's IRB text covers the sentence? ``TB_IRB_TEXT_GATE`` is
    ``auto`` (on in VALIDATION and PRODUCTION, off in DEV and TEST, where only synthetic data is read), ``on`` or
    ``off``; ``off`` is refused in VALIDATION and PRODUCTION (ValueError)."""
    mode = (env.get("TB_IRB_TEXT_GATE") or "auto").strip().lower()
    if mode not in ("auto", "on", "off"):
        raise ValueError(f"TB_IRB_TEXT_GATE must be auto, on or off, got {mode!r}")
    name = environment_name(env)
    if mode == "off" and name in GATE_ENVS:
        raise ValueError(f"TB_IRB_TEXT_GATE=off is refused in {name}")
    return name in GATE_ENVS if mode == "auto" else mode == "on"


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
    reason: str = Field(default="", max_length=300)  # D-380 (ROLE-015): why a saved record changes


class ApiIcf(BaseModel):
    """D-399: one approved consent-form version (``withdraw`` with a ``note`` takes it off the list)."""

    version: str = Field(default="", max_length=40)
    version_date: str = ""
    irb_approved_on: str = ""
    effective_from: str = ""
    reconsent: bool = True
    note: str = Field(default="", max_length=200)
    withdraw: bool = False


class ApiOptOut(BaseModel):
    pid: str = ""
    chart_no: str = ""
    source: str = "office"
    note: str = Field(default="", max_length=300)
    lift: bool = False
    unknown_reason: str = Field(default="", max_length=300)  # NEW-DIN-3: why a number the box does not know is kept


def register(app: FastAPI, h: Helpers, env: Mapping[str, str]) -> None:
    bk, au, store = h.bk, h.au, h.store
    team = TeamStore()  # schema team of the trial database (TB_DB_URL, D-126)
    optout = OptOutRegister()  # schema optout, read by the orchestrator too
    h.team, h.optout = team, optout
    h.irb_gate = irb_text_gate(env)  # D-395
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
        return h.permit(user, f"task.{task}", rid).allowed

    def may_approve(user: User, rid: str) -> bool:
        """FR-AUTH-13 and D-147: only the PI the study's log names approves (D-380: no PI named, nobody)."""
        return user.can_approve and stand(user, rid).pi

    h.may_approve, h.stand = may_approve, stand  # T-512, T-102c: h.permit and h.may_run read the standing

    def monitor_grants(user: User) -> list[tuple[str, str, str]]:
        """NEW-JRN-8 (D-772): the studies a CRO account reads today under a monitor grant, with the visit id and the
        grant's last day, so the reports page and the menu link the monitoring page (it was a typed address)."""
        if not monitor_account(user):
            return []
        out = []
        for r in bk.rulesets():
            if user.sees_study(r.id) and h.permit(user, "monitor.read", r.id).allowed:  # any kind: the grant decides
                g = stand(user, r.id).monitor
                if g is not None:
                    out.append((r.id, g.training_ref or "", g.end or ""))
        return out

    h.monitor_grants = monitor_grants

    def pi_missing(user: User) -> list[str]:
        """NEW-JRN-1 (D-540): the studies this account sees whose criteria wait for approval while the delegation
        log names no PI: nobody can approve them until the steward names one (D-380)."""
        try:
            waiting = st.waiting_studies(bk)
        except Exception:  # the orchestrator is down: no task shown, the pages say so themselves
            return []
        return [rid for rid in waiting if user.sees_study(rid) and not names_pi(rid)]

    def names_pi(rid: str) -> bool:
        """The log names a PI who can act: an entry with an account (an entry without one approves nothing)."""
        pi = team.pi_of(rid, today())
        return pi is not None and bool(pi.username)

    def log_or_404(sess: Session, rs: str) -> str:
        """The delegation log's own door (D-540): a known study, or one whose first criteria wait for approval."""
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not st.log_study(bk, rid):
            if _RS.match(rid):
                au.append("console.denied", actor=h.actor(sess), detail={"action": f"study {rid}"})
            raise h.problem(404, "notfound")
        return rid

    h.pi_missing = pi_missing
    h.team_due = lambda rid: check_due(team, rid, today(), site_zone(bk))

    def deny(sess: Session, path: str) -> Exception:
        au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
        return h.problem(403, "forbidden")

    def study_seen(user: User, rid: str) -> bool:
        """The account sees study ``rid`` and the box knows it (the question of :func:`study_or_404`)."""
        return bool(_RS.match(rid)) and user.sees_study(rid) and known_study(bk, rid)

    def study_or_404(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not study_seen(sess.user, rid):
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

    def admits_candidates(user: User, rs: str) -> bool:
        """D-1245: would the study's candidate list (``GET /studies/{rs}/candidates``) admit this account? The list's
        own two questions (:func:`study_seen`, then the ``screen`` task of :func:`need_task`), asked without a
        refusal or its audit event, for a page that shows a figure only to those the list admits."""
        rid = (rs or "").strip().upper()
        return study_seen(user, rid) and "screen" in stand(user, rid).tasks

    h.admits_candidates = admits_candidates

    def view_open(rid: str) -> bool:
        """D-395: the candidate view of this study may open (the gate is off here, or the IRB text covers it)."""
        return not h.irb_gate or store.irb_text(rid).enables

    def need_irb_text(sess: Session, rid: str, path: str) -> None:
        """D-395 (RSK-42): no candidate page and no chart number from it until the study's PI has recorded that the
        approved IRB text covers the cross-department identified view. Refused with the reason, and audited."""
        if not view_open(rid):
            au.append("console.denied", ruleset=rid, actor=h.actor(sess),
                      detail={"action": path[:80], "reason": "irb_text"})  # fmt: skip
            raise h.problem(403, "irbt.refused", rs=rid)

    # ------------------------------------------------------------------ candidates
    def candidate_rows(sess: Session, rid: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        wk = h.week_bundle(sess, rid) if h.week_bundle else None
        if wk is None:
            return None, []
        names = (wk["summary"] or {}).get("practitioner_names") or {}
        reg = h.registry_map(rid) if h.registry_map else {}
        # MVP-B: the bundle's own criteria with its kept fits (one read of the criteria a view)
        crit = wk["crit"]
        rows = st.weekly_rows(wk["cl"], crit, reg, store.latest_marks(rid), {}, wk["job"].job_id, names,
                              include_closed=True, today=today(), fits=wk["fits"])  # fmt: skip
        refs = team.latest_referrals(rid)
        staff = {s.practitioner_id: s for s in team.staff() if s.practitioner_id}
        nos = store.screening_nos(rid)
        for r in rows:
            r["referral"] = refs.get(r["pid"])
            r["doctor"] = suggestion(r, names, staff)
            r["n_open"] = st.n_open(r)
            r["closeness"] = st.closeness_key(r, crit)
            r["coded"] = st.coded_complete(r, crit)
            r["screening_no"] = nos.get(r["pid"])
            r["person"] = wk["people"].of(r["pid"])  # D-1221: the same state as on every other list
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
    h.pid_match_per_hour = lookups_per_hour  # NEW-JRN-2: the match note shares the lookups' limit

    def candidate_ctx(sess: Session, rid: str, pid: str) -> dict[str, Any]:
        if not _PID.match(pid) or h.patient_ctx is None:
            raise h.problem(404, "notfound")
        wk = h.week_bundle(sess, rid) if h.week_bundle else None
        ctx = h.patient_ctx(sess, rid, pid, wk)
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
        need_irb_text(sess, rid, path)
        if purpose not in VIEW_PURPOSES:
            raise h.problem(400, "candidate.purpose")
        ctx = candidate_ctx(sess, rid, pid)
        rate(sess, rid, pid, purpose)
        au.append("console.candidate_view", job_id=ctx["job"].job_id, ruleset=rid, actor=h.actor(sess),
                  detail={"pid": pid, "purpose": purpose, "role": sess.user.role,
                          "pi": ctx["standing"].pi})  # fmt: skip
        ctx["purpose"] = purpose
        return rid, ctx

    @app.get("/studies/{rs}/candidates")
    def candidates(request: Request, rs: str, page: int = 1, show: str = "", order: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        need_task(sess, rid, "screen", request.url.path)
        wk, rows = candidate_rows(sess, rid)
        order = "closest" if order == "closest" else ""  # the one other order (MATCH-ARCH 1(e)); else the next visit
        if order:
            rows = sorted(rows, key=lambda r: r["closeness"])
        if show == "unknown":
            rows = [r for r in rows if not r["doctor"]["known"]]
        elif show == "open":
            rows = [r for r in rows if r["referral"] is not None and r["referral"].open]
        n_all = len(rows)
        shown, page_no, pages = st.paged(rows, page)
        removed = len((wk or {}).get("removed") or ())  # only the count: who opted out is itself private
        return h.page(request, "team_candidates.html", sess, rs=rid, wk=wk, rows=shown, n_all=n_all, page_no=page_no,
                      pages=pages, show=show, order=order, removed=removed, standing=stand(sess.user, rid),
                      purposes=VIEW_PURPOSES, view_open=view_open(rid))  # fmt: skip

    @app.get("/studies/{rs}/candidates/{pid}")
    def candidate(request: Request, rs: str, pid: str, purpose: str = "") -> Response:
        sess = h.need(request)
        if purpose not in VIEW_PURPOSES:  # nothing patient-level before the purpose is given
            rid = study_or_404(sess, rs)
            need_task(sess, rid, "screen", request.url.path)
            need_irb_text(sess, rid, request.url.path)
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
        rid = study_or_404(sess, rs)
        need_irb_text(sess, rid, request.url.path)
        purpose = str(form.get("purpose") or "")
        if purpose not in VIEW_PURPOSES:
            raise h.problem(400, "candidate.purpose")
        got = h.reveal.identifier(sess, rid, pid, purpose, str(form.get("reason") or ""), via="candidates",
                                  note=str(form.get("note") or "")[:200], path=request.url.path)  # fmt: skip
        return h.page(request, "team_candidate.html", sess,
                      **{**candidate_ctx(sess, rid, pid), "mrn": got.mrn, "purpose": purpose})  # fmt: skip

    # ------------------------------------------------------------------ referral
    def request_referral(sess: Session, path: str, rs: str, pid: str, body: ApiReferral) -> tuple[str, int, str]:
        rid = study_or_404(sess, rs)
        need_task(sess, rid, "refer", path)
        if not _PID.match(pid) or h.patient_ctx is None:
            raise h.problem(404, "notfound")
        wk = h.week_bundle(sess, rid) if h.week_bundle else None
        ctx = h.patient_ctx(sess, rid, pid, wk)  # 404 unless the study's run lists the patient (opt-outs never)
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
        # T-516 (UX-013): asked after Approach, the referral pauses it (no call task, no contact outcome) until the
        # treating doctor agrees; the audit record says so
        paused = getattr(ctx.get("mark"), "mark", "") == "approach"
        au.append("console.referral", job_id=ctx["job"].job_id, ruleset=rid, actor=h.actor(sess),
                  detail={"pid": pid, "action": "requested", "route": route, "known": bool(physician),
                          "suggested": sug["known"], "changed": route != "suggested" and sug["known"],
                          "run": no or "", "id": ref_id, **({"paused": "approach"} if paused else {})})  # fmt: skip
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
        rid = study_or_404(sess, rs)
        if str(form.get("confirm") or "") != "yes" and h.confirm is not None and _PID.match(pid):
            mk = store.latest_marks(rid).get(pid)
            if mk is not None and mk.mark == "approach" and may(sess.user, rid, "refer"):
                # T-516 (UX-013): the consequence first: Approach is paused until the doctor answers
                fields = {k: str(form.get(k) or "") for k in ("route", "staff_id", "name", "department", "note")}
                return h.confirm(request, sess, translate(sess.lang, "confirm.referral.pause"), request.url.path,
                                 fields, f"/studies/{rid}/patients/{pid}")  # fmt: skip
        rid, ref_id, _ = request_referral(sess, request.url.path, rs, pid, body)
        return RedirectResponse(f"/studies/{rid}/referrals?done=requested#r{ref_id}", status_code=303)

    def answer_referral(sess: Session, path: str, rs: str, ref_id: int, body: ApiAnswer) -> tuple[str, Any]:
        """The doctor's answer, recorded by the CRC (who asked by phone, in person or by EMR message) or, for a
        referral arranged outside TrialBox, by the PI or sub-PI who asked."""
        rid = study_or_404(sess, rs)
        if not h.permit(sess.user, "referral.answer", rid):
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

    # ------------------------------------------------------------------ the request for the doctor (D-407, UX-034)
    def doctor_request(sess: Session, rid: str, ref: Referral, lang: str, mrn: str = "") -> list[str]:
        """What the CRC hands or sends to the treating doctor, who has no account (LIFE-017, UX-034): the study, the
        patient's code and screening number, the inclusion criteria the records meet (labels and counts, never a
        note's words), what is asked, and the study contact. The chart number only after a recorded reveal
        (``mrn``); otherwise a line the study team fills in by hand. Plain lines in ``lang``, for the copy text and
        the one-page print alike."""
        lang = lang if lang in DOCTOR_LANGS else "en"
        fit = None
        if h.patient_ctx is not None:
            try:
                fit = h.patient_ctx(sess, rid, ref.pid).get("fit")
            except Exception:  # the patient is not on the latest list any more: the request names no criteria
                fit = None
        no = store.screening_nos(rid).get(ref.pid) or ""
        crc = next((m for m in team.staff() if m.username and m.username == ref.requested_by), None)
        who = (crc.name if crc else "") or ref.requested_by.removeprefix("console:")
        lines = [translate(lang, "ref.doc.heading", study=rid)]
        if ref.physician or ref.department:
            lines.append(translate(lang, "ref.doc.to", doctor=ref.physician or "–", dept=ref.department or "–"))
        lines.append(translate(lang, "ref.doc.patient", code=ref.pid[:8], no=no or "–"))
        lines.append(translate(lang, "ref.doc.chart_shown", mrn=mrn) if mrn else translate(lang, "ref.doc.chart"))
        if fit is not None and fit.inc_total:
            lines.append(translate(lang, "ref.doc.criteria", met=fit.inc_met, total=fit.inc_total))
            lines += [f"- {k['label']}" for k in fit.key[:12]]
        lines.append(translate(lang, "ref.doc.ask", study=rid))
        lines.append(translate(lang, "ref.doc.contact", name=who, contact=(crc.contact if crc else "") or "–"))
        lines.append(translate(lang, "ref.doc.note"))
        return lines

    def ref_or_404(sess: Session, path: str, rs: str, ref_id: int) -> tuple[str, Referral]:
        rid = study_or_404(sess, rs)
        if "screen" not in stand(sess.user, rid).tasks:
            raise deny(sess, path)
        ref = team.referral(rid, ref_id)
        if ref is None or ref.pid in optout.effective():
            raise h.problem(404, "notfound")
        return rid, ref

    def print_page(request: Request, sess: Session, rid: str, ref: Referral, lang: str, mrn: str = "") -> Response:
        lang = lang if lang in DOCTOR_LANGS else (sess.lang if sess.lang in DOCTOR_LANGS else "en")
        au.append("console.referral", ruleset=rid, actor=h.actor(sess),
                  detail={"pid": ref.pid, "action": "printed", "id": ref.id, "lang": lang,
                          "chart_no": bool(mrn)})  # fmt: skip
        may_reveal = "screen" in stand(sess.user, rid).tasks and sess.user.sees_ids(rid)
        return h.page(request, "team_referral_print.html", sess, rs=rid, ref=ref, doc_lang=lang, langs=DOCTOR_LANGS,
                      lines=doctor_request(sess, rid, ref, lang, mrn), mrn=mrn, may_reveal=may_reveal,
                      reveal_reasons=REVEAL_REASONS)  # fmt: skip

    @app.get("/studies/{rs}/referrals/{ref_id}/print")
    def referral_print(request: Request, rs: str, ref_id: int, lang: str = "") -> Response:
        """A one-page print of the request for the treating doctor, in the doctor's language (UX-034)."""
        sess = h.need(request)
        rid, ref = ref_or_404(sess, request.url.path, rs, ref_id)
        return print_page(request, sess, rid, ref, lang)

    @app.post("/studies/{rs}/referrals/{ref_id}/print")
    async def referral_print_reveal(request: Request, rs: str, ref_id: int) -> Response:
        """The same page with the chart number, through the one reveal path (a reason, the audit record on both
        sides and the per-person cap, whose use row is the referral's candidate-view record; T-103, D-438)."""
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        h.reveal.guard(sess, rs.strip().upper(), request.url.path, "referral", str(form.get("reason") or ""),
                       "referral")  # fmt: skip
        rid, ref = ref_or_404(sess, request.url.path, rs, ref_id)
        need_irb_text(sess, rid, request.url.path)
        got = h.reveal.identifier(sess, rid, ref.pid, "referral", str(form.get("reason") or ""), via="referral",
                                  note=str(form.get("note") or "")[:200], path=request.url.path)  # fmt: skip
        return print_page(request, sess, rid, ref, str(form.get("lang") or ""), got.mrn)

    @app.get("/studies/{rs}/referrals")
    def referrals(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        s = stand(sess.user, rid)
        if "screen" not in s.tasks:
            raise deny(sess, request.url.path)
        on = optout.effective()
        refs = [r for r in team.referrals(rid) if r.pid not in on]
        latest = team.latest_referrals(rid)
        open_refs = [r for r in refs if r.open and latest[r.pid].id == r.id]
        counts: dict[str, int] = {}
        for r in refs:
            counts[f"route.{r.route}"] = counts.get(f"route.{r.route}", 0) + 1
            counts[f"state.{r.state}"] = counts.get(f"state.{r.state}", 0) + 1
        nos = store.screening_nos(rid)
        may_answer = permit(sess.user.role, "referral.answer", s.grant()).allowed
        lang = sess.lang if sess.lang in DOCTOR_LANGS else "en"
        asks = {r.id: "\n".join(doctor_request(sess, rid, r, lang)) for r in open_refs}  # UX-034: the copy text
        return h.page(request, "team_referrals.html", sess, rs=rid, refs=list(reversed(refs)), open_refs=open_refs,
                      counts=counts, nos=nos, routes=ROUTES, answers=ANSWERS, channels=CHANNELS,
                      reasons=DECLINE_REASONS, may_answer=may_answer, contacts=team.contacts(), asks=asks,
                      doc_langs=DOCTOR_LANGS)  # fmt: skip

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
        """Accounts a log entry may name: investigators and coordinators of the study, and CRO accounts of the study
        for a monitor grant (FIT-002)."""
        return [u for u in h.users.users() if on_log(u) and u.sees_study(rid)]

    def log_roles_for(sess: Session, s: Standing) -> tuple[str, ...]:
        """The log roles this account may write (D-380): the logged PI every role; the steward the PI entry (study
        set-up, from the signed log) and monitor grants; nobody else any."""
        g = s.grant()
        out = set(LOG_ROLES) if permit(sess.user.role, "delegation.keep", g) else set()
        if permit(sess.user.role, "delegation.name_pi", g):
            out.add("pi")
        if permit(sess.user.role, "monitor.grant", g):
            out.add("monitor")
        return tuple(r for r in LOG_ROLES if r in out)

    @app.get("/studies/{rs}/team")
    def team_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = log_or_404(sess, rs)
        if sess.user.aggregate_only:
            raise deny(sess, request.url.path)
        s = stand(sess.user, rid)
        entries = team.entries(rid)
        writable = log_roles_for(sess, s)
        ending = [(e, e.days_left(today())) for e in entries if e.days_left(today()) is not None]  # 9f-4 (a)
        return h.page(request, "team_log.html", sess, rs=rid, entries=entries, standing=s, tasks=TASKS, ending=ending,
                      log_roles=writable, accounts=accounts(rid), checks=team.checks(rid)[:12],
                      due=check_due(team, rid, today(), site_zone(bk)), history=team.history(rid)[-30:], today=today(),
                      can_edit=bool(writable), can_tick=permit(sess.user.role, "delegation.keep", s.grant()).allowed,
                      can_check=permit(sess.user.role, "delegation.check", s.grant()).allowed,
                      results=CHECK_RESULTS, has_pi=names_pi(rid))  # fmt: skip

    @app.post("/studies/{rs}/team")
    async def team_add(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        rid = log_or_404(sess, rs)
        s = stand(sess.user, rid)
        role = str(form.get("role") or "")
        writable = log_roles_for(sess, s)
        if not writable:  # D-380 (ROLE-008): no PI named, no investigator writes the log
            raise deny(sess, request.url.path)
        if role in LOG_ROLES and role not in writable:
            raise deny(sess, request.url.path)
        username = str(form.get("username") or "").strip().lower() or None
        acct = next((u for u in accounts(rid) if u.username == username), None) if username else None
        if username and acct is None:
            raise refused(TeamError("no such account for this study"))
        if role in ("pi", "sub_pi") and acct is not None and not log_account(acct):
            raise refused(TeamError("a sub-investigator signs in with an investigator account"))
        if role != "monitor" and acct is not None and monitor_account(acct):
            raise refused(TeamError("a CRO account is on the log only as a monitor"))
        if role == "monitor" and (acct is None or not monitor_account(acct)):
            raise refused(TeamError("a monitor grant names a CRO account of this study"))
        # DEMO-JA: the visit id has its own field ("visit"; the training-certificate field is still read for it)
        ref = str(form.get("visit") or "").strip() if role == "monitor" else ""
        ref = ref or str(form.get("training_ref") or "").strip()
        if role == "monitor":
            missing = [w for w, ok in (("the last day", str(form.get("end") or "").strip()), ("the visit id", ref))
                       if not ok]  # fmt: skip
            if missing:  # say which field is empty (the rehearsal's refusal named none)
                raise refused(TeamError(f"a monitor grant needs {' and '.join(missing)} of the monitoring visit"))
        tasks = [] if role == "monitor" else form.getlist("tasks")
        try:
            eid = team.add_entry(rid, username=username, name=str(form.get("name") or "").strip() or (username or ""),
                                 role=role, tasks=tasks, start=str(form.get("start") or ""),
                                 end=str(form.get("end") or ""), training_day=str(form.get("training_day") or ""),
                                 training_ref=ref, by=sess.user.username,
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
        if not permit(sess.user.role, "delegation.check", s.grant()):
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
        if not permit(sess.user.role, "delegation.keep", s.grant()):
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
        """D-380 (ROLE-015): the matrix's ``irb.edit`` (a coordinator, the logged PI) and hospital staff only: an SMO
        or CRO account and the administrator never set the dates that silence the IRB warning."""
        if sess.user.affiliation != "hospital":
            return False
        return permit(sess.user.role, "irb.edit", stand(sess.user, rid).grant()).allowed

    def save_irb(sess: Session, path: str, rs: str, body: ApiIrb) -> tuple[str, Irb]:
        """D-380 (ROLE-015): an approval date needs its approval number; a change to a saved record needs a written
        reason; the API body is the whole record (a field left out is cleared, never kept silently); the audit event
        holds the old and the new values."""
        rid = study_or_404(sess, rs)
        if not may_edit_irb(sess, rid):
            raise deny(sess, path)
        before = team.irb(rid)
        new = Irb(body.approval_no, body.approved_on, body.expires_on, body.icf_version, body.icf_date)
        if new.approved_on.strip() and not new.approval_no.strip():
            raise refused(TeamError("give the IRB approval number with the approval date"))
        fields = IRB_FIELDS
        changed = [k for k in fields if str(getattr(before, k) or "") != str(getattr(new, k) or "").strip()]
        reason = body.reason.strip()
        if before.at and changed and len(reason) < IRB_REASON_MIN:
            raise refused(TeamError(f"say why the IRB record changes (at least {IRB_REASON_MIN} characters)"))
        try:
            rec = team.save_irb(rid, new, sess.user.username, now())
        except TeamError as exc:
            raise refused(exc) from exc
        au.append("console.irb", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "save", "approved_on": rec.approved_on, "expires_on": rec.expires_on,
                          "icf_version": rec.icf_version, "approval_no": rec.approval_no,
                          "changed": ",".join(changed), "reason": reason[:300],
                          "before": {k: str(getattr(before, k) or "") for k in fields}})  # fmt: skip
        return rid, rec

    @app.get("/studies/{rs}/irb")
    def irb_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if sess.user.aggregate_only:
            raise deny(sess, request.url.path)
        rec = team.irb(rid)
        on = optout.effective()
        # D-380: the overrides name patients (pseudonyms): only a patient-level reader sees them, never the admin
        overrides = [o for o in team.overrides(rid) if o[0] not in on][-50:] if sess.user.can_view_phi else []
        return h.page(request, "team_irb.html", sess, rs=rid, irb=rec, warnings=rec.warnings(today()),
                      can_edit=may_edit_irb(sess, rid), icf=team.icf_list(rid), icf_history=team.icf_history(rid),
                      reads_subjects=sess.user.can_view_phi, overrides=overrides,
                      committee=h.committee_status(rid) if h.committee_status else None)  # fmt: skip

    @app.post("/studies/{rs}/irb")
    async def irb_save(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        body = ApiIrb(**{k: str(form.get(k) or "")[: 300 if k == "reason" else 60] for k in ApiIrb.model_fields})
        rid, _ = save_irb(sess, request.url.path, rs, body)
        return RedirectResponse(f"/studies/{rid}/irb?done=1", status_code=303)

    # the monitor's pages (reads under a monitor grant, the visit record) are ``console.sdv_page`` (D-436)

    # ------------------------------------------------------------------ approved ICF versions, re-consent (D-399)
    def icf_json(v: IcfVersion) -> dict[str, Any]:
        return {"version": v.version, "version_date": v.version_date or None,
                "irb_approved_on": v.irb_approved_on or None, "effective_from": v.effective_from or None,
                "reconsent": v.reconsent, "action": v.action, "note": v.note or None, "by": v.by,
                "at": v.at}  # fmt: skip

    def save_icf(sess: Session, path: str, rs: str, body: ApiIcf) -> tuple[str, list[IcfVersion]]:
        """Add or change a version of the study's ICF list, or take one off it; who may edit the IRB record may."""
        rid = study_or_404(sess, rs)
        if not may_edit_irb(sess, rid):
            raise deny(sess, path)
        try:
            if body.withdraw:
                team.withdraw_icf(rid, body.version, body.note, sess.user.username, now())
            else:
                team.add_icf(rid, IcfVersion(body.version, body.version_date, body.irb_approved_on,
                                             body.effective_from, body.reconsent, body.note), sess.user.username,
                             now())  # fmt: skip
        except TeamError as exc:
            raise refused(exc) from exc
        au.append("console.icf", ruleset=rid, actor=h.actor(sess),
                  detail={"action": "withdraw" if body.withdraw else "add", "version": body.version.strip()[:40],
                          "irb_approved_on": body.irb_approved_on[:10], "effective_from": body.effective_from[:10],
                          "reconsent": body.reconsent})  # fmt: skip
        return rid, team.icf_list(rid)

    def reconsent_access(sess: Session, path: str, rs: str) -> str:
        """Record level: who reads the participants (``lifecycle_pages``) reads the re-consent list."""
        rid = study_or_404(sess, rs)
        if not sess.user.can_view_phi:
            raise deny(sess, path)
        h.delegated(sess, rid, f"participants {rid}", ("screen", "enter_data"))
        return rid

    def reconsent_list(rid: str) -> dict[str, Any]:
        """LIFE-018: the subjects on study still on an older consent-form version than the newest in force that asks
        for re-consent, with their screening numbers; opted-out patients are left out."""
        day = today()
        out = s28.call(bk, "GET", f"/studies/{rid}/subjects?today={day.isoformat()}")
        on = optout.effective()
        subs = [x for x in out.get("subjects") or [] if str(x.get("pid") or "") not in on]
        due = reconsent_due(subs, [v.as_row() for v in team.icf_list(rid)], day)
        nos = store.screening_nos(rid)
        for r in due["rows"]:
            r["screening_no"] = nos.get(str(r["pid"])) or ""
        return due

    @app.post("/studies/{rs}/irb/icf")
    async def icf_save(request: Request, rs: str) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        body = ApiIcf(version=str(form.get("version") or "")[:40],
                      version_date=str(form.get("version_date") or "")[:10],
                      irb_approved_on=str(form.get("irb_approved_on") or "")[:10],
                      effective_from=str(form.get("effective_from") or "")[:10],
                      reconsent=str(form.get("reconsent") or "") == "1", note=str(form.get("note") or "")[:200],
                      withdraw=str(form.get("withdraw") or "") == "1")  # fmt: skip
        rid, _ = save_icf(sess, request.url.path, rs, body)
        return RedirectResponse(f"/studies/{rid}/irb?icf=1#icf", status_code=303)

    @app.get("/studies/{rs}/reconsent")
    def reconsent_page(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = reconsent_access(sess, request.url.path, rs)
        err = None
        due: dict[str, Any] = {"target": None, "rows": []}
        try:
            due = reconsent_list(rid)
        except (Problem, Unavailable) as exc:
            err = err_of(exc)
        enters = h.permit(sess.user, "task.enter_data", rid).allowed
        return h.page(request, "team_reconsent.html", sess, rs=rid, due=due, err=err, editable=enters)

    # T-657 (D-444): the actions' own first checks, run before the body is read (console.api_first)
    def first_refer(sess: Session, request: Request) -> None:
        need_task(sess, study_or_404(sess, request.path_params["rs"]), "refer", request.url.path)

    def first_answer(sess: Session, request: Request) -> None:
        rid = study_or_404(sess, request.path_params["rs"])
        if not h.permit(sess.user, "referral.answer", rid):
            raise deny(sess, request.url.path)

    def first_irb(sess: Session, request: Request) -> None:
        rid = study_or_404(sess, request.path_params["rs"])
        if not may_edit_irb(sess, rid):
            raise deny(sess, request.url.path)

    def first_optout(sess: Session, request: Request) -> None:
        if not can_keep_optouts(sess.user):
            raise deny(sess, request.url.path)

    @app.get("/api/v1/studies/{rs}/icf")
    def api_icf(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = study_or_404(sess, rs)
        if sess.user.aggregate_only:
            raise deny(sess, request.url.path)
        return {"study": rid, "versions": [icf_json(v) for v in team.icf_list(rid)],
                "history": [icf_json(v) for v in team.icf_history(rid)]}  # fmt: skip

    @app.post("/api/v1/studies/{rs}/icf")
    @before_body(first_irb)
    @page_twin("/studies/{rs}/irb/icf")
    def api_icf_save(request: Request, rs: str, body: ApiIcf) -> dict[str, Any]:
        sess = api(request)
        rid, rows = save_icf(sess, request.url.path, rs, body)
        return {"study": rid, "versions": [icf_json(v) for v in rows]}

    @app.get("/api/v1/studies/{rs}/reconsent")
    def api_reconsent(request: Request, rs: str) -> dict[str, Any]:
        sess = api(request)
        rid = reconsent_access(sess, request.url.path, rs)
        due = reconsent_list(rid)  # a data core that does not answer is the console's 503 (Unavailable)
        target = due["target"]
        return {"study": rid, "version": target["version"] if target else None,
                "since": (target["effective_from"] or None) if target else None,
                "subjects": [{"record": r["record"], "pid": r["pid"], "screening_no": r["screening_no"] or None,
                              "state": r["state"], "version": r["version"] or None, "consented_on": r["day"],
                              "listed": r["listed"], "next_event": r["next_rc"]} for r in due["rows"]]}  # fmt: skip

    # ------------------------------------------------------------------ staff directory (kept by the steward)
    def can_keep(user: User) -> bool:
        """The staff directory and department contacts: the matrix's ``staff.keep`` (D-380: the steward and the
        privacy office only). No patient data on these lists."""
        return permit(user.role, "staff.keep").allowed

    def can_keep_optouts(user: User) -> bool:
        """The opt-out register (patient level: pseudonyms, a chart-number lookup): the matrix's ``optout.keep``.
        D-380 (ROLE-005): the steward and the privacy office only; never a coordinator (an SMO one least of all) and
        never the administrator."""
        return permit(user.role, "optout.keep").allowed

    @app.get("/site/staff")
    def staff_page(request: Request) -> Response:
        sess = h.need(request)
        if not (sess.user.can_view_phi or can_keep(sess.user)):
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
    def to_pid(sess: Session, chart_no: str, pid: str, lift: bool = False) -> tuple[str, bool | None]:
        """The pseudonym, and for a chart number whether the box holds a patient under it (NEW-DIN-3, D-544): True
        only when the box says so; False when it says no; None when it cannot say or does not answer the question
        (and for a typed pseudonym, which is not asked)."""
        pid = pid.strip()
        if pid:
            # NEW-JRN-2 (D-542): the whole pseudonym or nothing. Every screen shows a patient by the first eight
            # characters; an opt-out stored for those names nobody and removes nobody. The one exception is taking
            # back a row that is on the register as it was typed (made before this rule).
            if lift and _PID.match(pid) and any(e.pid == pid for e in optout.current()):
                return pid, None  # the row's own text, as it is on the register
            whole = pid.lower()
            if _WHOLE_PID.match(whole):
                return whole, None
            raise refused(OptOutError(WHOLE_PID_WHY))
        # NEW-DIN-3d (D-548): full-width characters and the blanks around are written half-width first, as every
        # path to a pseudonym writes them (the box applies the site's rule after that); the shape is asked of that
        chart = chartno.normalise("asis", chart_no)
        if not chart:
            raise refused(TeamError("give a chart number or a pseudonym"))
        if not _CHART.match(chart):
            raise refused(TeamError("chart numbers are letters, digits or '-'"))
        if _WHOLE_PID.match(chart.lower()):  # hashed again it would name nobody (review of NEW-JRN-2)
            raise refused(OptOutError("this is a pseudonym, not a chart number: put it in the pseudonym field"))
        try:  # the box turns the chart number into the pseudonym at the door; the number is never stored
            # T-719 (D-487): as the signed-in keeper of the register; the box refuses the console's token alone.
            # NEW-DIN-3 (D-544): and the box is asked whether it knows the pseudonym
            out = acting.call(h, sess, "optout.keep", None, "POST", "/setup/pseudonym",
                              {"chart_no": chart, "ask_known": True})  # fmt: skip
        except (Problem, Unavailable) as exc:
            raise h.problem(409, "request.refused",
                            reason="the box could not turn the chart number into a pseudonym") from exc  # fmt: skip
        got = str((out or {}).get("pid") or "")
        if not _PID.match(got):
            raise h.problem(409, "request.refused", reason="the box could not turn the chart number into a pseudonym")
        known = (out or {}).get("known")
        return got, known if isinstance(known, bool) else None

    def chart_to_pid(sess: Session, chart_no: str, purpose: str) -> tuple[str, bool | None]:
        """NEW-JRN-6 (D-771): a chart number turned into its pseudonym at the door, for another reader than the
        opt-out register (the privacy office's disclosure report): the same cap per person and hour (D-273 PV-6),
        its own ``console.chart_lookup`` event with ``for``; the number is never stored, the caller never shows the
        pseudonym. Returns the pseudonym and whether the box holds a patient under the number (D-544)."""
        chart_lookup(sess, purpose)
        pid, known = to_pid(sess, chart_no, "")
        au.append("console.chart_lookup", actor=h.actor(sess),
                  detail={"pid": pid, "for": purpose, "role": sess.user.role, "known": KNOWN_WORD[known]})  # fmt: skip
        return pid, known

    h.chart_to_pid = chart_to_pid

    def on_lists(pid: str) -> bool | None:
        """NEW-JRN-2 (D-542): is this pseudonym on a registry or a current list of any study of this box? Read
        before the opt-out removes it. None when any study could not be read: then nothing is said."""
        try:
            studies = [r.id for r in bk.rulesets()]
        except Exception:
            return None
        whole = True
        for rs in studies:
            try:
                rows = {e.pid for e in bk.registry_rows(rs)}
                wk = h.week_bundle(None, rs) if h.week_bundle is not None else None
                rows |= {str(r.get("pid")) for r in ((wk or {}).get("cl") or {}).get("rows") or []}
            except Exception as exc:  # the opt-out stands; the note is left out
                log.warning("opt-out match: a study could not be read", extra={"error": type(exc).__name__})
                whole = False
                continue
            if pid in rows:
                return True
        return False if whole else None

    def change_optout(sess: Session, path: str, body: ApiOptOut, match: str = "") -> tuple[str, bool]:
        """One opt-out or lift. D-273 (PV-6): a chart number typed at the door is a lookup of a patient's
        pseudonym, so it is capped per person and hour and audited as its own event, changed or not, and neither
        the page nor ``/api/v1`` gives the pseudonym back. D-273 (CR-055): the change's audit event is written inside
        the register's transaction, so a failed append keeps no opt-out without its event."""
        if not can_keep_optouts(sess.user):
            raise deny(sess, path)
        if body.lift and len(body.note.strip()) < LIFT_REASON_MIN:  # D-380 (ROLE-005): a lift says why
            raise refused(OptOutError(f"say why the opt-out is lifted (at least {LIFT_REASON_MIN} characters)"))
        by_chart = bool(body.chart_no.strip()) and not body.pid.strip()
        if by_chart:
            chart_lookup(sess, "optout")
        pid, known = to_pid(sess, body.chart_no, body.pid, body.lift)
        why_unknown = ""
        if by_chart:
            au.append(
                "console.chart_lookup",
                actor=h.actor(sess),
                detail={"pid": pid, "for": "lift" if body.lift else "opt_out", "role": sess.user.role,
                        "known": KNOWN_WORD[known]},
            )  # fmt: skip
            # NEW-DIN-3 (D-544): a number that is not a patient of this box (a slip of the hand, another hospital's
            # number) is not registered as one; the keeper may still register it, saying why. A lift is not asked:
            # what is on the register can always be taken off.
            if known is not True and not body.lift:
                why_unknown = " ".join(body.unknown_reason.split())[:300]
                if len(why_unknown) < UNKNOWN_REASON_MIN:
                    raise refused(OptOutError(NOT_A_PATIENT if known is False else CANNOT_CHECK))
        detail = {"pid": pid, "action": "lift" if body.lift else "opt_out",
                  "reason": body.note.strip()[:300] if body.lift else "",
                  "source": "" if body.lift else (body.source if body.source in SOURCES else "other"),
                  "removed_from": "" if body.lift else "screening, candidate lists, exports"}  # fmt: skip
        if by_chart and not body.lift:
            detail["known"] = KNOWN_WORD[known]
            if why_unknown:
                detail["unknown_reason"] = why_unknown
        if match:  # NEW-JRN-2: the keeper was told whether this pseudonym is on a list (a lookup: on the record)
            detail["match_shown"] = match

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

    def matched_before(sess: Session, body: ApiOptOut) -> str:
        """ "yes" or "no": is the patient a typed whole pseudonym names on a list or registry of this box, read
        before the opt-out removes them; "" when nothing is to be said. Only for a typed pseudonym: a chart
        number is turned into its pseudonym inside ``change_optout`` (capped and audited there) and gets the plain
        answer. It is a lookup ("is this pseudonym a listed patient"), so it is counted per person and hour with
        the chart-number lookups' limit (``TB_OPTOUT_LOOKUPS_PER_HOUR``); past it the opt-out is still taken,
        with no note. No study is named: the keeper of the register reads no study's list."""
        typed = body.pid.strip().lower()
        if body.lift or not can_keep_optouts(sess.user) or not _WHOLE_PID.match(typed):
            return ""
        since = (h.clock() - timedelta(hours=1)).isoformat()
        if not team.take("-", "-", "optout", "pid_match", sess.user.username, now(), since, lookups_per_hour):
            return ""
        found = on_lists(typed)
        return "" if found is None else ("yes" if found else "no")

    @app.get("/site/opt-outs")
    def optout_page(request: Request) -> Response:
        sess = h.need(request)
        if not can_keep_optouts(sess.user):
            raise deny(sess, request.url.path)
        # NEW-JRN-2: what the last opt-out matched, from the redirect: study ids only, or "-" for nobody
        on = request.query_params.get("on", "")
        return h.page(request, "site_optouts.html", sess, rows=optout.current(), events=optout.events()[-30:][::-1],
                      sources=SOURCES, on=on if on in ("yes", "no") else "")  # fmt: skip

    @app.post("/site/opt-outs")
    async def optout_add(request: Request) -> Response:
        sess = h.need(request)
        form = await request.form()
        need_csrf(sess, form)
        # NEW-DIN-3d (the review): the chart number is not cut to the field's 40 characters here; a longer one is
        # refused by the shape check, never registered by its first 40
        body = ApiOptOut(pid=str(form.get("pid") or "")[:64], chart_no=str(form.get("chart_no") or "")[:256],
                         source=str(form.get("source") or "office")[:20], note=str(form.get("note") or "")[:300],
                         lift=form.get("lift") == "1",
                         unknown_reason=str(form.get("unknown_reason") or "")[:300])  # fmt: skip
        match = matched_before(sess, body)
        _pid, changed = change_optout(sess, request.url.path, body, match)
        done = ("lifted" if body.lift else "added") if changed else "same"
        # D-273 (PV-6): no pseudonym back. NEW-JRN-2: for a typed pseudonym, whether a listed patient matched
        more = f"&on={match}" if done == "added" and match else ""
        return RedirectResponse(f"/site/opt-outs?done={done}{more}", status_code=303)

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
    def api_candidates(request: Request, rs: str, page: int | None = None, size: int = API_PAGE) -> dict[str, Any]:
        """The study's candidates. P-20: with ``page`` (from 1), one page of ``size`` rows (at most
        :data:`API_PAGE_MAX`) and ``total``, ``page``, ``pages``, ``size``; without it, every row, as before."""
        sess = api(request)
        rid = study_or_404(sess, rs)
        need_task(sess, rid, "screen", request.url.path)
        wk, rows = candidate_rows(sess, rid)
        paging: dict[str, int] = {}
        if page is not None:
            size = min(max(1, size), API_PAGE_MAX)
            total = len(rows)
            rows, page_no, pages = st.paged(rows, page, size)
            paging = {"total": total, "page": page_no, "pages": pages, "size": size}
        return {
            "study": rid,
            "job_id": wk["job"].job_id if wk else None,
            "candidate_view": view_open(rid),  # D-395: a candidate's page opens (the IRB text covers it)
            **paging,
            "candidates": [
                {"pid": r["pid"], "tier": r["tier"], "status": r["status"], "state": r["person"].name,  # D-1221
                 "screening_no": r["screening_no"],
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
    @before_body(first_refer)
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
        on = optout.effective()
        nos = store.screening_nos(rid)
        return [ref_json(r, nos) for r in team.referrals(rid) if r.pid not in on]

    @app.post("/api/v1/studies/{rs}/referrals/{ref_id}/answer")
    @before_body(first_answer)
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
        return {"study": rid, **{k: getattr(rec, k) or None for k in IRB_FIELDS},
                "warnings": rec.warnings(today())}  # fmt: skip

    @app.post("/api/v1/studies/{rs}/irb")
    @before_body(first_irb)
    def api_irb_save(request: Request, rs: str, body: ApiIrb) -> dict[str, Any]:
        sess = api(request)
        rid, rec = save_irb(sess, request.url.path, rs, body)
        return {"study": rid, **{k: getattr(rec, k) or None for k in IRB_FIELDS},
                "warnings": rec.warnings(today())}  # fmt: skip

    @app.get("/api/v1/site/opt-outs")
    def api_optouts(request: Request) -> dict[str, Any]:
        sess = api(request)
        if not can_keep_optouts(sess.user):
            raise deny(sess, request.url.path)
        rows = optout.current()
        return {"count": len(rows), "opted_out": [{"pid": e.pid, "since": e.at, "source": e.source, "by": e.by}
                                                  for e in rows]}  # fmt: skip

    @app.post("/api/v1/site/opt-outs")
    @before_body(first_optout)
    def api_optout(request: Request, body: ApiOptOut) -> dict[str, Any]:
        sess = api(request)
        match = matched_before(sess, body)
        _pid, changed = change_optout(sess, request.url.path, body, match)
        out: dict[str, Any] = {"opted_out": not body.lift, "changed": changed}  # D-273 (PV-6): no pseudonym back
        if changed and match:  # NEW-JRN-2: for a typed pseudonym, whether a listed patient matched
            out["matched"] = match == "yes"
        return out
