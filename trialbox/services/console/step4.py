"""Build step 4 (D-110): the header command field, S22 My account, S29 Help panel, S37 Notices received and the
admin page with its three tabs (S13 health, S26 jobs with Cancel and Retry, S24 data sources).

Registered by ``console.app`` inside the pilot workspace, after ``console.home``.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import RedirectResponse
from tb_contracts import Job, JobCreate

from console import command
from console.auth import AuthError, Session
from console.backend import Refused, Unavailable
from console.home import Helpers

_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
TERMINAL = ("done", "failed")
TABS = ("health", "jobs", "sources")

# S29: which help text a page gets, by its path (first match wins)
HELP_PAGES: tuple[tuple[str, str], ...] = (
    (r"^/(home)?$", "home"),
    (r"^/(studies/[^/]+/)?week$", "week"),
    (r"^/studies/[^/]+/patients/", "patient"),
    (r"^/studies/[^/]+/feasibility", "feasibility"),
    (r"^/studies/[^/]+/screening-log", "log"),
    (r"^/studies/[^/]+/cohort", "cohort"),
    (r"^/studies/[^/]+/setup", "setup"),
    (r"^/studies/[^/]+/approv", "approval"),
    (r"^/reports", "reports"),
    (r"^/admin(/redcap)?$", "admin"),
    (r"^/(pilot/)?jobs", "jobs"),
    (r"^/account", "account"),
    (r"^/notices/received", "notices"),
    (r"^/settings/notices", "notice_settings"),
    (r"^/pilot/registry", "registry"),
    (r"^/pilot/request", "request"),
    (r"^/pilot/protocol", "protocol"),
    (r"^/cmd", "cmd"),
    (r"^/site(/|$)", "site"),
    (r"^/ask", "ask"),
)
HELP_SLUGS = (*dict.fromkeys(slug for _, slug in HELP_PAGES), "other")


def help_slug(path: str) -> str:
    for pat, slug in HELP_PAGES:
        if re.search(pat, path):
            return slug
    return "other"


def _safe_back(path: str) -> str:
    return path if path.startswith("/") and not path.startswith("//") else "/home"


def register(app: FastAPI, h: Helpers) -> None:
    bk, au, store = h.bk, h.au, h.store

    def studies_of(sess: Session) -> list[str]:
        return sorted({r.id.upper() for r in bk.rulesets() if sess.user.sees_study(r.id)})

    # ------------------------------------------------------------------ S1 header command field (+ S28 search)
    def search(sess: Session, text: str, studies: list[str]) -> dict[str, list[dict[str, str]]]:
        """Studies, pseudonyms and screening numbers in this account's scope (FR-PLAT-14). Never chart numbers."""
        q = text.strip()
        qu = q.upper()
        out: dict[str, list[dict[str, str]]] = {"studies": [], "patients": []}
        for rs in studies:
            if qu and qu in rs:
                out["studies"].append(
                    {"id": rs, "href": command.url_of(command.Action("status", rs), sess.user.role) or "/home"}
                )
        if not sess.user.can_view_phi or len(q) < 4:
            return out
        for rs in studies:
            nos = store.screening_nos(rs)
            pids = set(nos)
            if h.week_bundle is not None:  # D-133: a patient on this week's list is found by its code too
                wk = h.week_bundle(sess, rs) or {}
                pids |= {str(r["pid"]) for r in wk.get("rows") or []}
            try:
                pids |= {e.pid for e in bk.registry_rows(rs)}
            except Exception:  # the registry is optional for search  # noqa: S112
                continue
            for pid in sorted(pids):
                no = nos.get(pid, "")
                if pid.startswith(q) or (no and no.upper() == qu):
                    out["patients"].append({"study": rs, "pid": pid, "no": no, "href": f"/studies/{rs}/patients/{pid}"})
                if len(out["patients"]) >= 20:
                    return out
        return out

    def one_patient(pats: list[dict[str, str]]) -> str | None:
        """The page to open when every hit is the same patient (D-133, review task T3: a code typed on the phone
        opens the patient's "why" page in two taps): the study that screens patients (a trial) before a registry."""
        if not pats or len({x["pid"] for x in pats}) != 1:
            return None
        kinds = {r.id.upper(): r.kind for r in bk.rulesets()}
        best = sorted(pats, key=lambda x: kinds.get(x["study"], "trial") not in ("trial", ""))
        return best[0]["href"]

    @app.get("/cmd")
    def cmd(request: Request, q: str = "", back: str = "/home") -> Response:
        sess = h.need(request)
        role = sess.user.role
        studies = studies_of(sess)
        act = command.interpret(q[:300], studies, role)
        au.append("console.command", actor=h.actor(sess), detail={"intent": act.intent, "action": act.command or ""})
        if act.intent == "patient" and act.target:
            pats = search(sess, act.target, studies)["patients"]
            only = one_patient(pats)
            if only:
                return RedirectResponse(only, status_code=303)
            return h.page(
                request, "cmd.html", sess, q=q, act=act, hits={"studies": [], "patients": pats}, back=_safe_back(back)
            )
        if act.intent == "search":
            hits = search(sess, act.target or q, studies)
            found = hits["studies"] + hits["patients"]
            only = found[0]["href"] if len(found) == 1 else None if hits["studies"] else one_patient(hits["patients"])
            if only:
                return RedirectResponse(only, status_code=303)
            return h.page(request, "cmd.html", sess, q=q, act=act, hits=hits, studies=studies, back=_safe_back(back))
        if act.opens_page:
            url = command.url_of(act, role)
            if url:
                return RedirectResponse(url, status_code=303)
        return h.page(request, "cmd.html", sess, q=q, act=act, hits=None, studies=studies, back=_safe_back(back))

    # ------------------------------------------------------------------ S22 My account
    @app.get("/account")
    def account(request: Request, saved: str = "") -> Response:
        sess = h.need(request)
        u = sess.user
        last = next(
            (r.ts for r in bk.audit(None, 2000) if r.event == "console.login" and r.actor == f"console:{u.username}"),
            "",
        )
        return h.page(
            request,
            "account.html",
            sess,
            me=u,
            sso=h.users.is_sso(u.username),
            studies=studies_of(sess),
            last_login=last[:16].replace("T", " "),
            saved=saved == "1",
            error="",
        )

    @app.post("/account/password")
    def account_password(
        request: Request,
        csrf: str = Form(""),
        current: str = Form(""),
        new: str = Form(""),
        again: str = Form(""),
    ) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        u = sess.user
        error = ""
        if h.users.is_sso(u.username):
            error = "account.err.sso"
        elif new != again:
            error = "account.err.mismatch"
        elif h.users.authenticate(u.username, current) is None:
            error = "account.err.current"
        else:
            try:
                h.users.set_password(u.username, new)
            except AuthError:
                error = "account.err.policy"
        if not error:
            au.append("console.user", actor=h.actor(sess), detail={"action": "password", "user": u.username})
            return RedirectResponse("/login", status_code=303)  # set_password signs the account out everywhere
        return h.page(
            request,
            "account.html",
            sess,
            status=400,
            me=u,
            sso=h.users.is_sso(u.username),
            studies=studies_of(sess),
            last_login="",
            saved=False,
            error=error,
        )

    # ------------------------------------------------------------------ S29 Help panel
    @app.get("/help")
    def help_panel(request: Request, back: str = "/home") -> Response:
        sess = h.need(request)
        target = _safe_back(back)
        return h.page(
            request, "help.html", sess, slug=help_slug(target.split("?")[0]), back=target, studies=studies_of(sess)
        )

    # ------------------------------------------------------------------ S37 Notices received
    @app.get("/notices/received")
    def notices_received(request: Request) -> Response:
        sess = h.need(request)
        rows = [
            {
                "kind": k,
                "day": d,
                "at": a[:16].replace("T", " "),
                "subject": s,
                "href": "/week" if k == "N1" else "/home",
            }
            for k, d, a, s in store.notices_for(sess.user.username)
        ]
        return h.page(request, "notices_received.html", sess, rows=rows)

    # ------------------------------------------------------------------ S13 admin page: health, jobs, data sources
    def need_admin(request: Request) -> Session:
        sess = h.need(request)
        if not sess.user.is_admin:
            au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    def admin_ctx(sess: Session) -> dict[str, Any]:
        users = h.users.users()
        today = h.clock().date()
        soon = [u for u in users if u.expires and u.expires <= (today + timedelta(days=30)).isoformat()]
        jobs = bk.list_jobs(limit=200)
        since = (h.clock() - timedelta(hours=24)).isoformat()
        recs = [r for r in bk.audit(None, 1000) if r.ts >= since]
        reveals: dict[str, int] = {}
        for r in recs:
            if r.event in ("console.reveal", "console.reveal_patient"):
                reveals[r.actor or ""] = reveals.get(r.actor or "", 0) + 1
        by_aff: dict[str, int] = {}
        for u in users:
            by_aff[u.affiliation] = by_aff.get(u.affiliation, 0) + 1
        return {
            "users": users,
            "by_aff": by_aff,
            "soon": soon,
            "waiting": [j for j in jobs if j.state == "awaiting_approval"],
            "rulesets": bk.rulesets(),
            "reveals": sorted(reveals.items(), key=lambda kv: -kv[1]),
            "counts": {
                "exports": sum(1 for r in recs if r.event in ("console.export", "console.download")),
                "denied": sum(
                    1 for r in recs if r.event in ("console.denied", "console.login_failed", "console.sso_rejected")
                ),
                "marks": sum(1 for r in recs if r.event == "console.pi_mark"),
            },
            "queue": sum(1 for j in jobs if j.state not in TERMINAL and j.state != "awaiting_approval"),
            "failed24": sum(
                1 for j in jobs if j.state == "failed" and (j.updated_at or j.received_at).isoformat() >= since
            ),
        }

    def sources_rows() -> list[dict[str, Any]]:
        """S24: one row per source from the adapter's ``ingest.done`` / ``ingest.failed`` audit records."""
        rows: dict[str, dict[str, Any]] = {}
        stale = (h.clock() - timedelta(hours=48)).isoformat()
        for r in bk.audit(None, 5000):  # newest first
            if r.event not in ("ingest.done", "ingest.failed"):
                continue
            src = str(r.detail.get("source") or "csv")
            row = rows.setdefault(
                src,
                {
                    "source": src,
                    "last_ok": "",
                    "last_try": r.ts,
                    "patients": None,
                    "records": None,
                    "error_pct": None,
                    "runs": [],
                },
            )
            if len(row["runs"]) < 30:
                row["runs"].append(
                    {
                        "at": r.ts[:16].replace("T", " "),
                        "ok": r.event == "ingest.done",
                        "records": r.detail.get("records"),
                        "error_pct": r.detail.get("validation_error_pct"),
                    }
                )
            if r.event == "ingest.done" and not row["last_ok"]:
                row.update(
                    last_ok=r.ts,
                    patients=r.detail.get("patients"),
                    records=r.detail.get("records"),
                    error_pct=r.detail.get("validation_error_pct"),
                )
        for row in rows.values():
            row["amber"] = not row["last_ok"] or row["last_ok"] < stale
            row["last_ok_text"] = row["last_ok"][:16].replace("T", " ")
        return sorted(rows.values(), key=lambda r: r["source"])

    def admin_page(request: Request, sess: Session, tab: str, notice: str = "", **flt: str) -> Response:
        tab = tab if tab in TABS else "health"
        ctx: dict[str, Any] = {"tab": tab, "tabs": TABS, "notice": notice}
        if tab == "health":
            from tb_common.refdata import status_or_none

            ctx.update(admin_ctx(sess), health=bk.health(), models=bk.models(), refdata=status_or_none())
        elif tab == "jobs":
            jobs = bk.list_jobs(limit=300)
            types = sorted({j.type for j in jobs})
            studies = sorted({j.ruleset for j in jobs if j.ruleset})
            sel = [
                j
                for j in jobs
                if (not flt.get("study") or j.ruleset == flt["study"])
                and (not flt.get("type") or j.type == flt["type"])
                and (not flt.get("state") or j.state == flt["state"])
                and (not flt.get("day") or j.received_at.date().isoformat() == flt["day"])
            ]
            ctx.update(
                jobs=sel,
                types=types,
                studies=studies,
                flt=flt,
                terminal=TERMINAL,
                can_cancel=callable(getattr(bk, "cancel_job", None)),
            )
        else:
            ctx.update(sources=sources_rows())
        return h.page(request, "admin.html", sess, **ctx)

    @app.get("/admin")
    def admin(
        request: Request,
        tab: str = "health",
        notice: str = "",
        study: str = "",
        type: str = "",
        state: str = "",
        day: str = "",
    ) -> Response:
        sess = need_admin(request)
        return admin_page(
            request,
            sess,
            tab,
            notice if notice in ("cancelled", "retried", "ingested", "canary", "canary_down") else "",
            study=study,
            type=type,
            state=state,
            day=day,
        )

    @app.get("/admin/notice")
    def admin_notice(request: Request) -> Response:
        """D-140: every source of the loaded reference data, with its licence and the attribution it requires."""
        from tb_common.refdata import notices_or_empty, status_or_none

        sess = need_admin(request)
        return h.page(request, "admin_notice.html", sess, sources=notices_or_empty(), refdata=status_or_none())

    h.admin_page = admin_page  # type: ignore[attr-defined]  # /home for the administrator (console.home)

    def job_for_admin(request: Request, job_id: str, csrf: str) -> tuple[Session, Job]:
        sess = need_admin(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        job = bk.get_job(job_id) if _ULID.match(job_id) else None
        if job is None:
            raise h.problem(404, "notfound")
        return sess, job

    @app.post("/admin/jobs/{job_id}/cancel")
    def job_cancel(request: Request, job_id: str, csrf: str = Form(""), confirm: str = Form("")) -> Response:
        sess, job = job_for_admin(request, job_id, csrf)
        if job.state in TERMINAL:
            raise h.problem(409, "admin.jobs.not_cancellable")
        if confirm != "yes":
            return h.page(request, "admin_confirm.html", sess, job=job, action="cancel")
        fn = getattr(bk, "cancel_job", None)
        if not callable(fn):
            raise Unavailable("this backend cannot cancel jobs")
        try:
            fn(job.job_id, h.actor(sess))
        except Refused as exc:
            raise h.problem(400, "request.refused", reason=str(exc)) from exc
        au.append(
            "console.operate",
            actor=h.actor(sess),
            job_id=job.job_id,
            ruleset=job.ruleset,
            detail={"action": "cancel", "type": job.type},
        )
        return RedirectResponse("/admin?tab=jobs&notice=cancelled", status_code=303)

    @app.post("/admin/jobs/{job_id}/retry")
    def job_retry(request: Request, job_id: str, csrf: str = Form(""), confirm: str = Form("")) -> Response:
        sess, job = job_for_admin(request, job_id, csrf)
        if job.state != "failed":
            raise h.problem(409, "admin.jobs.not_retryable")
        if confirm != "yes":
            return h.page(request, "admin_confirm.html", sess, job=job, action="retry")
        req = JobCreate(
            type=job.type,
            ruleset=job.ruleset,
            options=dict(job.options or {}),
            comment=job.comment,
            requested_by=job.requested_by,
            inputs=list(job.inputs or []) or None,
        )
        try:
            new = bk.create_job(req, by=h.actor(sess), role=sess.user.role)  # D-146: the role decides
        except Refused as exc:
            raise h.problem(400, "request.refused", reason=str(exc)) from exc
        au.append(
            "console.operate",
            actor=h.actor(sess),
            job_id=new.job_id,
            ruleset=job.ruleset,
            detail={"action": "retry", "from": job.job_id, "type": job.type},
        )
        return RedirectResponse("/admin?tab=jobs&notice=retried", status_code=303)

    @app.post("/admin/models/canary")
    def models_canary(request: Request, csrf: str = Form("")) -> Response:
        """The Models tile's "Run now" (D-117): the 54-case pair canary, in the background on the orchestrator."""
        sess = need_admin(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        run = getattr(bk, "run_canary", None)
        ok = bool(run()) if callable(run) else False
        au.append("console.operate", actor=h.actor(sess), detail={"action": "canary", "started": ok})
        return RedirectResponse(f"/admin?notice={'canary' if ok else 'canary_down'}", status_code=303)
