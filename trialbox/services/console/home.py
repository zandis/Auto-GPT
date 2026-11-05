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
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from tb_contracts import Job

from console import studies as st
from console.auth import Session
from console.backend import Refused
from console.sitestore import (
    CAP_VALUES,
    CAPABILITIES_AD,
    CAPABILITIES_GENERAL,
    MARKS,
    NOT_SUITABLE_REASONS,
    Mark,
    SiteProfile,
    SiteStore,
)

_PID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
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


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store

    # ------------------------------------------------------------------ helpers
    def trials(sess: Session) -> list[Any]:
        return [
            r
            for r in bk.rulesets()
            if r.status == "approved" and r.kind in ("trial", "") and sess.user.sees_study(r.id)
        ]

    def study_or_404(sess: Session, rs: str) -> str:
        rid = rs.strip().upper()
        if not _RS.match(rid) or not sess.user.sees_study(rid):
            if _RS.match(rid):
                au.append("console.denied", actor=h.actor(sess), detail={"action": f"study {rid}"})
            raise h.problem(404, "notfound")
        return rid

    def crit_of(rs: str) -> dict[str, st.CriterionMeta]:
        fn = getattr(bk, "criteria", None)
        rows = fn(rs) if fn else []
        return {
            r["id"]: st.CriterionMeta(
                r["id"], r["kind"], r.get("class", "structured"), r.get("label") or r["id"], r.get("text", "")
            )
            for r in rows
        }

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
        rep = st.feas_report(result, prof, store.profile(rs), crit_of(rs), sponsor=sponsor)
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
        summary = load(job, "screen_", ".json")
        names = (summary or {}).get("practitioner_names") or {}
        pids = [str(r.get("pid")) for r in (cl or {}).get("rows") or [] if r.get("tier") in ("high", "review")]
        seen = store.seen(rs, pids, job.job_id, (job.updated_at or job.received_at).isoformat())
        rows = st.weekly_rows(cl, crit_of(rs), registry_map(rs), store.latest_marks(rs), seen, job.job_id, names)
        return {"job": job, "rows": rows, "counts": st.week_counts(rows), "summary": summary or {}, "cl": cl}

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
        week: dict[str, Any] | None = None
        if screen_job is not None:
            cl = load(screen_job, "candidate_list_", ".json")
            if cl is not None:
                rows = st.weekly_rows(cl, {}, registry_map(rs), store.latest_marks(rs), {}, "", None)
                week = {"job": screen_job, "counts": st.week_counts(rows)}
        regc = registry_counts(rs)
        if waiting is not None:
            nxt = ("approve", f"/pilot/jobs/{waiting.job_id}")
        elif feas_job is None:
            nxt = ("feas", f"/pilot/request?ruleset={rs}")
        elif site.missing:
            nxt = ("site", f"/studies/{rs}/feasibility#site")
        elif screen_job is None:
            nxt = ("screen", f"/pilot/request?ruleset={rs}")
        elif week and week["counts"]["marked"]:
            nxt = ("contact", f"/pilot/registry/{rs}")
        else:
            nxt = ("week", f"/studies/{rs}/week")
        return {
            "id": rs,
            "version": r.version,
            "feas": feas,
            "feas_job": feas_job,
            "week": week,
            "registry": regc,
            "site_missing": site.missing,
            "next": nxt,
        }

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
            return admin_home(request, sess)
        jobs = bk.list_jobs(limit=500)
        cards = [study_card(sess, r, jobs) for r in trials(sess)]
        return h.page(request, "home_crc.html", sess, cards=cards, models=bk.models())

    def admin_home(request: Request, sess: Session) -> Response:
        users = h.users.users()
        today = h.clock().date()
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
        if len(mine) == 1:
            return RedirectResponse(f"/studies/{mine[0].id}/week", status_code=303)
        return h.page(request, "week_pick.html", sess, studies=mine)

    # ------------------------------------------------------------------ feasibility report
    @app.get("/studies/{rs}/feasibility")
    def feasibility(request: Request, rs: str, view: str = "", saved: str = "") -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        sponsor = view == "sponsor" or sess.user.role == "cro"
        rep = feas_bundle(sess, rid, sponsor)
        site = store.profile(rid)
        ad = bool(rep and rep["summary"].get("screen_fail_ref"))
        keys = CAPABILITIES_AD if ad else CAPABILITIES_GENERAL
        return h.page(
            request,
            "feasibility.html",
            sess,
            rs=rid,
            rep=rep,
            site=site,
            cap_keys=keys,
            cap_values=CAP_VALUES,
            can_edit=sess.user.can_request,
            saved=saved == "1",
        )

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
        wk = week_bundle(sess, rid)
        return h.page(request, "week.html", sess, rs=rid, wk=wk, marks=MARKS, reasons=NOT_SUITABLE_REASONS)

    def patient_ctx(sess: Session, rid: str, pid: str) -> dict[str, Any]:
        if not _PID.match(pid):
            raise h.problem(404, "notfound")
        wk = week_bundle(sess, rid)
        if wk is None:
            raise h.problem(404, "notfound")
        row = next((r for r in (wk["cl"] or {}).get("rows") or [] if str(r.get("pid")) == pid), None)
        if row is None:
            raise h.problem(404, "notfound")
        crit = crit_of(rid)
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
            "reasons": NOT_SUITABLE_REASONS,
            "mrn": None,
        }

    @app.get("/studies/{rs}/patients/{pid}")
    def patient(request: Request, rs: str, pid: str) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not sess.user.can_view_phi:
            raise h.problem(403, "forbidden")
        return h.page(request, "patient.html", sess, **patient_ctx(sess, rid, pid))

    @app.post("/studies/{rs}/patients/{pid}/reveal")
    def patient_reveal(request: Request, rs: str, pid: str, csrf: str = Form("")) -> Response:
        """One chart number, shown once, audited on both sides (D-99). Investigators may too (D-104): they already
        treat these patients; the reveal names the investigator in the audit trail."""
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.can_view_phi:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        ctx = patient_ctx(sess, rid, pid)
        job = ctx["job"]
        au.append(
            "console.reveal_patient",
            job_id=job.job_id,
            ruleset=rid,
            actor=h.actor(sess),
            detail={"pid": pid, "role": sess.user.role, "affiliation": sess.user.affiliation},
        )
        try:
            mrn = bk.reveal(job.job_id, pid, h.actor(sess))
        except Refused as exc:
            raise h.problem(409, "request.refused", reason=str(exc)) from exc
        ctx["mrn"] = mrn or ""
        return h.page(request, "patient.html", sess, **ctx)

    @app.post("/studies/{rs}/patients/{pid}/mark")
    def patient_mark(
        request: Request,
        rs: str,
        pid: str,
        csrf: str = Form(""),
        mark: str = Form(""),
        reason: str = Form(""),
        note: str = Form(""),
        back: str = Form(""),
    ) -> Response:
        sess = h.need(request)
        rid = study_or_404(sess, rs)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.can_mark:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        if mark not in MARKS or not _PID.match(pid):
            raise h.problem(400, "request.refused", reason="choose Approach, Not suitable or Need info")
        if mark == "not_suitable" and reason not in NOT_SUITABLE_REASONS:
            reason = "other"
        wk = week_bundle(sess, rid)
        if wk is None or not any(str(r.get("pid")) == pid for r in (wk["cl"] or {}).get("rows") or []):
            raise h.problem(404, "notfound")
        now = h.clock().isoformat()
        store.mark(
            rid,
            Mark(
                pid,
                mark,
                reason if mark == "not_suitable" else None,
                note.strip()[:300] or None,
                sess.user.username,
                now,
                wk["job"].job_id,
            ),
        )
        au.append(
            "console.pi_mark",
            job_id=wk["job"].job_id,
            ruleset=rid,
            actor=h.actor(sess),
            detail={"pid": pid, "action": mark, "reason": reason if mark == "not_suitable" else ""},
        )
        target = f"/studies/{rid}/patients/{pid}" if back == "patient" else f"/studies/{rid}/week#p-{pid[:8]}"
        return RedirectResponse(target, status_code=303)
