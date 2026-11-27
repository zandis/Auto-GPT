"""Report-first role pages (D-104): one home per role, the feasibility report, the weekly PI list and the patient
page. Registered by ``console.app`` inside the pilot workspace; the older job/registry/cascade pages stay reachable
under "More".

Role → home:

* coordinator (hospital or SMO, study-scoped) → **My studies**: one card per study with its next action;
* investigator → **This week**: the weekly list, marks Approach / Not suitable / Need info;
* cro, viewer → **Reports**: finalised feasibility reports (CRO: the sponsor copy only);
* admin → **Admin**: accounts, approvals, audit, system.

The console never recomputes eligibility: it joins the job outputs the orchestrator already wrote (feasibility
JSON + feasprofile JSON, SCREEN / MICROBATCH candidate list), the candidate registry and its own site store.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote

from datacore.lifecycle import CONTACT_ATTEMPTS, CONTACT_DEFAULT, contact_check
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from tb_common.authz import NO_STANDING, Decision, conditional, study_bound
from tb_common.authz import permit as permit_row
from tb_common.erased import Gone, GoneOn
from tb_common.retention import STUDY_YEARS_AFTER_CLOSE
from tb_common.service_auth import bind_session
from tb_contracts import Job

from console import actor as console_actor
from console import ai_confirm, coded_view, home_today, s28, terminology_refused
from console import person_state as ps
from console import studies as st
from console.api_first import before_body, page_twin
from console.auth import Session, source_of
from console.backend import Problem, Refused, Unavailable
from console.i18n import translate
from console.own_roles import own_roles
from console.reveal import Reveal
from console.sitestore import (
    CAP_VALUES,
    CAPABILITIES_AD,
    CAPABILITIES_GENERAL,
    MARKS,
    OUTCOMES,
    WITHDRAWN,
    Mark,
    Outcome,
    SiteProfile,
    SiteStore,
    StudySettings,
)
from console.studies import known_study
from console.timefmt import local_date, local_today, site_zone

# D-178 (review J-14): the contact outcomes that end the contact; each names its consequence before it is recorded
CLOSING_OUTCOMES = frozenset({"reached_declined", "not_approached", "lost_contact"})

_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
# T-102c (D-425): where ``/home`` sends a role, by the first of these matrix rows it holds (the investigator marks the
# weekly list; the viewer and the CRO read reports; D-280: the steward reviews break-glass; D-380: the privacy office
# keeps the opt-out register); the administrator and the coordinator stay on the home page
HOME_STARTS: tuple[tuple[str, str], ...] = (
    ("list.mark", "/week"),
    ("report.aggregate_only", "/reports"),
    ("breakglass.review", "/breakglass"),
    ("optout.keep", "/site/opt-outs"),
)
_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
SCREEN_TYPES = ("MICROBATCH", "SCREEN")


STALE_DAYS = 2  # FIT-U01: a list whose data is older than this many days is shown amber
# FIT-U03 (T-629): another study's registry status, as this study's list says it
OTHER_STATE = {"candidate": "candidate", "contacted": "candidate", "consented": "enrolled", "enrolled": "enrolled"}


def data_as_of(job: Job, today: date) -> dict[str, Any]:
    """FIT-U01 (T-512): the day of the data a list was made from (the run's snapshot, else the run's own day), and
    whether it is more than :data:`STALE_DAYS` old. Every patient list shows it, so nobody acts on old data unawares."""
    day = job.snapshot_date or job.run_date or (job.updated_at or job.received_at).date()
    return {"day": day.isoformat(), "stale": (today - day).days > STALE_DAYS}


# 10D-17 (D-1242, review 14 M14-16): the ClinicalTrials.gov modes of services/criteria_compiler/ctgov.py (MODES; the
# console does not import the compiler, tests/console/test_ctgov_mode_text.py holds the two equal)
CTGOV_MODES = ("live", "offline", "cassette")


def ctgov_mode(environ: Mapping[str, str] | None = None) -> str:
    """The box's ClinicalTrials.gov mode, read from ``TB_CTGOV_MODE`` as the compiler reads it (lower case, D-140):
    one of :data:`CTGOV_MODES`; ``unset`` when the variable is empty or absent (the compiler then works ``offline``, its
    default, and the page says both); ``unknown`` for a value the compiler refuses. The page never states a mode the
    setting does not name. The console receives the setting from ``deploy/.env`` like every service (``env_file``);
    it reads no data for it."""
    raw = (os.environ if environ is None else environ).get("TB_CTGOV_MODE") or ""
    if not raw:
        return "unset"
    return raw.lower() if raw.lower() in CTGOV_MODES else "unknown"


@dataclass
class Helpers:
    need: Callable[[Request], Session]
    page: Callable[..., Response]
    problem: Callable[..., Exception]  # (status, key, **values) -> exception to raise
    csrf_ok: Callable[[Session, str], bool]
    actor: Callable[[Session], str]
    bk: Any
    au: Any
    store: SiteStore
    users: Any
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    submit: Callable[..., Job] | None = None  # console.app.submit: a request as if mailed (D-108 refresh)
    # set by register(): the rows the pages show, read again by console.notify (D-108)
    week_bundle: Callable[..., dict[str, Any] | None] | None = None
    #: NEW-SEC-1 (D-717): the weekly list as the morning mail reads it (signed as the mail's principal), for the
    #: box's own tools and drills that build it with no person
    mail_week: Callable[[str], dict[str, Any] | None] | None = None
    trials: Callable[..., list[Any]] | None = None
    settings_of: Callable[[str], StudySettings] | None = None
    api_session: Callable[[Request], Session] | None = None  # set by register(): bearer sign-in for /api/v1
    # set by console.lifecycle_pages (D-134): the home page's visits and serious AEs; the visits for N1/N2
    life_home: Callable[..., dict[str, Any]] | None = None
    #: set by console.lifecycle_pages (J-6, D-1225): the participant pages' rule of who reads a study's participants,
    #: and the overdue SAE reports of one study from the data core's answer
    reads_participants: Callable[[Any, str], bool] | None = None
    life_reports_of: Callable[[Any], list[dict[str, Any]]] | None = None
    #: set by console.sae_pages (J-6, D-1225): the SAE pages' rule of who reads a study's serious AEs, and one study's
    #: serious AEs for the opening page from the SAE pages' own answer
    reads_saes: Callable[[Any, str], bool] | None = None
    home_saes: Callable[[str], dict[str, Any]] | None = None
    life_mail: Callable[[str, date], dict[str, Any]] | None = None
    life_sae: Callable[[str], list[dict[str, Any]]] | None = None  # one study's unacknowledged SAEs (the week page)
    life_reports: Callable[[str], list[dict[str, Any]]] | None = None  # one study's overdue SAE reports (P-03)
    sae_sync: Callable[[str], None] | None = None  # set by console.sae_pages (D-277): the SAE register's write path
    # set by console.sae_pages (D-763): how many SAE reports of a study are still to send (raises when not read)
    sae_open: Callable[[str], int] | None = None
    # P-10 (D-143): one confirmation page before an action that is hard to take back
    confirm: Callable[..., Response] | None = None
    # D-146 (review J-03): the role and study scope rules of every page, applied to /api/v1 calls too
    scope_check: Callable[[Request, Session], None] | None = None
    # set by register(): read again by console.team (D-147)
    crit_of: Callable[..., dict[str, Any]] | None = None
    registry_map: Callable[[str], dict[str, str]] | None = None
    #: set by register() (D-1221): the people of one study and their one state each (``console.person_state.read``)
    people: Callable[[str], ps.People] | None = None
    patient_ctx: Callable[..., dict[str, Any]] | None = None
    # set by console.team (D-147): the study team store, the opt-out register and the one permission function
    team: Any = None
    optout: Any = None
    may_approve: Callable[..., bool] | None = None
    stand: Callable[..., Any] | None = None  # console.team.standing for one account and study (T-512)
    #: NEW-JRN-8 (D-772): an account's monitor grants today, as (study, visit id, last day), for the menu
    monitor_grants: Callable[..., list[tuple[str, str, str]]] | None = None
    team_due: Callable[[str], bool] | None = None
    # set by console.team (NEW-JRN-1, D-540): the studies waiting for approval whose log names no PI yet
    pi_missing: Callable[..., list[str]] | None = None
    reveal: Any = None  # set by register(): console.reveal.Reveal, the one reveal path (T-103, D-438)
    chart_lookup: Callable[[Session, str], None] | None = None  # set by console.team: the lookup cap (D-273)
    # set by console.team (NEW-JRN-6, D-771): a chart number turned into its pseudonym at the door, capped and audited
    chart_to_pid: Callable[[Session, str, str], tuple[str, bool | None]] | None = None
    pid_match_per_hour: int = 0  # set by console.team (NEW-JRN-2): the match note's limit per person and hour
    irb_gate: bool = False  # set by console.team (D-395): the candidate view waits for the study's IRB-text record
    # set by console.committee_pages (10C-4, D-1227): the Japan profile's committee findings of a study at this site
    # and what they do (refuse a move into open, hold the lists, wait); None outside the Japan profile
    committee_status: Callable[[str], dict[str, Any] | None] | None = None
    committee_opened: Callable[[str, str], None] | None = None  # a move into open passed (Japan profile)
    ops_summary: Callable[[], dict[str, Any]] | None = None  # set by console.ops_pages (D-178): the health tile
    ops_status: Callable[[], dict[str, Any]] | None = None  # set by console.ops_pages: the host runner's status
    health: Callable[[], Any] | None = None  # set by console.metrics_page (T-209a): tb_common.metrics.Health now
    # set by console.admin_accounts (T-209c, D-406): the /admin health tab's backup, update and account facts, and the
    # unused-account report the Monday health mail carries
    admin_extra: Callable[[Session], dict[str, Any]] | None = None
    accounts_report: Callable[[], dict[str, Any]] | None = None
    identity: Any = None  # console.identity.Identity (D-279): the second factor at signing; None in bare test apps
    recorded: Any = None  # console.recorded_opinions.Recorded (T-515): demo opinions laid over the candidate list
    # set by console.breakglass (D-280, T-309): the account's open grant covering one patient or one job, else None;
    # each call that finds one is one audited use. None in bare test apps (no grant, so no access)
    breakglass: Callable[..., Any] | None = None
    # set by console.team (D-1245): would the study's candidate list admit this account (user, study) -> bool; None in
    # bare test apps (nobody is admitted)
    admits_candidates: Callable[[Any, str], bool] | None = None
    breakglass_find: Callable[..., Any] | None = None  # T-716 (D-484): the open grant, found and not used
    breakglass_note: Callable[..., Any] | None = None  # the audit event of a use the orchestrator recorded
    # T-310a (D-446): set by register(): the latest run's not-matched list and its rows as the page shows them; set by
    # console.notmatched_pages: the weekly sample, the site's check and the send-back to the PI list. None in bare
    # test apps (the list is open and nothing comes back)
    excluded_bundle: Callable[[str], tuple[Job | None, dict[str, Any] | None]] | None = None
    excluded_rows: Callable[[str, dict[str, Any], str], list[dict[str, Any]]] | None = None
    not_matched: Any = None

    def gone(self) -> set[str]:
        """D-273 (PV-4): the pseudonyms on the opt-out register now. Every patient-level reader (lists, the excluded
        list, the job page, the registry) leaves them out; who opted out is itself private, so callers show counts.
        The one register read of the console's pages (D-477, review M3): with the surviving pseudonym of a merged
        chart, as the jobs read it."""
        # D-477 (M3): merged charts too. D-875: an erased token (a never-consented patient's screening-log row kept
        # without the pseudonym) is in it too, so every reader that leaves the opted-out out leaves the row out
        return Gone(self.optout.effective()) if self.optout is not None else Gone()

    def opted_out_on(self) -> dict[str, str]:
        """NEW-LIFE-5 (D-762): each pseudonym of :meth:`gone` with the site's day it was opted out (the first opt-out
        event since its last lift); "" for the surviving chart of a merge, which has no opt-out event of its own. For
        the rows a numbered patient keeps (the screening log, the monitor's sheet): the trial record of a consented
        or enrolled subject stays (D-441)."""
        if self.optout is None:
            return GoneOn()  # D-875: an erased token is still opted out, with the day it carries
        # the review of D-762: the first opt-out since the patient's last lift, not a later repeat (a person's own
        # opt-out after the registry's is an event of its own, D-441)
        first: dict[str, str] = {}
        for e in self.optout.events():
            if e.action == "lift":
                first.pop(e.pid, None)
            elif e.action == "opt_out":
                first.setdefault(e.pid, e.at)
        tz = site_zone(self.bk)
        return GoneOn({p: local_date(first[p], tz) if p in first else "" for p in self.gone()})

    def delegated(self, sess: Session, rid: str, path: str, tasks: tuple[str, ...] = ("screen",)) -> None:
        """D-273 (PV-3): D-147's delegation rule on every page that shows one study's patients, not only the week,
        patient, candidate and SAE pages. Once the study's delegation log names a PI, an investigator sees them only
        as the PI or as a sub-investigator ticked for one of ``tasks``; a refusal is audited."""
        if not self.delegated_ok(sess.user, rid, tasks):
            self.au.append("console.denied", actor=self.actor(sess), detail={"action": path[:80]})
            raise self.problem(403, "forbidden")

    def need_rows(self, sess: Session, rid: str, path: str) -> None:
        """ROLE-017 (T-102c, D-425): who reads one study's patient-level rows. A page, its XLSX and its ``/api/v1``
        twin ask this one question (the ``phi.view`` row, then the study's delegation log), so they never disagree; a
        refusal is audited."""
        if not self.rows_ok(sess.user, rid):  # one refusal, one audit event, whichever of the two said no
            self.au.append("console.denied", actor=self.actor(sess), detail={"action": path[:80]})
            raise self.problem(403, "forbidden")

    def rows_ok(self, user: Any, rid: str) -> bool:
        """The question of :meth:`need_rows` as a yes or no, with no audit event (J-5, D-1223: a list shows the
        screening log's people only to whom the log's own page admits)."""
        return bool(self.permit(user, "phi.view", rid)) and self.delegated_ok(user, rid)

    def delegated_ok(self, user: Any, rid: str | None, tasks: tuple[str, ...] = ("screen",)) -> bool:
        """The rule of :meth:`delegated` as a yes or no, for a page that hides a part instead of refusing. It applies
        to the roles whose ``task.*`` rows the log decides (the matrix's conditions, T-102c); the others pass here
        and meet their own row on the page."""
        if not any(conditional(user.role, f"task.{t}") for t in tasks):
            return True
        return bool(rid) and any(self.permit(user, f"task.{t}", rid) for t in tasks)

    def reads(self, user: Any, rid: str | None) -> bool:
        """T-309 (D-430): does the account read this study's patients by its own rights (the ``phi.view`` row, then the
        delegation log)? Where it does not, the one break-glass rule decides, for the administrator and for an
        investigator alike: an open grant for that patient or that job (``console.breakglass``)."""
        return bool(user.can_view_phi) and self.delegated_ok(user, rid)

    def permit(self, user: Any, action: str, rid: str | None = None) -> Decision:
        """T-102c (D-425): the one question pages and ``/api/v1`` ask: ``tb_common.authz.permit`` for ``action``,
        with the account's standing in study ``rid`` read from the delegation log. No study, a study the account does
        not see, or no log store: no standing, so no condition holds (fails closed; the team fallback is gone)."""
        standing = NO_STANDING
        if rid and self.stand is not None and user.sees_study(rid):
            stand = self.stand
            # once per page view and study (J-6, D-1225): a page that asks several rows reads the log once
            standing = ps.per_view(f"standing:{user.username}:{user.role}", rid, lambda: stand(user, rid).grant())
        return permit_row(user.role, action, standing)

    def may_run(self, user: Any, rid: str | None, command: str) -> bool:
        """T-512 (D-349, Q-04): may this account start ``command`` on study ``rid``? The ``command.*`` row decides,
        with the account's standing in the study; a role whose runs depend on the log needs a study it sees."""
        if study_bound(user.role, "command.") and not (rid and user.sees_study(rid)):
            return False
        return self.permit(user, f"command.{command.upper()}", rid).allowed

    def today(self) -> date:
        """The site's calendar date now (site.tz), the one "today" of every console rule (D-270).

        ``clock()`` is a UTC instant and stays right for timestamps; its ``.date()`` is the UTC date, which in Japan
        is yesterday until 09:00. Delegation and IRB dates, visit days and the morning notices are site
        days, so they all ask here."""
        return local_today(self.clock(), site_zone(self.bk))


class ApiLogin(BaseModel):
    """``POST /api/v1/session`` (D-125)."""

    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=400)
    code: str = Field(default="", max_length=32)  # T-505a (D-320): the authenticator code, with TOTP on
    lang: str = "en"


class ApiMark(BaseModel):
    mark: str
    reason: str = ""
    recheck: str = ""
    note: str = Field(default="", max_length=300)


class ApiOutcome(BaseModel):
    outcome: str
    retry: str = ""
    note: str = Field(default="", max_length=300)


class ApiReveal(BaseModel):
    """``POST /api/v1/studies/{rs}/patients/{pid}/reveal`` (D-143): the reason is required, as on the page."""

    reason: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=200)  # D-273 (ROLE-016): required with "other"


