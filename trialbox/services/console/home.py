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
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from tb_common.service_auth import bind_session, scope_of
from tb_contracts import Job

from console import s28
from console import studies as st
from console.auth import REVEAL_REASONS, Session, reveal_reason, source_of
from console.backend import Refused
from console.i18n import translate
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
REVEAL_NOTE_MIN = 10  # D-273 (ROLE-016): the written "why" a reveal for "other" needs, in characters
_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
SCREEN_TYPES = ("MICROBATCH", "SCREEN")


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
    trials: Callable[..., list[Any]] | None = None
    settings_of: Callable[[str], StudySettings] | None = None
    api_session: Callable[[Request], Session] | None = None  # set by register(): bearer sign-in for /api/v1
    # set by console.lifecycle_pages (D-134): the home page's visits and serious AEs; the visits for N1/N2
    life_home: Callable[[Session], dict[str, Any]] | None = None
    life_mail: Callable[[str, date], dict[str, Any]] | None = None
    life_sae: Callable[[str], list[dict[str, Any]]] | None = None  # one study's unacknowledged SAEs (the week page)
    life_reports: Callable[[str], list[dict[str, Any]]] | None = None  # one study's overdue SAE reports (P-03)
    # P-10 (D-143): one confirmation page before an action that is hard to take back
    confirm: Callable[..., Response] | None = None
    # D-146 (review J-03): the role and study scope rules of every page, applied to /api/v1 calls too
    scope_check: Callable[[Request, Session], None] | None = None
    # set by register(): read again by console.team (D-147)
    crit_of: Callable[..., dict[str, Any]] | None = None
    registry_map: Callable[[str], dict[str, str]] | None = None
    patient_ctx: Callable[..., dict[str, Any]] | None = None
    # set by console.team (D-147): the study team store, the opt-out register and the one permission function
    team: Any = None
    optout: Any = None
    may: Callable[..., bool] | None = None
    may_approve: Callable[..., bool] | None = None
    team_due: Callable[[str], bool] | None = None
    apply_reveal: Callable[..., tuple[dict[str, Any], str]] | None = None  # set by register(): D-143's reveal
    chart_lookup: Callable[[Session, str], None] | None = None  # set by console.team: the lookup cap (D-273)
    ops_summary: Callable[[], dict[str, Any]] | None = None  # set by console.ops_pages (D-178): the health tile
    identity: Any = None  # console.identity.Identity (D-279): the second factor at signing; None in bare test apps

    def gone(self) -> set[str]:
        """D-273 (PV-4): the pseudonyms on the opt-out register now. Every patient-level reader (lists, the excluded
        list, the job page, the registry) leaves them out; who opted out is itself private, so callers show counts."""
        return set(self.optout.active()) if self.optout is not None else set()

    def delegated(self, sess: Session, rid: str, path: str, tasks: tuple[str, ...] = ("screen",)) -> None:
        """D-273 (PV-3): D-147's delegation rule on every page that shows one study's patients, not only the week,
        patient, candidate and SAE pages. Once the study's delegation log names a PI, an investigator sees them only
        as the PI or as a sub-investigator ticked for one of ``tasks``; a refusal is audited."""
        if not self.delegated_ok(sess.user, rid, tasks):
            self.au.append("console.denied", actor=self.actor(sess), detail={"action": path[:80]})
            raise self.problem(403, "forbidden")

    def delegated_ok(self, user: Any, rid: str | None, tasks: tuple[str, ...] = ("screen",)) -> bool:
        """The rule of :meth:`delegated` as a yes or no, for a page that hides a part instead of refusing."""
        if user.role != "investigator" or self.may is None:
            return True
        return bool(rid) and any(self.may(user, rid, t) for t in tasks)

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


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store

    # ------------------------------------------------------------------ helpers
    def trials(sess: Session) -> list[Any]:
        return [
            r
            for r in bk.rulesets()
            if r.status == "approved" and r.kind in ("trial", "") and sess.user.sees_study(r.id)
        ]

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
            data = json.loads(bk.get_object(out.minio_key))
        except (KeyError, ValueError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def registry_map(rs: str) -> dict[str, str]:
        try:
            return {e.pid: e.status for e in bk.registry_rows(rs)}
        except Exception:
            return {}

    def registry_counts(rs: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in registry_map(rs).values():
            out[s] = out.get(s, 0) + 1
        return out

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

    def week_bundle(sess: Session, rs: str) -> dict[str, Any] | None:
        jobs = bk.list_jobs(limit=500)
        job = st.latest_job(jobs, rs, SCREEN_TYPES)
        if job is None:
            return None
        cl = load(job, "candidate_list_", ".json")
        removed: list[str] = []
        if cl is not None and h.optout is not None:  # D-147: an opted-out patient is on no list, page or mail
            out = h.optout.active()
            removed = [str(r.get("pid")) for r in cl.get("rows") or [] if str(r.get("pid")) in out]
            if removed:
                cl = {**cl, "rows": [r for r in cl.get("rows") or [] if str(r.get("pid")) not in out]}
        summary = load(job, "screen_", ".json")
        names = (summary or {}).get("practitioner_names") or {}
        pids = [str(r.get("pid")) for r in (cl or {}).get("rows") or [] if r.get("tier") in ("high", "review")]
        seen = store.seen(rs, pids, job.job_id, (job.updated_at or job.received_at).isoformat())
        rows = st.weekly_rows(
            cl,
            crit_of(rs, sess.lang if sess else "en"),
            registry_map(rs),
            store.latest_marks(rs),
            seen,
            job.job_id,
            names,
            today=h.today(),
        )
        return {"job": job, "rows": rows, "counts": st.week_counts(rows), "summary": summary or {}, "cl": cl,
                "removed": removed}  # fmt: skip

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
        regc = registry_counts(rs)
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
            if mk is not None and mk.mark == "approach" and reg.get(w["pid"]) in (None, "candidate"):
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
            "step": study_step(rs),
            "pipeline": st.pipeline_counts(rows, reg),
            "tasks": tasks,
            "clinic": clinic,
            "feas": feas,
            "feas_job": feas_job,
            "week": week,
            "registry": regc,
            "site_missing": site.missing,
            "next": nxt,
        }

    # the notices (console.notify) read the same rows as the pages
    h.week_bundle = week_bundle
    h.trials = trials
    h.settings_of = settings_of
    h.crit_of = crit_of
    h.registry_map = registry_map

    def screen_or_403(sess: Session, rid: str, path: str) -> None:
        """D-147: once a study's delegation log names a PI, an investigator sees its patients only as the PI or a
        sub-investigator the PI ticked "screen" for (the one rule, ``Helpers.delegated``, D-273)."""
        h.delegated(sess, rid, path)

    # ------------------------------------------------------------------ homes
    @app.get("/home")
    def home(request: Request, view: str = "") -> Response:
        sess = h.need(request)
        role = sess.user.role
        if role == "investigator":
            return RedirectResponse("/week", status_code=303)
        if role in ("cro", "viewer"):
            return RedirectResponse("/reports", status_code=303)
        if role == "admin" and view != "studies":
            admin_page = getattr(h, "admin_page", None)  # step 4: S13 with its tabs (console.step4)
            return admin_page(request, sess, "health") if admin_page else admin_home(request, sess)
        jobs = bk.list_jobs(limit=500)
        cards = [study_card(sess, r, jobs) for r in trials(sess)]
        tasks = sorted((tk for c in cards for tk in c["tasks"]), key=lambda tk: (tk["due"], tk["rs"]))
        clinic = sorted((v for c in cards for v in c["clinic"]), key=lambda v: v["visit_text"])
        return h.page(
            request, "home_crc.html", sess, cards=cards, tasks=tasks, clinic=clinic, steps=st.STEPS,
            pipeline_keys=st.PIPELINE, models=bk.models(), life=h.life_home(sess) if h.life_home else None,
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
                    sponsor=sess.user.role == "cro",
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
        sponsor = view == "sponsor" or sess.user.role == "cro"
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
            saved=saved == "1",
            refreshed=refreshed == "1",
            registry=next((r.kind for r in bk.rulesets() if r.id == rid), "") in st.REGISTRY_KINDS,
        )

    @app.post("/studies/{rs}/feasibility/refresh")
    def feasibility_refresh(request: Request, rs: str, csrf: str = Form("")) -> Response:
        """FR-FEAS-13: run the study's feasibility again on today's snapshot, with the approved criteria."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.can_request or h.submit is None:
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
                sel = patient_ctx(sess, rid, pid)
            except Exception as exc:  # h.problem(404): a pid not on this run's list opens the first row instead
                if getattr(exc, "status", 0) != 404:
                    raise
                pid, opened = rows[0]["pid"], False
                sel = patient_ctx(sess, rid, pid)
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
            quick_outcomes=tuple(OUTCOMES) if sess.user.can_request and not sess.user.can_mark else (),
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
            team_due=bool(h.team_due and h.team_due(rid)),
        )

    def study_step(rid: str) -> int:
        jobs = bk.list_jobs(limit=500)
        regc = registry_counts(rid)
        return st.procedure_step(
            approved=any(r.id == rid and r.status == "approved" for r in bk.rulesets()),
            feas_done=st.latest_job(jobs, rid, ("FEAS",)) is not None,
            screen_done=st.latest_job(jobs, rid, SCREEN_TYPES) is not None,
            contacted=sum(v for k, v in regc.items() if k != "candidate"),
            enrolled=regc.get("enrolled", 0),
            waiting=st.latest_job(jobs, rid, ("FEAS", "SCREEN", "COMPILE"), state="awaiting_approval") is not None,
        )

    def patient_ctx(sess: Session, rid: str, pid: str) -> dict[str, Any]:
        if not _PID.match(pid):
            raise h.problem(404, "notfound")
        wk = week_bundle(sess, rid)
        if wk is None:
            raise h.problem(404, "notfound")
        row = next((r for r in (wk["cl"] or {}).get("rows") or [] if str(r.get("pid")) == pid), None)
        if row is None:
            raise h.problem(404, "notfound")
        crit = crit_of(rid, sess.lang)
        listed = next((r for r in wk["rows"] if r["pid"] == pid), None)
        names = (wk["summary"] or {}).get("practitioner_names") or {}
        return {
            "rs": rid,
            "pid": pid,
            "job": wk["job"],
            "row": row,
            "listed": listed,
            "fit": st.fit_facts(row.get("criteria") or [], crit),
            "crits": st.patient_rows(row.get("criteria") or [], crit),
            "practitioner": names.get(row.get("practitioner_id") or "", row.get("practitioner_id") or ""),
            "history": store.mark_history(rid, pid),
            "registry": registry_map(rid).get(pid),
            "judging": (wk["cl"] or {}).get("judging") or {},
            "marks": MARKS,
            "reasons": settings_of(rid).reasons,
            "mark": store.latest_marks(rid).get(pid),
            "screening_no": store.screening_no(rid, pid),
            "outcomes": store.outcomes(rid, pid),
            "outcome_keys": tuple(OUTCOMES),
            "today": h.today(),
            "mrn": None,
            # D-147: the IRB/consent-form warning before Approach, who may mark Approach, a referral still waiting
            "irb_warn": h.team.irb(rid).warnings(h.today()) if h.team is not None else [],
            "may_approach": sess.user.can_mark and (h.may is None or h.may(sess.user, rid, "approach")),
            "ref_wait": referral_wait(rid, pid),
        }

    # ------------------------------------------------------------------ excluded patients and why (P-04, D-143)
    ex_sources = ("coded", "fact", "notes", "rule")

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
        out = []
        for r in doc.get("rows") or []:
            items = [
                {"id": c["id"], "label": crit[c["id"]].label if c["id"] in crit else c["id"],
                 "kind": crit[c["id"]].kind if c["id"] in crit else "", "source": c.get("source") or "coded",
                 "quote": c.get("quote"), "date": c.get("quote_date"), "reason": c.get("reason"),
                 "records": len(c.get("resource_refs") or [])}
                for c in r.get("criteria") or []
            ]  # fmt: skip
            if not items:  # excluded by the run's own rules: scope, research-contact consent
                items = [{"id": "", "label": "consent" if "consent" in a.lower() or a.startswith("contact")
                          else "scope", "kind": "", "source": "rule", "quote": None, "date": None, "reason": None,
                          "records": 0} for a in r.get("actions") or ["scope"]]  # fmt: skip
            out.append({"pid": str(r["pid"]), "short": str(r["pid"])[:8], "items": items})
        return out

    def need_excluded(sess: Session, rs: str, path: str) -> str:
        rid = study_or_404(sess, rs)
        if not sess.user.can_view_phi:  # the PI and the CRC (and the administrator); never viewer or CRO
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        h.delegated(sess, rid, path)  # D-273 (PV-3): the same delegation rule as the week page
        return rid

    @app.get("/studies/{rs}/excluded")
    def excluded(request: Request, rs: str, src: str = "", page: int = 1, done: str = "") -> Response:
        sess = h.need(request)
        rid = need_excluded(sess, rs, request.url.path)
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
        return h.page(request, "excluded.html", sess, rs=rid, job=job, doc=doc, total=total,
                      rows=rows[(page_no - 1) * st.PAGE_SIZE: page_no * st.PAGE_SIZE], sent=sent, counts=counts,
                      src=src if src in ex_sources else "", sources=ex_sources, page_no=page_no, pages=pages,
                      done=done == "sent")  # fmt: skip

    @app.post("/studies/{rs}/excluded/{pid}/review")
    def excluded_review(request: Request, rs: str, pid: str, csrf: str = Form(""), crit: str = Form(""),
                        note: str = Form("")) -> Response:  # fmt: skip
        """ "This is wrong, send to review": recorded with the person and the time, audited (P-04)."""
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        rid = need_excluded(sess, rs, request.url.path)
        job, doc = excluded_bundle(rid)
        if (
            job is None
            or doc is None
            or not _PID.match(pid)
            or not any(str(r.get("pid")) == pid for r in doc.get("rows") or [])
        ):
            raise h.problem(404, "notfound")
        crit = crit.strip()[:40]
        store.send_excluded_review(rid, pid, job.job_id, crit, note.strip()[:300], h.actor(sess), h.clock().isoformat())
        au.append("console.excluded_review", job_id=job.job_id, ruleset=rid, actor=h.actor(sess),
                  detail={"pid": pid, "criterion": crit, "role": sess.user.role})  # fmt: skip
        return RedirectResponse(f"/studies/{rid}/excluded?done=sent#x-{pid[:8]}", status_code=303)

    h.patient_ctx = patient_ctx

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
        if not sess.user.can_view_phi:
            raise h.problem(403, "forbidden")
        screen_or_403(sess, rid, request.url.path)
        return h.page(request, "patient.html", sess, **patient_ctx(sess, rid, pid))

    def apply_reveal(
        sess: Session,
        path: str,
        rs: str,
        pid: str,
        reason: str,
        via: str = "patient",
        purpose: str = "",
        note: str = "",
    ) -> tuple[dict[str, Any], str]:
        """One chart number for the page and ``/api/v1`` alike (D-99): identifier authority for the study
        (administrator, coordinator, and the study's investigator since the owner's decision of 2026-11-09, D-143),
        a reason, one audit record on each side and the orchestrator's per-person rate limit. Viewer and CRO
        accounts get 403. D-147: once the study's delegation log names a PI, an investigator reveals only as that PI
        or as a sub-investigator ticked "screen"; the candidate page (``via="candidates"``, with the view's purpose)
        uses this same path, reason and cap. D-273: the job page (``via="job"``) too, so this is the console's one
        reveal path (PV-2); the reason "other" needs a written note of 10 characters or more, kept in the audit
        record (ROLE-016)."""
        rid = study_or_404(sess, rs)
        delegated = sess.user.role != "investigator" or h.may is None or h.may(sess.user, rid, "screen")
        if not sess.user.sees_ids(rid) or not delegated:
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        if reason not in REVEAL_REASONS:
            raise h.problem(400, "request.refused", reason="choose why you need the chart number")
        note = " ".join((note or "").split())[:200]
        if reason == "other" and len(note) < REVEAL_NOTE_MIN:
            raise h.problem(400, "reveal.note_needed", n=REVEAL_NOTE_MIN)
        ctx = patient_ctx(sess, rid, pid)
        job = ctx["job"]
        au.append(
            "console.reveal_patient",
            job_id=job.job_id,
            ruleset=rid,
            actor=h.actor(sess),
            detail={
                "pid": pid,
                "role": sess.user.role,
                "affiliation": sess.user.affiliation,
                "reason": reveal_reason(reason),
                "via": via,
                **({"purpose": purpose} if purpose else {}),
                **({"note": note} if note else {}),
            },
        )
        try:  # D-273 (PV-15): the role and the studies travel signed; the orchestrator checks them and the opt-out
            mrn = bk.reveal(job.job_id, pid, h.actor(sess), role=sess.user.role, scope=scope_of(sess.user.studies))
        except Refused as exc:
            raise h.problem(409, "request.refused", reason=str(exc)) from exc
        return ctx, mrn or ""

    h.apply_reveal = apply_reveal  # console.team's candidate page reveals through it (D-147)

    @app.post("/studies/{rs}/patients/{pid}/reveal")
    def patient_reveal(request: Request, rs: str, pid: str, csrf: str = Form(""), reason: str = Form(""),
                       note: str = Form("")) -> Response:  # fmt: skip
        """One chart number, shown once, audited on both sides (D-99, D-143)."""
        sess = h.need(request)
        study_or_404(sess, rs)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        ctx, mrn = apply_reveal(sess, request.url.path, rs, pid, reason, note=note)
        ctx["mrn"] = mrn
        return h.page(request, "patient.html", sess, **ctx)

    def back_to(rid: str, pid: str, back: str, done: str) -> str:
        if back == "patient":
            return f"/studies/{rid}/patients/{pid}?done={done}"
        lst = back.removeprefix("list:") if back.startswith("list:") else ""
        lst = lst if lst in st.WORKLISTS else "all"
        return f"/studies/{rid}/week?list={lst}&pid={pid}&done={done}#chart"

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
        if not sess.user.can_mark or (h.may is not None and not h.may(sess.user, rid, task)):
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
            au.append("console.pi_mark", job_id=wk["job"].job_id, ruleset=rid, actor=h.actor(sess), detail=detail)

        store.mark(rid, Mark(pid, value, stored_reason, stored_note, sess.user.username, now, wk["job"].job_id),
                   number=conf if mark == "approach" else None, before_commit=audit)  # fmt: skip
        if warned:  # the override record follows its audit event (an event without the record, never the reverse)
            h.team.add_override(rid, pid, warned, sess.user.username, now)
        return rid, value, detail

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
        if wk is None or not any(str(r.get("pid")) == pid for r in (wk["cl"] or {}).get("rows") or []):
            raise h.problem(404, "notfound")
        if outcome == "undo":
            return undo_outcome(sess, rid, pid, wk["job"].job_id)
        mk = store.latest_marks(rid).get(pid)
        if mk is None or mk.mark != "approach":
            # D-133 (review F-36): the coordinator calls a patient only after the investigator's "OK to contact";
            # refused here, so the page and /api/v1 refuse alike
            au.append("console.refused", ruleset=rid, actor=h.actor(sess),
                      detail={"pid": pid, "action": outcome, "reason": "no approach mark"})  # fmt: skip
            raise h.problem(409, "outcome.wait_pi")
        today = h.today()
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
                                                       source="manual", source_job=job_id))  # fmt: skip
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
        sess: Session | None = h.users.session(token) if token else None
        if sess is None:
            raise h.problem(401, "login")
        if h.users.must_change(sess.user.username):  # D-279 (SEC-1): the owner replaces the password on the page
            raise h.problem(403, "account.must_change")
        if h.scope_check is not None:  # D-146 (J-03): the API refuses what the page refuses, in one place
            h.scope_check(request, sess)
        bind_session(sess.token_sha[:16])  # S-09: the actor sent to the orchestrator is signed with this session
        return sess

    h.api_session = api_session  # the other /api/v1 routes (console.data_pages) sign in the same way

    @app.post("/api/v1/session")
    def api_login(body: ApiLogin, request: Request) -> dict[str, Any]:
        # D-279 (SEC-9, ROLE-006): the same per-address count as the page; a busy address waits (429), no account
        # is locked by someone else's guesses. The second factor on this route is T-505a's.
        src = source_of(request.client.host if request.client else None)
        wait = h.users.throttled(src)
        if wait:
            au.append("console.login_failed", actor=f"console:{body.username[:60]}",
                      detail={"via": "api", "reason": "slowed", "source": src})  # fmt: skip
            raise h.problem(429, "login.slowed", n=wait)
        user = h.users.authenticate(body.username, body.password, source=src)
        if user is None:
            au.append("console.login_failed", actor=f"console:{body.username[:60]}",
                      detail={"via": "api", "source": src})  # fmt: skip
            if h.identity is not None:
                h.identity.after_failure(body.username, src)
            raise h.problem(401, "login")
        if h.users.must_change(user.username):  # D-279 (SEC-1): no API session on a password someone else set
            au.append("console.login_failed", actor=f"console:{user.username}",
                      detail={"via": "api", "reason": "must_change"})  # fmt: skip
            raise h.problem(403, "account.must_change")
        token, sess = h.users.new_session(user, body.lang if body.lang in ("ja", "zh-TW", "en") else "en", "api")
        au.append("console.login", actor=f"console:{user.username}", detail={"role": user.role, "via": "api"})
        return {"token": token, "username": user.username, "role": user.role,
                "expires": getattr(sess, "expires", None)}  # fmt: skip

    @app.delete("/api/v1/session")
    def api_logout(request: Request) -> dict[str, bool]:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            h.users.end_session(auth[7:].strip())
        return {"ok": True}

    @app.get("/api/v1/studies")
    def api_studies(request: Request) -> list[dict[str, Any]]:
        sess = api_session(request)
        return [{"id": r.id, "version": getattr(r, "version", None), "kind": r.kind} for r in trials(sess)]

    def rows_or_403(sess: Session, rs: str, path: str) -> str:
        """A study this account sees, for a role that reads patient-level rows; the same check as the page (D-146)."""
        rid = study_or_404(sess, rs)
        if not sess.user.can_view_phi:
            au.append("console.denied", actor=h.actor(sess), detail={"action": path[:80]})
            raise h.problem(403, "forbidden")
        h.delegated(sess, rid, path)  # D-273 (PV-3): the page's delegation rule on /api/v1 too
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

    @app.post("/api/v1/studies/{rs}/patients/{pid}/mark")
    def api_mark(request: Request, rs: str, pid: str, body: ApiMark) -> dict[str, Any]:
        sess = api_session(request)
        rid, value, detail = apply_mark(
            sess, request.url.path, rs, pid, body.mark, body.reason, body.recheck, body.note
        )
        return {"study": rid, "pid": pid, "mark": value, "screening_no": detail.get("to"),
                "irb_override": detail.get("irb_override") or None}  # fmt: skip

    @app.post("/api/v1/studies/{rs}/patients/{pid}/outcome")
    def api_outcome(request: Request, rs: str, pid: str, body: ApiOutcome) -> dict[str, Any]:
        sess = api_session(request)
        rid, no = apply_outcome(sess, request.url.path, rs, pid, body.outcome, body.retry, body.note)
        return {"study": rid, "pid": pid, "outcome": body.outcome, "screening_no": no}

    @app.post("/api/v1/studies/{rs}/patients/{pid}/reveal")
    def api_reveal(request: Request, rs: str, pid: str, body: ApiReveal) -> dict[str, Any]:
        """The chart number of one listed patient for an account with identifier authority (D-143), audited and
        rate-limited exactly as on the patient page."""
        sess = api_session(request)
        _ctx, mrn = apply_reveal(sess, request.url.path, rs, pid, body.reason, note=body.note)
        return {"study": rs.strip().upper(), "pid": pid, "mrn": mrn or None}

    @app.get("/api/v1/studies/{rs}/screening-log")
    def api_screening_log(request: Request, rs: str) -> list[dict[str, Any]]:
        sess = api_session(request)
        rid = rows_or_403(sess, rs, request.url.path)
        gone = h.optout.active() if h.optout is not None else set()  # D-147: never an opted-out patient
        refs = h.team.latest_referrals(rid) if h.team is not None else {}
        return [
            {"pid": a, "screening_no": b, "at": c, "referral_route": refs[a].route if a in refs else "",
             "referral_outcome": refs[a].state if a in refs else ""}
            for a, b, c in store.screening_rows(rid) if a not in gone
        ]  # fmt: skip