async def json_body(request: Request) -> dict[str, Any]:
    """The JSON object of an ``/api/v1`` call, read after the session was checked (T-657's rule); anything else is
    an empty object, so the route's own checks refuse it."""
    try:
        if not request.headers.get("content-type", "").startswith("application/json"):
            return {}
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store

    # ------------------------------------------------------------------ helpers
    def trials(sess: Session) -> list[Any]:
        return [
            r
            for r in bk.rulesets()
            if r.status == "approved" and r.kind in ("trial", "") and sess.user.sees_study(r.id)
        ]

    def home_roles(sess: Session, shown: list[Any]) -> list[dict[str, Any]]:
        """9f-1, home half (D-1391): the person's own roles (``console.own_roles``) in the studies this page already
        shows them, and in no other, in the page's order of studies: it names and arranges what the account page
        lists, it reads nothing more."""
        return own_roles(getattr(h, "team", None), sess.user.username, h.today(), {r.id.upper() for r in shown},
                     [r.id.upper() for r in shown])  # fmt: skip

    def settings_of(rs: str) -> StudySettings:
        kind = next((r.kind for r in bk.rulesets() if r.id == rs), "trial")
        return s28.load(bk, store, rs, st.study_defaults(rs, kind))

    def approvals(sess: Session) -> list[Job]:
        """Criteria waiting for approval in the studies this account sees (the investigator's S20 queue)."""
        return [
            j
            for j in bk.list_jobs(limit=500)
            if j.state == "awaiting_approval" and j.ruleset and sess.user.sees_study(j.ruleset)
            and any(o.filename.startswith("review_") and o.filename.endswith(".xlsx") for o in j.outputs or [])
        ]  # fmt: skip

    def study_or_404(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid) or not known_study(bk, rid):
            if _RS.match(rid):
                au.append("console.denied", actor=h.actor(sess), detail={"action": f"study {rid}"})
            raise h.problem(404, "notfound")
        return rid

    def crit_of(rs: str, lang: str = "en") -> dict[str, st.CriterionMeta]:
        """The approved criteria; with a label the site gave in ``lang`` at approval (D-120) the page shows that label
        and keeps the study's own label and text beside it."""
        fn = getattr(bk, "criteria", None)
        rows = fn(rs) if fn else []
        mine = store.labels(rs, lang) if lang != "en" else {}
        # T-507 (D-309): the label, text and to-do the ruleset ships in ``lang`` fill in where the site gave none
        return {r["id"]: st.criterion_meta(r, lang, mine.get(r["id"], "")) for r in rows}

    def load(job: Job | None, prefix: str, suffix: str = ".json", tag: str | None = None) -> dict[str, Any] | None:
        out = st.output(job, prefix, suffix, tag)
        if out is None:
            return None
        try:
            with st.no_cycle_collection():  # P-20: a 50k candidate list is 50k new dicts
                data = json.loads(bk.get_object(out.minio_key))
        except (KeyError, ValueError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def registry_map(rs: str) -> dict[str, str]:
        if not console_actor.may_read_any():
            return {}  # D-1221: an account without patient rows anywhere makes no read it would be refused
        try:
            return {e.pid: e.status for e in ps.registry_rows(h, rs)}  # once per page view (D-1221)
        except Exception:  # a page's account without the right (refused and audited) or a service down: none shown;
            if console_actor.reading_for_a_person():  # the D-717 review: in a mail round a failed read is an error,
                return {}  # never "no status"
            raise

    def feas_bundle(sess: Session, rs: str, sponsor: bool) -> dict[str, Any] | None:
        jobs = bk.list_jobs(limit=500)
        job = st.latest_job(jobs, rs, ("FEAS",))
        result = load(job, "feasibility_", ".json", "aggregate")
        if job is None or result is None:
            return None
        prof = load(job, "feasprofile_", ".json", "aggregate")
        rep = st.feas_report(result, prof, store.profile(rs), crit_of(rs, sess.lang if sess else "en"), sponsor=sponsor)
        rep["job"] = job
        rep["has_profile"] = prof is not None
        rep["files"] = [
            o.filename for o in job.outputs or [] if o.tag == "aggregate" and o.filename.endswith((".pdf", ".xlsx"))
        ]
        return rep

    def week_bundle(sess: Session, rs: str, *, rows: bool = True) -> dict[str, Any] | None:
        """The study's latest run as the lists read it. ``rows=False`` (P-20): the list itself (opt-outs and deaths
        taken off), its people and summary, without the week list's rows, counts and first appearances: for a page
        that builds its own rows from ``cl`` (the candidates page and its API), so 50k candidates are read once."""
        jobs = bk.list_jobs(limit=500)
        job = st.latest_job(jobs, rs, SCREEN_TYPES)
        if job is None:
            return None
        cl = load(job, "candidate_list_", ".json")
        if h.recorded:  # T-515 (D-323): recorded first and second checks on a DEV demo, each with its source
            cl = h.recorded.apply(cl, rs)
        # T-310a (D-446, CR-014): a not-matched patient sent back is on the PI's list again, until the PI marks them
        cl, sent_back = h.not_matched.back_to_list(rs, cl) if h.not_matched is not None else (cl, {})
        removed: list[str] = []
        if cl is not None and h.optout is not None:  # D-147: an opted-out patient is on no list, page or mail
            out = h.gone()
            removed = [str(r.get("pid")) for r in cl.get("rows") or [] if str(r.get("pid")) in out]
            if removed:
                cl = {**cl, "rows": [r for r in cl.get("rows") or [] if str(r.get("pid")) not in out]}
        dead, unchecked = deceased_now(cl)
        if dead:  # FIT-U04 (T-629): a death recorded since the run takes the patient off every list at once
            cl = {**(cl or {}), "rows": [r for r in (cl or {}).get("rows") or [] if str(r.get("pid")) not in dead]}
        summary = load(job, "screen_", ".json")
        asof = {**data_as_of(job, h.today()), "dead": len(dead), "dead_unchecked": unchecked}
        if not rows:
            return {"job": job, "summary": summary or {}, "cl": cl, "removed": removed, "asof": asof,
                    "deceased": dead, "dead_unchecked": unchecked, "people": ps.read(h, rs)}  # fmt: skip
        names = (summary or {}).get("practitioner_names") or {}
        pids = [str(r.get("pid")) for r in (cl or {}).get("rows") or [] if r.get("tier") in ("high", "review")]
        seen = store.seen(rs, pids, job.job_id, (job.updated_at or job.received_at).isoformat())
        listed = st.weekly_rows(
            cl,
            crit_of(rs, sess.lang if sess else "en"),
            registry_map(rs),
            store.latest_marks(rs),
            seen,
            job.job_id,
            names,
            today=h.today(),
        )
        others_of(sess, rs, listed)
        people = ps.read(h, rs)  # D-1221: the one state of each person, the same on every list
        for r in listed:
            r["sent_back"] = sent_back.get(str(r["pid"]))
            r["person"] = people.of(str(r["pid"]))
        return {"job": job, "rows": listed, "counts": st.week_counts(listed), "summary": summary or {}, "cl": cl,
                "removed": removed, "asof": asof, "deceased": dead, "dead_unchecked": unchecked,
                "people": people}  # fmt: skip

    def deceased_now(cl: dict[str, Any] | None) -> tuple[set[str], bool]:
        """FIT-U04 (T-629, D-415): the listed patients whose record in the lake now says they died (T-616's
        ``patient.deceased``, or a death date), read at every page view, so a death recorded after the run takes the
        patient off the Approach lists, the call tasks and the morning mail at once. ``(dead, unchecked)``:
        ``unchecked`` when the lake could not be asked; then nobody may be marked Approach or called until it can."""
        fn = getattr(bk, "deceased", None)
        pids = sorted({str(r.get("pid")) for r in (cl or {}).get("rows") or []})
        if fn is None or not pids:
            return set(), False
        try:
            return set(fn(pids)) & set(pids), False
        except Exception:  # the lake did not answer: say so, and stop contacts, never a quiet "no deaths"
            return set(), True

    def others_of(sess: Session | None, rs: str, rows: list[dict[str, Any]]) -> None:
        """FIT-U03 (T-629, D-415): the same patient in other studies, from their candidate registries. Each row gets
        ``elsewhere``: ``{"study", "state"}`` per other study (state ``candidate`` or ``enrolled``), the study named
        only to an account that may see it, else empty ("another study"). Consented or enrolled in another study
        puts the patient on "needs information" (an open item) until a person checks the protocol's rule."""
        if not rows:
            return
        mine = {str(r["pid"]) for r in rows}
        found: dict[str, list[dict[str, str]]] = {}
        for other in bk.rulesets():
            if other.id == rs or other.status != "approved" or other.kind not in ("trial", ""):
                continue
            for pid, status in registry_map(other.id).items():
                state = OTHER_STATE.get(status)
                if pid in mine and state:
                    shown = other.id if sess is not None and sess.user.sees_study(other.id) else ""
                    found.setdefault(pid, []).append({"study": shown, "state": state})
        lang = sess.lang if sess else "en"
        for r in rows:
            r["elsewhere"] = found.get(str(r["pid"]), [])
            if any(o["state"] == "enrolled" for o in r["elsewhere"]):
                r["fit"].open.append(translate(lang, "elsewhere.open"))

    def study_card(sess: Session, r: Any, jobs: list[Job]) -> dict[str, Any]:
        rs = r.id
        feas_job = st.latest_job(jobs, rs, ("FEAS",))
        waiting = st.latest_job(jobs, rs, ("FEAS", "SCREEN", "COMPILE"), state="awaiting_approval")
        screen_job = st.latest_job(jobs, rs, SCREEN_TYPES)
        site = store.profile(rs)
        feas = None
        if feas_job is not None:
            res = load(feas_job, "feasibility_", ".json", "aggregate")
            if res is not None:
                rep = st.feas_report(res, load(feas_job, "feasprofile_", ".json", "aggregate"), site, {})
                feas = rep["summary"]
        # the same rows as the weekly page, so "new" and "marked" agree with what the PI sees
        week: dict[str, Any] | None = week_bundle(sess, rs) if screen_job is not None else None
        people = week["people"] if week else ps.read(h, rs)  # D-1221: the counts of the registry and the office
        if waiting is not None:
            nxt = ("approve", f"/pilot/jobs/{waiting.job_id}/approval")
        elif feas_job is None:
            nxt = ("feas", f"/pilot/request?ruleset={rs}")
        elif site.missing:
            nxt = ("site", f"/studies/{rs}/feasibility#site")
        elif screen_job is None:
            nxt = ("screen", f"/pilot/request?ruleset={rs}")
        elif week and week["counts"]["marked"]:
            nxt = ("contact", f"/studies/{rs}/week")
        else:
            nxt = ("week", f"/studies/{rs}/week")
        today = h.today()
        reg = registry_map(rs)
        rows = week["rows"] if week else []
        tasks: list[dict[str, Any]] = []
        if waiting is not None:
            href = f"/pilot/jobs/{waiting.job_id}/approval"
            tasks.append({"kind": "approve", "rs": rs, "short": waiting.type, "href": href, "due": today, "detail": ""})
        if feas_job is not None and site.missing:
            tasks.append({"kind": "site", "rs": rs, "short": "", "href": f"/studies/{rs}/feasibility#site",
                          "due": today, "detail": ""})  # fmt: skip
        clinic = []
        for w in rows:
            mk = w.get("mark")
            when = w["visit"].date() if w.get("visit") else None
            href = f"/studies/{rs}/week?list=all&pid={w['pid']}#chart"
            open_items = " · ".join((w["fit"].not_met + w["fit"].open + w["fit"].person)[:3])
            paused = mk is not None and mk.mark == "approach" and referral_wait(rs, w["pid"]) is not None
            if mk is not None and mk.mark == "approach" and reg.get(w["pid"]) in (None, "candidate") and not paused:
                # T-516 (UX-013): no call task while a referral asked after Approach waits for the doctor
                due = date.fromisoformat(local_date(mk.at, site_zone(h.bk))) + timedelta(days=2)
                tasks.append({"kind": "call", "rs": rs, "short": w["short"], "href": href, "due": due,
                              "detail": mk.note or open_items})  # fmt: skip
            elif mk is not None and mk.mark == "need_info":
                due = date.fromisoformat(local_date(mk.at, site_zone(h.bk))) + timedelta(days=3)
                tasks.append({"kind": "info", "rs": rs, "short": w["short"], "href": href, "due": due,
                              "detail": mk.note or open_items})  # fmt: skip
            if when is not None and today <= when <= today + timedelta(days=14):
                clinic.append({**w, "rs": rs, "href": href, "open_items": open_items})
                if mk is None and when <= today + timedelta(days=2):
                    tasks.append({"kind": "prepare", "rs": rs, "short": w["short"], "href": href, "due": when,
                                  "detail": open_items})  # fmt: skip
        if h.team is not None:  # D-147: doctors to ask for a referral; the monthly delegation-log comparison
            for ref in h.team.latest_referrals(rs).values():
                if ref.open and any(w["pid"] == ref.pid for w in rows):
                    tasks.append({"kind": "refer", "rs": rs, "short": ref.pid[:8], "due": today,
                                  "href": f"/studies/{rs}/referrals#r{ref.id}", "detail": ref.physician})  # fmt: skip
            if h.team_due is not None and h.team_due(rs):
                tasks.append({"kind": "delegation", "rs": rs, "short": "", "href": f"/studies/{rs}/team#check",
                              "due": today, "detail": ""})  # fmt: skip
        for tk in tasks:
            tk["late"] = tk["due"] < today
        return {
            "id": rs,
            "version": r.version,
            "step": study_step(rs, people),
            # D-1221: master's funnel (found, PI reviewed, contacted, consented, enrolled; cumulative), fed by the one
            # state of each person; the opening page's layout changes only behind card J-7's flag
            "pipeline": ps.funnel(people, [str(w["pid"]) for w in rows]),
            "people_readable": people.readable,
            "people": people,  # J-6 (D-1225): the Next line reads the same states as the funnel
            "tasks": tasks,
            "clinic": clinic,
            "feas": feas,
            "feas_job": feas_job,
            "week": week,
            "site_missing": site.missing,
            "next": nxt,
        }

    # the notices (console.notify) read the same rows as the pages
    h.week_bundle = week_bundle

    def mail_week(rs: str) -> dict[str, Any] | None:
        with console_actor.reading_as(console_actor.NOTIFY):
            return week_bundle(None, rs)  # type: ignore[arg-type]

    h.mail_week = mail_week
    h.trials = trials
    h.settings_of = settings_of
    h.crit_of = crit_of
    h.registry_map = registry_map
    h.people = lambda rs: ps.read(h, rs)

    def screen_or_403(sess: Session, rid: str, path: str) -> None:
        """D-147: once a study's delegation log names a PI, an investigator sees its patients only as the PI or a
        sub-investigator the PI ticked "screen" for (the one rule, ``Helpers.delegated``, D-273)."""
        h.delegated(sess, rid, path)

    # ------------------------------------------------------------------ homes
    def recent_jobs() -> list[Job]:
        """The jobs both forms of the opening page read (J-6 shares the coordinator home's one read)."""
        return list(bk.list_jobs(limit=500))

    @app.get("/home")
    @st.heavy_page  # P-20
    def home(request: Request, view: str = "", today: str = "") -> Response:
        sess = h.need(request)
        if getattr(request.state, "home_today", False) and sess.user.role in home_today.ROLES:  # J-6 (D-1225)
            return today_home(request, sess, every=today == "all")
        # T-102c (D-425): each role starts on the page of its first right in this order (the matrix's rows)
        for action, start in HOME_STARTS:
            if permit_row(sess.user.role, action):
                return RedirectResponse(start, status_code=303)
        if sess.user.is_admin and view != "studies":
            admin_page = getattr(h, "admin_page", None)  # step 4: S13 with its tabs (console.step4)
            return admin_page(request, sess, "health") if admin_page else admin_home(request, sess)
        jobs = recent_jobs()
        cards = [study_card(sess, r, jobs) for r in trials(sess)]
        tasks = sorted((tk for c in cards for tk in c["tasks"]), key=lambda tk: (tk["due"], tk["rs"]))
        clinic = sorted((v for c in cards for v in c["clinic"]), key=lambda v: v["visit_text"])
        phi = sess.user.can_view_phi  # D-280 (CR-023): the administrator's study view carries no patient row
        return h.page(
            request, "home_crc.html", sess, cards=cards, tasks=tasks, clinic=clinic if phi else [], steps=st.STEPS,
            home_roles=home_roles(sess, trials(sess)),
            pipeline_keys=st.PIPELINE, models=bk.models(), life=h.life_home(sess) if h.life_home and phi else None,
        )  # fmt: skip

    def today_home(request: Request, sess: Session, every: bool) -> Response:
        """J-6 (D-1225): "Needs you today" and one "Next" line per study (``console.home_today``). A study's
        patient-level sources (its people, visits and serious AEs) are read only where the participant pages would let
        this account read them (``lifecycle_pages.reads_participants``, the rule of their ``study_or_404``); within
        those, visits with the task ``enter_data`` and the card's tasks with ``request.prepare`` (none for a closed
        study). Serious AEs are read where the SAE pages would show them (``sae_pages.sae_scope``), once. Every
        other study gets its Next from the reads the account already has (the feasibility report, a monitor grant), so
        no read is made that a page would refuse. The account's standing in each study's log is read once per page
        view (``Helpers.permit``)."""
        user = sess.user
        jobs = recent_jobs()
        day = h.today()

        def allow(action: str, rid: str | None = None) -> bool:
            return bool(h.permit(user, action, rid).allowed)

        def mine_of(step: str, rid: str) -> bool:
            """Whether this account does ``step`` itself: the row its page asks (asked for the step shown only)."""
            if step == "approve":
                return bool(h.may_approve(user, rid)) if h.may_approve else allow("criteria.approve", rid)
            if step in ("feas", "screen"):
                return h.may_run(user, rid, "FEAS" if step == "feas" else "SCREEN")
            if step in ("review", "contact"):  # the week page: its row, then the study's log (task "screen")
                row = "list.mark" if step == "review" else "request.prepare"
                return allow(row, rid) and h.delegated_ok(user, rid)
            if step in ("consent", "conduct"):
                return allow("task.enter_data", rid)
            return step in ("startup", "close", "paused") and allow("study.state", rid)

        studies = trials(sess)
        readable = [r.id for r in studies if h.reads_participants is not None and h.reads_participants(user, r.id)]
        states = {rs: store.study_state(rs) for rs in readable}
        # a closed study has no visits, tasks or site fields to do; its serious AEs keep their reporting clocks
        visit_studies = [rs for rs in readable if states[rs].state != "closed" and allow("task.enter_data", rs)]
        # the SAE pages' own rule (sae_pages.sae_scope), not the participant pages': their serious AEs are read for
        # the opening page only where those pages show them to this account
        sae_studies = [r.id for r in studies if h.reads_saes is not None and h.reads_saes(user, r.id)]
        life = (h.life_home(sess, only=visit_studies, visits=visit_studies, saes=())
                if h.life_home and visit_studies else None)  # fmt: skip
        coordinator_card = allow("request.prepare")  # the study card with its tasks and funnel, as on today's home
        cards: list[dict[str, Any]] = []
        lines: list[home_today.TodayLine] = []
        nexts: list[home_today.NextLine] = []
        failed: list[str] = []
        grants = {g[0]: g for g in (h.monitor_grants(user) if h.monitor_grants else [])}
        for r in studies:
            rs = r.id
            if rs not in readable:  # no patient-level read in this study: the aggregate reads only
                step = home_today.report_step(report=st.latest_job(jobs, rs, ("FEAS",)) is not None,
                                              grant=grants.get(rs))  # fmt: skip
                g = grants.get(rs) or ("", "", "")
                nexts.append(home_today.next_line(rs, step, step != "report_none", home_today.href_of(step, rs),
                                                  visit=g[1] or "–", end=g[2] or "–"))  # fmt: skip
                continue
            state = states[rs]
            if coordinator_card:
                card = study_card(sess, r, jobs)
                cards.append(card)
                people = card["people"]
                step_no = card["step"]
                if state.state != "closed":
                    lines += home_today.task_lines(card["tasks"], day)
            else:
                people = ps.read(h, rs)
                step_no = study_step(rs, people)
            screen_done = st.latest_job(jobs, rs, SCREEN_TYPES) is not None
            step = home_today.life_step(state=state.state, step=step_no, screen_done=screen_done,
                                        counts=people.counts() if people.readable else None)  # fmt: skip
            waiting = st.latest_job(jobs, rs, ("FEAS", "SCREEN", "COMPILE"), state="awaiting_approval")
            href = home_today.href_of(step, rs, approval=f"/pilot/jobs/{waiting.job_id}/approval" if waiting else "")
            mine = bool(href) and mine_of(step, rs)
            nexts.append(home_today.next_line(rs, step, mine, href,
                                              years=state.keep_years or STUDY_YEARS_AFTER_CLOSE))  # fmt: skip
            if rs in visit_studies and life is not None:
                for v in life["studies"]:
                    if v["rs"] == rs:
                        lines += home_today.visit_lines(rs, len(v["overdue"]), len(v["today"]), day)
        for rs in sae_studies:  # one read of the study's serious AEs, the SAE pages' own (sae_pages.home_saes)
            got: dict[str, Any] = (h.home_saes(rs) if h.home_saes is not None
                                   else {"unacked": [], "reports": [], "failed": True})  # fmt: skip
            lines += home_today.sae_lines(rs, got["unacked"], got["reports"], acknowledges=allow("sae.ack", rs))
            if got["failed"]:
                failed.append(rs)
        lines = home_today.ordered(lines)
        shown = lines if every else lines[: home_today.LIMIT]
        home_today.mark_in_today(nexts, shown)
        # the "This week" link only where the week page itself admits this account (``Helpers.reads``: its phi.view
        # and delegation checks): straight to the study's week when there is one, else the week picker
        weeks = [r.id for r in studies if h.reads(user, r.id)]
        week_href = f"/studies/{weeks[0]}/week" if len(weeks) == 1 else "/week" if weeks else ""
        template = "home_crc.html" if coordinator_card else "home_today.html"
        return h.page(
            request, template, sess, today=True, every=every, lines=shown, more=len(lines) - len(shown),
            home_roles=home_roles(sess, studies),
            total=len(lines), nexts=nexts, today_failed=failed, cards=cards, tasks=[], clinic=[], steps=st.STEPS,
            pipeline_keys=st.PIPELINE, models=bk.models() if coordinator_card else None, life=None,
            week_href=week_href,
        )  # fmt: skip

    def admin_home(request: Request, sess: Session) -> Response:
        users = h.users.users()
        today = h.today()
        soon = [u for u in users if u.expires and u.expires <= (today + timedelta(days=30)).isoformat()]
        jobs = bk.list_jobs(limit=200)
        waiting = [j for j in jobs if j.state == "awaiting_approval"]
        since = (h.clock() - timedelta(hours=24)).isoformat()
        recs = [r for r in bk.audit(None, 1000) if r.ts >= since]
        reveals: dict[str, int] = {}
        for r in recs:
            if r.event in ("console.reveal", "console.reveal_patient"):
                reveals[r.actor] = reveals.get(r.actor, 0) + 1
        counts = {
            "exports": sum(1 for r in recs if r.event in ("console.export", "console.download")),
            "denied": sum(
                1 for r in recs if r.event in ("console.denied", "console.login_failed", "console.sso_rejected")
            ),
            "marks": sum(1 for r in recs if r.event == "console.pi_mark"),
        }
        by_aff: dict[str, int] = {}
        for u in users:
            by_aff[u.affiliation] = by_aff.get(u.affiliation, 0) + 1
        return h.page(
            request,
            "home_admin.html",
            sess,
            users=users,
            by_aff=by_aff,
            soon=soon,
            waiting=waiting,
            rulesets=bk.rulesets(),
            reveals=sorted(reveals.items(), key=lambda kv: -kv[1]),
            counts=counts,
            health=bk.health(),
            models=bk.models(),
            term_refused=terminology_refused.on_box(),  # E-TERM-3 (D-1048): a site list the box does not read
        )

    @app.get("/reports")
    def reports(request: Request) -> Response:
        sess = h.need(request)
        jobs = bk.list_jobs(limit=500)
        rows = []
        for r in trials(sess):
            job = st.latest_job(jobs, r.id, ("FEAS",))
            res = load(job, "feasibility_", ".json", "aggregate")
            summary = None
            if res is not None:
                summary = st.feas_report(
                    res,
                    load(job, "feasprofile_", ".json", "aggregate"),
                    store.profile(r.id),
                    {},
                    sponsor=sess.user.sponsor_form,
                )["summary"]
            rows.append({"id": r.id, "version": r.version, "job": job, "summary": summary})
        return h.page(request, "reports.html", sess, rows=rows)

    @app.get("/week")
    def week_any(request: Request) -> Response:
        sess = h.need(request)
        if sess.user.aggregate_only:
            raise h.problem(403, "forbidden")
        jobs = bk.list_jobs(limit=500)
        mine = [r for r in trials(sess) if st.latest_job(jobs, r.id, SCREEN_TYPES) is not None]
        waiting = approvals(sess)
        if len(mine) == 1 and not waiting:
            return RedirectResponse(f"/studies/{mine[0].id}/week", status_code=303)
        cohorts = [
            r for r in bk.rulesets()
            if r.status == "approved" and r.kind in st.REGISTRY_KINDS and sess.user.sees_study(r.id)
            and st.latest_job(jobs, r.id, SCREEN_TYPES) is not None
        ]  # fmt: skip
        life = h.life_home(sess) if h.life_home else None
        return h.page(request, "week_pick.html", sess, studies=mine, approvals=waiting, cohorts=cohorts, life=life)

    # ------------------------------------------------------------------ feasibility report
    @app.get("/studies/{rs}/feasibility")
    def feasibility(request: Request, rs: str, view: str = "", saved: str = "", refreshed: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        sponsor = view == "sponsor" or sess.user.sponsor_form
        rep = feas_bundle(sess, rid, sponsor)
        site = store.profile(rid)
        wk = week_bundle(sess, rid) if rep and sess.user.can_view_phi and not sponsor else None
        bridge = st.list_bridge(rep, wk["rows"] if wk else None, h.today()) if rep else None
        ad = bool(rep and rep["summary"].get("screen_fail_ref"))
        keys = CAPABILITIES_AD if ad else CAPABILITIES_GENERAL
        return h.page(
            request,
            "feasibility.html",
            sess,
            rs=rid,
            rep=rep,
            bridge=bridge,
            site=site,
            cap_keys=keys,
            cap_values=CAP_VALUES,
            can_edit=sess.user.can_request,
            can_refresh=h.may_run(sess.user, rid, "FEAS"),  # T-512 (D-349): the PI refreshes feasibility too
            saved=saved == "1",
            refreshed=refreshed == "1",
            registry=next((r.kind for r in bk.rulesets() if r.id == rid), "") in st.REGISTRY_KINDS,
            ctgov_mode=ctgov_mode(),  # 10D-17: the sentence under section 9 states it
        )

    @app.post("/studies/{rs}/feasibility/refresh")
    def feasibility_refresh(request: Request, rs: str, csrf: str = Form("")) -> Response:
        """FR-FEAS-13: run the study's feasibility again on today's snapshot, with the approved criteria."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not h.may_run(sess.user, rid, "FEAS") or h.submit is None:  # T-512 (D-349): the PI may refresh
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        if not any(r.id == rid and r.status == "approved" for r in bk.rulesets()):
            raise h.problem(409, "request.refused", reason="approve the criteria first")
        h.submit(sess, f"FEAS {rid}")
        return RedirectResponse(f"/studies/{rid}/feasibility?refreshed=1", status_code=303)

    @app.post("/studies/{rs}/profile")
    async def profile_save(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        if not sess.user.can_request:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        prof = SiteProfile()
        for key in (*CAPABILITIES_AD, *CAPABILITIES_GENERAL):
            v = str(form.get(f"cap_{key}") or "")
            note = str(form.get(f"capnote_{key}") or "")[:200]
            if v in CAP_VALUES:
                prof.capabilities[key] = {"value": v, "note": note}
        for i in range(5):
            tid = str(form.get(f"ct_id_{i}") or "").strip()[:40]
            if not tid:
                continue
            prof.competing.append(
                {
                    "id": tid,
                    "title": str(form.get(f"ct_title_{i}") or "")[:160],
                    "overlap": str(form.get(f"ct_overlap_{i}") or "")[:20],
                    "status": str(form.get(f"ct_status_{i}") or "")[:40],
                }
            )
        try:
            tn = str(form.get("target_n") or "").strip()
            tm = str(form.get("target_months") or "").strip()
            prof.target_n = int(tn) if tn else None
            prof.target_months = int(tm) if tm else None
            sf = str(form.get("screen_fail") or "").strip().rstrip("%")
            prof.screen_fail = (float(sf) / 100.0) if sf else None
        except ValueError as exc:
            raise h.problem(400, "request.refused", reason="target and screen failure must be numbers") from exc
        if prof.target_n is not None and not 0 < prof.target_n <= 10_000:
            raise h.problem(400, "request.refused", reason="target must be between 1 and 10,000 patients")
        if prof.target_months is not None and not 1 <= prof.target_months <= 120:
            raise h.problem(400, "request.refused", reason="target period must be 1 to 120 months")
        if prof.screen_fail is not None and not 0 <= prof.screen_fail < 1:
            raise h.problem(400, "request.refused", reason="screen failure must be 0 to 99 %")
        prof.comment = str(form.get("comment") or "")[:1000]
        prof.comment_to_sponsor = form.get("comment_to_sponsor") == "1"
        store.save_profile(rid, prof, sess.user.username, h.clock().isoformat())
        au.append("console.site_profile", ruleset=rid, actor=h.actor(sess), detail={"action": "save"})
        return RedirectResponse(f"/studies/{rid}/feasibility?saved=1#site", status_code=303)

    # ------------------------------------------------------------------ weekly list and patient page
    @app.get("/studies/{rs}/week")
    @st.heavy_page  # P-20
    def week(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not sess.user.can_view_phi:
            raise h.problem(403, "forbidden")
        screen_or_403(sess, rid, request.url.path)
        if settings_of(rid).study_type == "registry":
            return RedirectResponse(f"/studies/{rid}/cohort", status_code=303)
        wk = week_bundle(sess, rid)
        today = h.today()
        counts = st.worklist_counts(wk["rows"], today) if wk else {}
        lst = request.query_params.get("list", "")
        if lst not in st.WORKLISTS:  # open on the first list with work in it
            lst = next((k for k in ("clinic", "review") if counts.get(k)), "all")
        rows = st.worklist_sorted([r for r in wk["rows"] if st.in_worklist(r, lst, today)] if wk else [], lst)
        try:
            want = int(request.query_params.get("page") or 1)
        except ValueError:
            want = 1
        pid = request.query_params.get("pid", "")
        if pid and "page" not in request.query_params:  # a chart link opens the page that holds the patient
            at = next((i for i, r in enumerate(rows) if r["pid"] == pid), 0)
            want = at // st.PAGE_SIZE + 1
        order = [r["pid"] for r in rows]  # the whole list, for Next on the patient sheet
        rows, page_no, pages = st.paged(rows, want)
        for r in rows:
            r["score"] = st.met_score(r["fit"])
            r["n_open"] = st.n_open(r)
        sel = None
        opened = bool(pid) and _PID.match(pid) is not None  # the user tapped a row (a sheet on the phone, D-133)
        if wk and rows:
            if pid not in order and not opened:
                pid = rows[0]["pid"]
            try:
                # D-133 (review F-03): after a mark the patient may have left this list; the panel still shows that
                # patient's real state (and Undo), never the next patient's
                sel = patient_ctx(sess, rid, pid, wk)
            except Exception as exc:  # h.problem(404): a pid not on this run's list opens the first row instead
                if getattr(exc, "status", 0) != 404:
                    raise
                pid, opened = rows[0]["pid"], False
                sel = patient_ctx(sess, rid, pid, wk)
            nxt = order.index(pid) + 1 if pid in order else 0
            sel["next_pid"] = order[nxt] if nxt < len(order) and order[nxt] != pid else None
            sel["next_page"] = nxt // st.PAGE_SIZE + 1
        return h.page(
            request,
            "week.html",
            sess,
            rs=rid,
            wk=wk,
            lst=lst,
            lists=st.WORKLISTS,
            counts=counts,
            rows=rows,
            page_no=page_no,
            pages=pages,
            # D-120: the coordinator records a call from the list in two taps (open, then the outcome)
            # D-1221: no quick outcome in a closed study (the outcome route refuses it)
            quick_outcomes=tuple(OUTCOMES)
            if sess.user.can_request and not sess.user.can_mark and store.study_state(rid).state != "closed"
            else (),
            sel=sel,
            opened=opened and sel is not None,
            marks=MARKS,
            reasons=settings_of(rid).reasons,
            step=study_step(rid),
            steps=st.STEPS,
            approvals=approvals(sess),
            sae=[{**a, "rs": rid} for a in h.life_sae(rid)] if h.life_sae else [],
            sae_reports=[{**a, "rs": rid} for a in h.life_reports(rid)] if h.life_reports else [],
            irb_warn=sel["irb_warn"] if sel else [],
            may_approach=sel["may_approach"] if sel else False,
            ref_wait=sel["ref_wait"] if sel else None,
            approach_by=sel["approach_by"] if sel else "",
            team_due=bool(h.team_due and h.team_due(rid)),
        )

    def study_step(rid: str, people: ps.People | None = None) -> int:
        jobs = bk.list_jobs(limit=500)
        n = (people or ps.read(h, rid)).counts()  # D-1221: the step follows the same states as the funnel
        return st.procedure_step(
            approved=any(r.id == rid and r.status == "approved" for r in bk.rulesets()),
            feas_done=st.latest_job(jobs, rid, ("FEAS",)) is not None,
            screen_done=st.latest_job(jobs, rid, SCREEN_TYPES) is not None,
            contacted=ps.reached(n, "contacted"),
            enrolled=ps.reached(n, "enrolled"),
            waiting=st.latest_job(jobs, rid, ("FEAS", "SCREEN", "COMPILE"), state="awaiting_approval") is not None,
        )

    unread_of: dict[str, Any] = {}  # the last run asked and its answer (one entry)

    def values_unread(job: Job | None) -> bool:
        """NEW-CAND-1 (D-713): did this run say it could not read the values behind its coded answers? The run
        keeps that in its stored "not matched" list (``coded_values: not read``, D-652). A run that read them, a
        list from before the field existed and a run with no stored list all answer no: nothing is said. An
        after-ingest or weekly run (``MICROBATCH``) stores no such list and records no flag, so nothing is said
        while it is the study's latest run (D-713, "What it does not do").

        The answer of the last run asked is kept: a finished run's stored list does not change, and the weekly
        list's side panel asks for every view (it shows no coded value, but shares this context)."""
        if job is None:
            return False
        if unread_of.get("job") != job.job_id:
            said = (load(job, "excluded_", ".json") or {}).get("coded_values") == "not read"
            unread_of.update(job=job.job_id, said=said)
        return bool(unread_of["said"])

    def patient_ctx(sess: Session, rid: str, pid: str, wk: dict[str, Any] | None = None) -> dict[str, Any]:
        """``wk``: the week bundle the caller read in this same request (P-20: the list is read once per view)."""
        if not _PID.match(pid):
            raise h.problem(404, "notfound")
        wk = wk if wk is not None else week_bundle(sess, rid)
        if wk is None:
            raise h.problem(404, "notfound")
        row = next((r for r in (wk["cl"] or {}).get("rows") or [] if str(r.get("pid")) == pid), None)
        if row is None:
            raise h.problem(404, "notfound")
        crit = crit_of(rid, sess.lang)
        listed = next((r for r in wk["rows"] if r["pid"] == pid), None)
        names = (wk["summary"] or {}).get("practitioner_names") or {}
        fit = st.fit_facts(row.get("criteria") or [], crit)
        elsewhere = (listed or {}).get("elsewhere") or []
        if any(o["state"] == "enrolled" for o in elsewhere):  # FIT-U03 (T-629): as on the list
            fit.open.append(translate(sess.lang, "elsewhere.open"))
        return {
            "rs": rid,
            "pid": pid,
            "job": wk["job"],
            "values_unread": values_unread(wk["job"]),
            "asof": wk["asof"],
            "row": row,
            "listed": listed,
            "elsewhere": elsewhere,
            "fit": fit,
            "crits": st.patient_rows(row.get("criteria") or [], crit),
            "practitioner": names.get(row.get("practitioner_id") or "", row.get("practitioner_id") or ""),
            "history": store.mark_history(rid, pid),
            "registry": registry_map(rid).get(pid),
            "person": (listed or {}).get("person") or wk["people"].of(pid),  # D-1221
            "study_closed": store.study_state(rid).state == "closed",
            "judging": (wk["cl"] or {}).get("judging") or {},
            "marks": MARKS,
            "reasons": settings_of(rid).reasons,
            "mark": store.latest_marks(rid).get(pid),
            "screening_no": store.screening_no(rid, pid),
            "outcomes": store.outcomes(rid, pid),
            "contact": contact_state(rid, pid, h.today()),  # D-407 (LIFE-017): attempt n of the study's limit
            "outcome_keys": tuple(OUTCOMES),
            "today": h.today(),
            "mrn": None,
            # D-147: the IRB/consent-form warning before Approach, who may mark Approach, a referral still waiting
            "irb_warn": h.team.irb(rid).warnings(h.today()) if h.team is not None else [],
            "may_approach": sess.user.can_mark and h.permit(sess.user, "task.approach", rid).allowed,
            "ref_wait": referral_wait(rid, pid),
            # T-516 (UX-015): who marks Approach when this account may not (the logged PI), shown where the button is
            "approach_by": approach_by(rid),
        }

    # ------------------------------------------------------------------ excluded patients and why (P-04, D-143)
    # "records": the confirmed facts could not be read on that run (D-652): from the records, confirmed or not
    ex_sources = ("coded", "fact", "records", "notes", "rule")

    def excluded_bundle(rid: str) -> tuple[Job | None, dict[str, Any] | None]:
        """The latest screening run of the study that stored its excluded list (``excluded_*.json``)."""
        jobs = [j for j in bk.list_jobs(limit=500) if j.ruleset == rid and j.type in SCREEN_TYPES and j.state == "done"]
        for job in sorted(jobs, key=lambda j: j.updated_at or j.received_at, reverse=True):
            doc = load(job, "excluded_", ".json")
            if doc is not None:
                gone = h.gone()  # D-273 (PV-4): an opted-out patient is on no list, the excluded list too
                return job, {**doc, "rows": [r for r in doc.get("rows") or [] if str(r.get("pid")) not in gone]}
        return None, None

    def excluded_rows(rid: str, doc: dict[str, Any], lang: str) -> list[dict[str, Any]]:
        crit = crit_of(rid, lang)
        # D-652: an answer with no source, in a document that says the confirmed facts were not read, is not said to
        # come from "the coded records"
        unsourced = "records" if doc.get("confirmed_facts") == "not read" else "coded"
        out = []
        for r in doc.get("rows") or []:
            items = [
                {"id": c["id"], "label": crit[c["id"]].label if c["id"] in crit else c["id"],
                 "kind": crit[c["id"]].kind if c["id"] in crit else "", "source": c.get("source") or unsourced,
                 "quote": c.get("quote"), "date": c.get("quote_date"), "reason": c.get("reason"),
                 "records": len(c.get("resource_refs") or []),
                 # T-514 (D-362): the coded records' value, unit, date and code; the test model's note answers say so
                 "coded": coded_view.view(c, "fail"),
                 "test_model": c.get("source") == "notes" and st.test_model_in_use()}
                for c in r.get("criteria") or []
            ]  # fmt: skip
            if not items:  # excluded by the run's own rules: scope, research-contact consent
                items = [{"id": "", "label": "consent" if "consent" in a.lower() or a.startswith("contact")
                          else "scope", "kind": "", "source": "rule", "quote": None, "date": None, "reason": None,
                          "records": 0, "coded": None, "test_model": False}
                         for a in r.get("actions") or ["scope"]]  # fmt: skip
            out.append({"pid": str(r["pid"]), "short": str(r["pid"])[:8], "items": dedupe_items(items)})
        return out

    def has_evidence(i: dict[str, Any]) -> bool:
        return bool(i["quote"] or (i["coded"] or {}).get("lines"))

    def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """T-685 (UX-031): one line per patient, criterion and source. A run's own rule (scope, research-contact
        consent) came once per action, so one reason stood five to seven times; a criterion listed twice from the
        same source keeps its first line that has evidence, with the record counts added."""
        seen: dict[tuple[str, str, str], dict[str, Any]] = {}
        for i in items:
            key = (i["source"], i["id"], i["label"])
            first = seen.get(key)
            if first is None:
                seen[key] = dict(i)
            elif not has_evidence(first) and has_evidence(i):
                seen[key] = {**i, "records": first["records"] + i["records"]}
            else:
                first["records"] += i["records"]
        return list(seen.values())

    h.excluded_bundle = excluded_bundle
    h.excluded_rows = excluded_rows

    def need_excluded(sess: Session, rs: str, path: str) -> str:
        rid = study_or_404(sess, rs)
        if not sess.user.can_view_phi:  # the PI and the CRC (and the administrator); never viewer or CRO
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        h.delegated(sess, rid, path)  # D-273 (PV-3): the same delegation rule as the week page
        return rid

    @app.get("/studies/{rs}/excluded")
    def excluded_moved(request: Request, rs: str) -> Response:
        """T-116 (D-351): the page is "Criteria not matched"; the old path answers 301 for one release, query kept.
        Access is checked first, so an account that may not see the list gets the same 403 here as on the page."""
        rid = need_excluded(h.need(request), rs, request.url.path)
        q = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"/studies/{quote(rid, safe='')}/not-matched{q}", status_code=301)

    @app.get("/studies/{rs}/not-matched")
    def excluded(request: Request, rs: str, src: str = "", page: int = 1, done: str = "") -> Response:
        sess = h.need(request)
        rid = need_excluded(sess, rs, request.url.path)
        nm = h.not_matched
        # T-310a (D-446, FIT-007): where the list waits for the site's check, the page says so and lists nobody
        if nm is not None and not nm.shown(rid):
            au.append("console.view", ruleset=rid, actor=h.actor(sess), detail={"page": "excluded", "held": True})
            return h.page(request, "excluded.html", sess, rs=rid, job=None, doc=None, total=0, rows=[], sent={},
                          counts={}, src="", sources=ex_sources, page_no=1, pages=1, done=False, held=nm.state(rid),
                          may_sample=False)  # fmt: skip
        job, doc = excluded_bundle(rid)
        rows = excluded_rows(rid, doc, sess.lang) if doc else []
        sent = store.excluded_reviews(rid)
        counts = {s: sum(1 for r in rows if any(i["source"] == s for i in r["items"])) for s in ex_sources}
        if src in ex_sources:
            rows = [r for r in rows if any(i["source"] == src for i in r["items"])]
        rows.sort(key=lambda r: (r["pid"] not in sent, r["pid"]))  # sent to review first
        pages = max(1, -(-len(rows) // st.PAGE_SIZE))
        page_no = min(max(1, page), pages)
        au.append("console.view", ruleset=rid, actor=h.actor(sess), detail={"page": "excluded", "rows": len(rows)})
        total = len((doc or {}).get("rows") or [])
        may_send = bool(h.permit(sess.user, "notmatched.send_back", rid))
        return h.page(request, "excluded.html", sess, rs=rid, job=job, doc=doc, total=total,
                      rows=rows[(page_no - 1) * st.PAGE_SIZE: page_no * st.PAGE_SIZE], sent=sent, counts=counts,
                      src=src if src in ex_sources else "", sources=ex_sources, page_no=page_no, pages=pages,
                      done=done == "sent", held=nm.state(rid) if nm is not None else None, may_send=may_send,
                      may_sample=bool(h.permit(sess.user, "notmatched.sample", rid)))  # fmt: skip

    def apply_review(sess: Session, path: str, rs: str, pid: str, crit: str, note: str) -> tuple[str, str]:
        """ "This is wrong, send to review" (P-04), the same for the page and ``/api/v1``: recorded with the person
        and the time, audited; T-310a (D-446, CR-014): the patient is back on the PI's weekly list. The
        ``notmatched.send_back`` row decides who; a list held for the site's check takes nothing. Returns (study,
        job)."""
        rid = need_excluded(sess, rs, path)
        if not h.permit(sess.user, "notmatched.send_back", rid):
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        if h.not_matched is not None and not h.not_matched.shown(rid):
            raise h.problem(409, "nm.held")
        job, doc = excluded_bundle(rid)  # an opted-out patient is on no list, so never sent back (D-273)
        if (
            job is None
            or doc is None
            or not _PID.match(pid)
            or not any(str(r.get("pid")) == pid for r in doc.get("rows") or [])
        ):
            raise h.problem(404, "notfound")
        crit = crit.strip()[:40]

        def decided() -> None:  # D-989 (D-1152): the review rejects the model's answers that excluded the patient
            ai_confirm.review(au, rid, job.job_id, doc, pid, crit, sess.user.username, h.actor(sess))

        store.send_excluded_review(rid, pid, job.job_id, crit, note.strip()[:300], h.actor(sess),
                                   h.clock().isoformat(), before_commit=decided)  # fmt: skip
        au.append("console.excluded_review", job_id=job.job_id, ruleset=rid, actor=h.actor(sess),
                  detail={"pid": pid, "criterion": crit, "role": sess.user.role})  # fmt: skip
        return rid, job.job_id

    @app.post("/studies/{rs}/not-matched/{pid}/review")
    @app.post("/studies/{rs}/excluded/{pid}/review")  # the old path still takes a form posted from an open page
    def excluded_review(request: Request, rs: str, pid: str, csrf: str = Form(""), crit: str = Form(""),
                        note: str = Form("")) -> Response:  # fmt: skip
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rid, _job = apply_review(sess, request.url.path, rs, pid, crit, note)
        return RedirectResponse(f"/studies/{rid}/not-matched?done=sent#x-{pid[:8]}", status_code=303)

    @app.post("/api/v1/studies/{rs}/not-matched/{pid}/review")
    @page_twin("/studies/{rs}/excluded/{pid}/review")  # the page's old path, the same handler (T-657)
    async def api_excluded_review(request: Request, rs: str, pid: str) -> dict[str, Any]:
        """The page's "send to review" for the apps (T-310a): the session is checked before the body is read."""
        sess = api_session(request)
        body = await json_body(request)
        rid, job_id = apply_review(sess, request.url.path, rs, pid, str(body.get("crit") or ""),
                                   str(body.get("note") or ""))  # fmt: skip
        return {"study": rid, "pid": pid, "job_id": job_id, "sent_back": True}

    # ------------------------------------------------------------------ amendment re-screen list (D-364, LIFE-010)
    def rescreen_bundle(sess: Session, rid: str) -> dict[str, Any]:
        """The latest list (a new criteria version) against the latest list of an earlier version."""
        wk = week_bundle(sess, rid)
        cl = (wk or {}).get("cl") or None
        version = str((cl or {}).get("version") or "")
        if wk is None or not version:
            return {"rows": [], "version": version, "prev": "", "job": None}
        jobs = [j for j in bk.list_jobs(limit=500) if j.ruleset == rid and j.type in SCREEN_TYPES and j.state == "done"]
        older = [j for j in jobs if j.ruleset_version and st.semver(j.ruleset_version) < st.semver(version)]
        old_job = max(older, key=lambda j: (j.updated_at or j.received_at, j.job_id), default=None)
        old = load(old_job, "candidate_list_", ".json") if old_job is not None else None
        gone = h.gone()  # D-273 (PV-4): an opted-out patient is on no list
        reg = {p: s for p, s in registry_map(rid).items() if p not in gone}
        rows = st.rescreen_list(cl, store.latest_marks(rid), reg, crit_of(rid, sess.lang), old)
        prev = str((old or {}).get("version") or "")
        return {"rows": rows, "version": version, "prev": prev, "job": wk["job"]}

    @app.get("/studies/{rs}/rescreen")
    def rescreen(request: Request, rs: str) -> Response:
        sess = h.need(request)
        rid = need_excluded(sess, rs, request.url.path)
        b = rescreen_bundle(sess, rid)
        groups = {g: [r for r in b["rows"] if r["group"] == g] for g in st.RESCREEN_GROUPS}
        au.append("console.view", ruleset=rid, actor=h.actor(sess),
                  detail={"page": "rescreen", "rows": len(b["rows"]), "version": b["version"]})  # fmt: skip
        return h.page(request, "rescreen.html", sess, rs=rid, groups=groups, n=len(b["rows"]), version=b["version"],
                      prev=b["prev"], job=b["job"])  # fmt: skip

    h.patient_ctx = patient_ctx

    def approach_by(rid: str) -> str:
        """T-516 (UX-015): the name of the study's PI in the delegation log today, or "" when the log names none."""
        pi = h.team.pi_of(rid, h.today()) if h.team is not None else None
        return str(pi.name or pi.username or "") if pi is not None else ""

    def referral_wait(rid: str, pid: str) -> Any:
        """The patient's latest referral when it is not agreed (asked, discuss or declined), else None."""
        if h.team is None:
            return None
        refs = h.team.referrals(rid, pid)
        return refs[-1] if refs and refs[-1].state != "agreed" else None

    @app.get("/studies/{rs}/patients/{pid}")
    def patient(request: Request, rs: str, pid: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        # D-280 (OD-5), T-309 (D-430): an account outside its own rights opens one patient only under a break-glass
        # grant for that patient (the administrator always; an investigator the delegation log does not reach)
        grant = None
        if not h.reads(sess.user, rid):
            grant = h.breakglass(sess, ruleset=rid, pid=pid, what="patient page") if h.breakglass else None
            if grant is None:
                if sess.user.can_view_phi:
                    screen_or_403(sess, rid, request.url.path)  # the delegation refusal, audited
                raise h.problem(403, "forbidden")
        return h.page(request, "patient.html", sess, **patient_ctx(sess, rid, pid), breakglass=grant)

    # T-103 (D-438): the one reveal path; every surface below and in console.team / console.app calls it
    h.reveal = Reveal(h, study_or_404)

    @app.post("/studies/{rs}/patients/{pid}/reveal")
    def patient_reveal(request: Request, rs: str, pid: str, csrf: str = Form(""), reason: str = Form(""),
                       note: str = Form("")) -> Response:  # fmt: skip
        """One chart number, shown once, audited on both sides (D-99, D-143)."""
        sess = h.need(request)
        study_or_404(sess, rs)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        got = h.reveal.identifier(sess, rs, pid, "patient", reason, note=note, path=request.url.path)
        return h.page(request, "patient.html", sess, **{**got.ctx, "mrn": got.mrn})

    def back_to(rid: str, pid: str, back: str, done: str) -> str:
        if back == "patient":
            return f"/studies/{rid}/patients/{pid}?done={done}"
        lst = back.removeprefix("list:") if back.startswith("list:") else ""
        lst = lst if lst in st.WORKLISTS else "all"
        return f"/studies/{rid}/week?list={lst}&pid={pid}&done={done}#chart"

    def contact_or_refuse(sess: Session, rid: str, wk: dict[str, Any] | None, pid: str, action: str) -> None:
        """FIT-U04 (T-629, D-415): nothing is recorded for a patient whose record now says they died (the page and
        ``/api/v1`` alike); while the death records cannot be read, no Approach and no contact outcome. Audited."""
        if wk is None:
            return
        why = ""
        if pid in (wk.get("deceased") or ()):
            why, key, status = "deceased", "patient.deceased", 409
        elif wk.get("dead_unchecked") and (action == "approach" or action in OUTCOMES):
            why, key, status = "death records unreadable", "patient.death_unchecked", 503
        if why:
            au.append("console.refused", ruleset=rid, actor=h.actor(sess),
                      detail={"pid": pid, "action": action, "reason": why})  # fmt: skip
            raise h.problem(status, key)

    def apply_mark(
        sess: Session,
        path: str,
        rs: str,
        pid: str,
        mark: str,
        reason: str,
        recheck: str,
        note: str,
    ) -> tuple[str, str, dict[str, Any]]:
        """One mark (D-108, FR-SCR-07), the same for the page and ``/api/v1``. Returns (study, stored mark, detail).

        D-147: Approach needs the "approach" task of the delegation log, the other marks "screen"; while the
        patient's referral waits or was declined, Approach is refused (the PI contacts the patient only after the
        treating doctor agreed); a missing or expired IRB approval or consent-form version is a warning shown before
        Approach, never a gate: an Approach marked under it is recorded as an override with the marker's name."""
        rid = study_or_404(sess, rs)
        task = "approach" if mark == "approach" else "screen"
        if not sess.user.can_mark or not h.permit(sess.user, f"task.{task}", rid):
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        if mark not in (*MARKS, "withdraw", "undo") or not _PID.match(pid):
            raise h.problem(400, "request.refused", reason="choose Approach, Need info, Not suitable now or Not now")
        conf = settings_of(rid)
        if mark == "not_suitable" and reason not in conf.reasons:
            # D-133 (review F-03): a medical reason is never guessed (it used to fall back to "other"); no reason,
            # no mark, on the page and on /api/v1 alike
            raise h.problem(400, "mark.reason_needed")
        wk = week_bundle(sess, rid)
        contact_or_refuse(sess, rid, wk, pid, mark)
        if wk is None or not any(str(r.get("pid")) == pid for r in (wk["cl"] or {}).get("rows") or []):
            raise h.problem(404, "notfound")
        today = h.today()
        prev = store.latest_marks(rid).get(pid)
        stored_reason: str | None = None
        stored_note = note.strip()[:300] or None
        undone: str | None = None
        if mark == "undo":  # D-133: the toast's Undo puts back the state before this user's last mark
            hist = store.mark_history(rid, pid)
            if not hist or hist[-1].by != sess.user.username:
                raise h.problem(409, "mark.undo_none")
            undone = hist[-1].mark
            before: Mark | None = None
            for m in hist[:-1]:
                before = None if m.mark == WITHDRAWN else m
            if before is None:
                mark, stored_note = "withdraw", None
            else:
                mark, stored_reason, stored_note = before.mark, before.reason, before.note
        elif mark == "not_suitable":
            stored_reason = reason
        elif mark == "not_now":
            try:
                when = date.fromisoformat(recheck) if recheck else today + timedelta(days=28)
            except ValueError as exc:
                raise h.problem(400, "request.refused", reason="give the re-check date as YYYY-MM-DD") from exc
            if not today < when <= today + timedelta(days=366):
                raise h.problem(400, "request.refused", reason="the re-check date must be within the next year")
            stored_reason = when.isoformat()
        elif mark == "withdraw" and prev is None:
            raise h.problem(409, "request.refused", reason="there is no mark to withdraw")
        warned: list[str] = []
        if mark == "approach":
            waiting = referral_wait(rid, pid)
            if waiting is not None:
                au.append("console.refused", ruleset=rid, actor=h.actor(sess),
                          detail={"pid": pid, "action": "approach", "reason": f"referral {waiting.state}"})  # fmt: skip
                raise h.problem(409, "approach.wait_referral")
            # a warning, not a gate (owner decision 2026-11-09): marking Approach under the warning is the override
            warned = h.team.irb(rid).warnings(today) if h.team is not None else []
        now = h.clock().isoformat()
        value = WITHDRAWN if mark == "withdraw" else mark
        detail: dict[str, Any] = {"pid": pid, "action": value, "reason": stored_reason or ""}
        if undone is not None:
            detail["undo"] = undone
        if prev is not None:
            detail["from"] = prev.mark  # a replaced or withdrawn mark stays visible in the trail
        if warned:  # D-147: a warning, not a gate; each override is its own record and audit event
            detail["irb_override"] = ",".join(warned)

        def audit(no: str | None) -> None:
            """D-273 (CR-055, DI-5): the audit events are written inside the store's transaction, before it commits:
            a failed append rolls the mark and the screening number back, so no change is kept without its event."""
            if no is not None:  # FR-STUDY-08: the screening number is given when the PI approves contact
                detail["to"] = no
            if warned:
                au.append("console.approach_override", job_id=wk["job"].job_id, ruleset=rid, actor=h.actor(sess),
                          detail={"pid": pid, "action": "approach", "reason": ",".join(warned)})  # fmt: skip
            # D-989 (D-1152): inside the transaction too, so a mark is never kept without its events
            missing = approach_events(sess, rid, pid, prev, value, wk, version)
            if missing:
                detail["ai"] = missing
            au.append("console.pi_mark", job_id=wk["job"].job_id, ruleset=rid, actor=h.actor(sess), detail=detail)

        # D-364 (LIFE-010): the criteria version of the list the mark was made on
        version = str((wk.get("cl") or {}).get("version") or wk["job"].ruleset_version or "") or None
        if version:
            detail["version"] = version
        store.mark(rid, Mark(pid, value, stored_reason, stored_note, sess.user.username, now, wk["job"].job_id,
                             version), number=conf if mark == "approach" else None, before_commit=audit)  # fmt: skip
        if warned:  # the override record follows its audit event (an event without the record, never the reverse)
            h.team.add_override(rid, pid, warned, sess.user.username, now)
        return rid, value, detail

    def approach_events(sess: Session, rid: str, pid: str, prev: Mark | None, value: str, wk: dict[str, Any],
                        version: str | None) -> str:  # fmt: skip
        """D-989 (D-1152): an Approach that becomes the patient's mark confirms the model's answers of its list
        (``confirmed``); an Approach that stops being it (withdrawn, undone, replaced, or moved to a newer run's list
        by a new Approach) takes that back (``withdrawn``), naming the list it was made on. Every other mark decides
        nothing about the answers. Returns what could not be written ("" when all was), for the mark's own event."""
        was, now = prev is not None and prev.mark == "approach", value == "approach"
        new_list = (wk["job"].job_id, version or "")
        old_list = (prev.job_id or "", prev.version or "") if was and prev is not None else None
        if was and now and old_list == new_list:
            return ""  # an Approach on an Approach of the same list is no new decision
        missing = ""
        if old_list is not None:
            job, ver = old_list
            doc = wk["cl"] if job == wk["job"].job_id else load(bk.get_job(job) if job else None, "candidate_list_")
            row = ai_confirm.row_of(doc, pid) if ver else None
            if row is None:  # the confirmation's list is gone (or from before the version): said, never silent
                missing = f"withdrawn not written: the list of run {job} is not readable"
            else:
                ai_confirm.on_verdicts(au, ruleset=rid, version=ver, job=job, pid=pid,
                                       criteria=row.get("criteria") or [], by=sess.user.username,
                                       decision=ai_confirm.WITHDRAWN, job_id=job, actor=h.actor(sess))  # fmt: skip
        if now and version:
            row = ai_confirm.row_of(wk["cl"], pid)
            if row is not None:
                ai_confirm.on_verdicts(au, ruleset=rid, version=version, job=new_list[0], pid=pid,
                                       criteria=row.get("criteria") or [], by=sess.user.username,
                                       decision=ai_confirm.MARK_DECISION["approach"], job_id=new_list[0],
                                       actor=h.actor(sess))  # fmt: skip
        return missing

    @app.post("/studies/{rs}/patients/{pid}/mark")
    def patient_mark(
        request: Request,
        rs: str,
        pid: str,
        csrf: str = Form(""),
        mark: str = Form(""),
        reason: str = Form(""),
        recheck: str = Form(""),
        note: str = Form(""),
        back: str = Form(""),
    ) -> Response:
        """One mark vocabulary (D-108, FR-SCR-07): Approach / Need info / Not suitable now (a study reason) / Not now,
        re-check on a date. A new mark replaces the current one; ``withdraw`` takes the current mark back. Every mark
        is an event; the history keeps them all."""
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rid, value, _ = apply_mark(sess, request.url.path, rs, pid, mark, reason, recheck, note)
        return RedirectResponse(back_to(rid, pid, back, "undo" if mark == "undo" else value), status_code=303)

    def contact_rule(rid: str) -> dict[str, Any]:
        """The study's contact-attempt rule from the lifecycle (D-407); the default when the store does not answer."""
        try:
            row = s28.call(bk, "GET", f"/studies/{rid}/contact-rule") if s28.has_api(bk) else None
        except (Problem, Unavailable):
            row = None
        if not isinstance(row, dict):
            return {"max_attempts": CONTACT_DEFAULT[0], "min_days": CONTACT_DEFAULT[1], "set_by": "", "set_at": ""}
        return row

    def contact_state(rid: str, pid: str, today: date, rule: dict[str, Any] | None = None) -> dict[str, Any]:
        """D-407 (LIFE-017): attempts so far against the study's limit (``why``: "", ``limit``, ``too_soon``)."""
        r = rule or contact_rule(rid)
        days = [local_date(o.at, site_zone(bk)) for o in store.outcomes(rid, pid) if o.outcome in CONTACT_ATTEMPTS]
        return contact_check(days, int(r["max_attempts"]), int(r["min_days"]), today)

    def registry_signer(sess: Session, rid: str) -> Any:
        """T-715b (D-550): a contact outcome moves the registry's row, and the registry takes its person from the
        signed claim of the call: this person's, for this study and this request (`request.prepare`, the right
        the outcome already asks)."""
        from console import actor as acting

        def sign(method: str, path: str, body: Any) -> dict[str, str]:
            return acting.assert_for(h, sess, "request.prepare", rid, method, path, body)

        return sign

    def apply_outcome(
        sess: Session, path: str, rs: str, pid: str, outcome: str, retry: str, note: str
    ) -> tuple[str, str | None]:
        """A contact outcome (FR-SCR-10c), the same for the page and ``/api/v1``. Returns (study, screening number)."""
        rid = study_or_404(sess, rs)
        if not sess.user.can_request:
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        if (outcome not in OUTCOMES and outcome != "undo") or not _PID.match(pid):
            raise h.problem(400, "request.refused", reason="choose one of the contact outcomes")
        wk = week_bundle(sess, rid)
        if outcome != "undo":
            contact_or_refuse(sess, rid, wk, pid, outcome)
        if wk is None or not any(str(r.get("pid")) == pid for r in (wk["cl"] or {}).get("rows") or []):
            raise h.problem(404, "notfound")
        if outcome == "undo":
            return undo_outcome(sess, rid, pid, wk["job"].job_id)
        # D-1221 (walk finding F-13): no contact step in a closed study, nor for a participant, as on the page
        if store.study_state(rid).state == "closed":
            au.append("console.refused", ruleset=rid, actor=h.actor(sess),
                      detail={"pid": pid, "action": outcome, "reason": "study closed"})  # fmt: skip
            raise h.problem(409, "outcome.closed")
        who: ps.PersonState | None = wk["people"].of(pid)
        if who is not None and who.name == ps.UNKNOWN:
            # the participant records could not be read: before consent the screening log decides, as on master;
            # with the log unread too, nothing is recorded (503: try again)
            who = wk["people"].log_state(pid)
        if who is None:
            au.append("console.refused", ruleset=rid, actor=h.actor(sess),
                      detail={"pid": pid, "action": outcome, "reason": "state unavailable"})  # fmt: skip
            raise h.problem(503, "outcome.state_unknown")
        if who.phase == "participant":
            au.append("console.refused", ruleset=rid, actor=h.actor(sess),
                      detail={"pid": pid, "action": outcome, "reason": f"state {who.name}"})  # fmt: skip
            raise h.problem(409, "outcome.participant")
        mk = store.latest_marks(rid).get(pid)
        if mk is None or mk.mark != "approach":
            # D-133 (review F-36): the coordinator calls a patient only after the investigator's "OK to contact";
            # refused here, so the page and /api/v1 refuse alike
            au.append("console.refused", ruleset=rid, actor=h.actor(sess),
                      detail={"pid": pid, "action": outcome, "reason": "no approach mark"})  # fmt: skip
            raise h.problem(409, "outcome.wait_pi")
        waiting = referral_wait(rid, pid)
        if waiting is not None:
            # T-516 (UX-013): a referral asked after Approach pauses it; the call waits for the doctor's agreement
            paused = f"approach paused: referral {waiting.state}"
            au.append("console.refused", ruleset=rid, actor=h.actor(sess),
                      detail={"pid": pid, "action": outcome, "reason": paused})  # fmt: skip
            raise h.problem(409, "outcome.wait_referral")
        today = h.today()
        if outcome in CONTACT_ATTEMPTS:
            # D-407 (LIFE-017): the study's contact-attempt limit and the days between attempts; after the limit the
            # investigator decides what follows, so the page and /api/v1 refuse alike with a plain reason
            chk = contact_state(rid, pid, today)
            if chk["why"]:
                au.append("console.refused", ruleset=rid, actor=h.actor(sess),
                          detail={"pid": pid, "action": outcome, "reason": f"contact {chk['why']}",
                                  "attempts": chk["attempts"], "max": chk["max"]})  # fmt: skip
                key = "outcome.limit" if chk["why"] == "limit" else "outcome.too_soon"
                raise h.problem(409, key, n=chk["attempts"], max=chk["max"], next=chk["next"])
        retry_on: str | None = None
        if outcome == "not_reached":
            try:
                retry_on = (date.fromisoformat(retry) if retry else today + timedelta(days=2)).isoformat()
            except ValueError as exc:
                raise h.problem(400, "request.refused", reason="give the retry date as YYYY-MM-DD") from exc
        now = h.clock().isoformat()
        status, why = OUTCOMES[outcome]
        current = registry_map(rid).get(pid)
        if status is not None and status != current:
            from tb_contracts import RegistryUpdate

            try:
                bk.registry_update(
                    rid,
                    RegistryUpdate(
                        pid=pid,  # status: one of the registry statuses in sitestore.OUTCOMES
                        status=cast(Any, status),
                        reason=why,
                        by=h.actor(sess),
                        source="manual",
                        source_job=wk["job"].job_id,
                    ),
                    registry_signer(sess, rid),
                )
            except Refused as exc:
                raise h.problem(409, "request.refused", reason=str(exc)) from exc
        store.add_outcome(rid, Outcome(pid, outcome, retry_on, note.strip()[:300] or None, sess.user.username, now),
                          prev_status=current)  # fmt: skip
        no = store.assign_screening_no(rid, pid, settings_of(rid), now)  # everyone approached is on the log
        au.append(
            "console.contact_outcome",
            job_id=wk["job"].job_id,
            ruleset=rid,
            actor=h.actor(sess),
            detail={"pid": pid, "action": outcome, "to": status or current or "", "reason": why or "", "run": no},
        )
        return rid, no

    def undo_outcome(sess: Session, rid: str, pid: str, job_id: str) -> tuple[str, str | None]:
        """D-178 (review J-14): the toast's Undo takes back this person's latest contact outcome of the patient, and
        the registry status it set goes back to the one before (``candidate`` when the patient had none)."""
        now = h.clock().isoformat()
        got = store.undo_outcome(rid, pid, sess.user.username, now)
        if got is None:
            raise h.problem(409, "outcome.undo_none")
        undone, prev = got
        status, _ = OUTCOMES[undone.outcome]
        back_to_status = prev or "candidate"
        if status is not None and status != back_to_status and registry_map(rid).get(pid) == status:
            from tb_contracts import RegistryUpdate

            try:
                bk.registry_update(rid, RegistryUpdate(pid=pid, status=cast(Any, back_to_status),
                                                       reason="contact outcome undone", by=h.actor(sess),
                                                       source="manual", source_job=job_id),
                                   registry_signer(sess, rid))  # fmt: skip
            except Refused as exc:  # the outcome stays in force: the registry and the outcomes never disagree
                store.restore_outcome(rid, undone, now)
                raise h.problem(409, "request.refused", reason=str(exc)) from exc
        detail = {"pid": pid, "action": "undo", "undo": undone.outcome, "to": back_to_status if status else ""}
        au.append("console.contact_outcome", job_id=job_id, ruleset=rid, actor=h.actor(sess), detail=detail)
        return rid, None

    @app.post("/studies/{rs}/patients/{pid}/outcome")
    def patient_outcome(
        request: Request,
        rs: str,
        pid: str,
        csrf: str = Form(""),
        outcome: str = Form(""),
        retry: str = Form(""),
        note: str = Form(""),
        back: str = Form(""),
        confirm: str = Form(""),
    ) -> Response:
        """A contact outcome in two taps (FR-SCR-10c, TB-DS-07 §4.1): the coordinator opens the patient and taps
        what happened. The registry status follows the mapping in ``sitestore.OUTCOMES``; "not reached" keeps the
        status and a retry date."""
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if outcome in CLOSING_OUTCOMES and confirm != "yes" and h.confirm is not None:
            # D-178 (review J-14): an outcome that ends the contact names its consequence first
            rid = study_or_404(sess, rs)
            text = translate(sess.lang, f"confirm.outcome.{outcome}")
            return h.confirm(request, sess, text, request.url.path,
                             {"outcome": outcome, "retry": retry, "note": note, "back": back},
                             f"/studies/{rid}/patients/{pid}")  # fmt: skip
        rid, _ = apply_outcome(sess, request.url.path, rs, pid, outcome, retry, note)
        return RedirectResponse(back_to(rid, pid, back, "outcome_undo" if outcome == "undo" else outcome),
                                status_code=303)  # fmt: skip

    # ------------------------------------------------------------------ /api/v1 (D-125, D-127; review F-07)
    # The same actions as the pages, for the phone and desktop apps and other systems. Sign-in gives a bearer token
    # (a console session: same expiry, lockout and audit); no cookie, so no CSRF. Versioned: a breaking change is v2.
    def api_session(request: Request) -> Session:
        auth = request.headers.get("authorization") or ""
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        # T-505a (D-320, ROLE-001): only a token this route gave; a page's cookie is no bearer token
        sess: Session | None = h.users.session(token, api=True) if token else None
        if sess is None:
            raise h.problem(401, "login")
        if h.users.must_change(sess.user.username):  # D-279 (SEC-1): the owner replaces the password on the page
            raise h.problem(403, "account.must_change")
        if h.scope_check is not None:  # D-146 (J-03): the API refuses what the page refuses, in one place
            h.scope_check(request, sess)
        bind_session(sess.token_sha[:16])  # S-09: the actor sent to the orchestrator is signed with this session
        console_actor.bind_reader(h, sess)  # NEW-SEC-1 (D-717): this account signs the patient reads of the API
        return sess

    h.api_session = api_session  # the other /api/v1 routes (console.data_pages) sign in the same way

    @app.post("/api/v1/session")
    def api_login(body: ApiLogin, request: Request) -> dict[str, Any]:
        # D-279 (SEC-9, ROLE-006): the same per-address count as the page; a busy address waits (429), no account
        # is locked by someone else's guesses.
        src = source_of(request.client.host if request.client else None)
        wait = h.users.throttled(src)
        if wait:
            au.append("console.login_failed", actor=f"console:{body.username[:60]}",
                      detail={"via": "api", "reason": "slowed", "source": src})  # fmt: skip
            raise h.problem(429, "login.slowed", n=wait)
        ident = h.identity
        totp_on = ident is not None and ident.settings.totp_required
        # D-192: with a code to come, a right password does not reset the count of wrong codes
        user = h.users.authenticate(body.username, body.password, clear_failures=not totp_on, source=src)
        if user is None:
            au.append("console.login_failed", actor=f"console:{body.username[:60]}",
                      detail={"via": "api", "source": src})  # fmt: skip
            if ident is not None:
                ident.after_failure(body.username, src)
            raise h.problem(401, "login")
        via = "api"
        if totp_on and ident.needs_code(user):
            # T-505a (D-320, ROLE-001): the same two factors as the page, in one call. A password alone opens
            # nothing; a wrong or replayed code is a failed sign-in from this address, as on /login/totp.
            if not body.code.strip():
                au.append("console.login_failed", actor=f"console:{user.username}",
                          detail={"via": "api", "factor": "totp", "reason": "no_code", "source": src})  # fmt: skip
                raise h.problem(401, "login.code")
            reason = ident.step_up(user.username, body.code, src)
            if reason:
                au.append("console.login_failed", actor=f"console:{user.username}",
                          detail={"via": "api", "factor": "totp", "reason": reason, "source": src})  # fmt: skip
                if reason == "none":  # no authenticator yet: it is enrolled on the sign-in page, never here
                    raise h.problem(403, "login.enrol")
                if reason == "key":
                    key_refused = "the authenticator key file does not match; ask an administrator"  # refusals.py
                    raise h.problem(503, "request.refused", reason=key_refused)
                raise h.problem(401, "login")
            via = "api+totp"
        if totp_on:
            h.users.clear_failures(user.username, src)
        if h.users.must_change(user.username):  # D-279 (SEC-1): no API session on a password someone else set
            au.append("console.login_failed", actor=f"console:{user.username}",
                      detail={"via": "api", "reason": "must_change"})  # fmt: skip
            raise h.problem(403, "account.must_change")
        token, sess = h.users.new_session(user, body.lang if body.lang in ("ja", "zh-TW", "en") else "en", via)
        au.append("console.login", actor=f"console:{user.username}", detail={"role": user.role, "via": via})
        return {"token": token, "username": user.username, "role": user.role,
                "expires": getattr(sess, "expires", None)}  # fmt: skip

    @app.delete("/api/v1/session")
    def api_logout(request: Request) -> dict[str, bool]:
        auth = request.headers.get("authorization") or ""
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if h.users.session(token, touch=False, api=True) is not None:  # D-320: a page's session ends on its page
            h.users.end_session(token)
        return {"ok": True}

    @app.get("/api/v1/studies")
    def api_studies(request: Request) -> list[dict[str, Any]]:
        sess = api_session(request)
        return [{"id": r.id, "version": getattr(r, "version", None), "kind": r.kind} for r in trials(sess)]

    def rows_or_403(sess: Session, rs: str, path: str) -> str:
        """A study this account sees, for a role that reads patient-level rows; the same check as the page (D-146)."""
        rid = study_or_404(sess, rs)
        h.need_rows(sess, rid, path)  # D-273 (PV-3), ROLE-017: the page's rule on /api/v1 too
        return rid

    @app.get("/api/v1/studies/{rs}/patients")
    def api_patients(request: Request, rs: str) -> dict[str, Any]:
        """This week's list: pseudonyms, tiers, current marks and screening numbers (no chart numbers)."""
        sess = api_session(request)
        rid = rows_or_403(sess, rs, request.url.path)
        wk = week_bundle(sess, rid)
        rows = list((wk or {}).get("cl", {}).get("rows") or []) if wk else []
        marks = store.latest_marks(rid)
        numbers = store.screening_nos(rid)
        return {
            "study": rid,
            "job_id": wk["job"].job_id if wk else None,
            "patients": [
                {
                    "pid": str(r.get("pid")),
                    "tier": r.get("tier"),
                    "mark": marks[str(r.get("pid"))].mark if str(r.get("pid")) in marks else None,
                    "screening_no": numbers.get(str(r.get("pid"))),
                }
                for r in rows
            ],
        }

    # T-657 (D-444): the handlers' own first checks, run before the body is read (console.api_first)
    def first_study(sess: Session, request: Request) -> None:
        study_or_404(sess, request.path_params["rs"])

    def first_mark(sess: Session, request: Request) -> None:
        rid = study_or_404(sess, request.path_params["rs"])
        if not sess.user.can_mark or not any(h.permit(sess.user, f"task.{t}", rid) for t in ("approach", "screen")):
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")  # the body picks the task (apply_mark asks that one)

    def first_outcome(sess: Session, request: Request) -> None:
        study_or_404(sess, request.path_params["rs"])
        if not sess.user.can_request:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")

    @app.post("/api/v1/studies/{rs}/patients/{pid}/mark")
    @before_body(first_mark)
    def api_mark(request: Request, rs: str, pid: str, body: ApiMark) -> dict[str, Any]:
        sess = api_session(request)
        rid, value, detail = apply_mark(
            sess, request.url.path, rs, pid, body.mark, body.reason, body.recheck, body.note
        )
        return {"study": rid, "pid": pid, "mark": value, "screening_no": detail.get("to"),
                "irb_override": detail.get("irb_override") or None}  # fmt: skip

    @app.post("/api/v1/studies/{rs}/patients/{pid}/outcome")
    @before_body(first_outcome)
    def api_outcome(request: Request, rs: str, pid: str, body: ApiOutcome) -> dict[str, Any]:
        sess = api_session(request)
        rid, no = apply_outcome(sess, request.url.path, rs, pid, body.outcome, body.retry, body.note)
        return {"study": rid, "pid": pid, "outcome": body.outcome, "screening_no": no}

    @app.post("/api/v1/studies/{rs}/patients/{pid}/reveal")
    @before_body(first_study)  # the rest of the one reveal path (break-glass grants) needs the patient: in the handler
    @page_twin("/studies/{rs}/candidates/{pid}/reveal", "/studies/{rs}/referrals/{ref_id}/print")  # one reveal path
    def api_reveal(request: Request, rs: str, pid: str, body: ApiReveal) -> dict[str, Any]:
        """The chart number of one listed patient for an account with identifier authority (D-143), audited and
        rate-limited exactly as on the patient page."""
        sess = api_session(request)
        got = h.reveal.identifier(sess, rs, pid, "patient", body.reason, note=body.note, via="api",
                                  path=request.url.path)  # fmt: skip
        return {"study": rs.strip().upper(), "pid": pid, "mrn": got.mrn or None}

    @app.get("/api/v1/studies/{rs}/screening-log")
    def api_screening_log(request: Request, rs: str) -> list[dict[str, Any]]:
        sess = api_session(request)
        rid = rows_or_403(sess, rs, request.url.path)
        # D-147: never an opted-out patient's pseudonym. NEW-LIFE-5 (D-762): a numbered one keeps the row, with
        # the day of the opt-out ("yes" for a merged chart) and nothing of the contact work, as on the page
        gone = h.opted_out_on()
        refs = h.team.latest_referrals(rid) if h.team is not None else {}
        return [
            {"pid": "", "screening_no": b, "at": c, "referral_route": "", "referral_outcome": "",
             "opted_out": gone[a] or "yes"} if a in gone else
            {"pid": a, "screening_no": b, "at": c, "referral_route": refs[a].route if a in refs else "",
             "referral_outcome": refs[a].state if a in refs else "", "opted_out": ""}
            for a, b, c in store.screening_rows(rid)
        ]  # fmt: skip
