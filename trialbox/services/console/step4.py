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
from tb_common.authz import permit, role_allowed
from tb_common.erased import is_erased
from tb_contracts import Job, JobCreate

from console import about, actor, command, form_errors, i18n_prefs, prefs, terminology_refused, tier_words
from console.auth import AuthError, Session, source_of
from console.backend import Refused, Unavailable
from console.home import Helpers
from console.i18n import CATALOGUES
from console.local_path import local_path
from console.models_view import build_rows

for _lang, _cat in (("en", i18n_prefs.EN), ("ja", i18n_prefs.JA), ("zh-TW", i18n_prefs.ZH)):  # 10F-1 (D-1387)
    CATALOGUES[_lang].update(_cat)

# the orchestrator's in-process principals (orchestrator.core.SYSTEM_SENDERS; D-464): a retry names a person instead
INTERNAL_PRINCIPALS = ("scheduler", "system")


def scheduler_job(job: Job) -> bool:
    """A job the box's own scheduler started, or an administrator's retry of one (T-746, D-474: the orchestrator's
    retry sets ``parent_job_id``; it checks the chain again itself)."""
    return job.requested_by.strip().lower() == "scheduler" or bool(job.parent_job_id)


def may_retry(role: str, job: Job) -> bool:
    """A failed scheduler job: the matrix row ``job.retry_scheduled`` (D-474); any other: the role may start its type
    (D-146), as the orchestrator checks again."""
    if scheduler_job(job):
        return permit(role, "job.retry_scheduled").allowed
    return role_allowed(role, job.type)


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
    (r"^/studies/[^/]+/candidates", "candidates"),  # D-398 (UX-029): the PoC pages get their own text
    (r"^/studies/[^/]+/referrals", "referrals"),
    (r"^/studies/[^/]+/edc", "edc"),
    # J-4 (D-1224, walk F-08): the participants (the list and one participant) and the study's state get their own text
    (r"^/studies/[^/]+/subjects(/|$)", "subjects"),
    (r"^/studies/[^/]+/state$", "state"),
    (r"^/reports", "reports"),
    (r"^/admin(/redcap)?$", "admin"),
    # T-317 (D-774): the pages of the steward, the privacy office and the administrator's accounts get their own text
    (r"^/ops/users", "users"),
    (r"^/ops/accounts/requests", "account_requests"),
    (r"^/breakglass", "breakglass"),
    (r"^/audit", "audit"),
    (r"^/data/conflicts", "conflicts"),
    (r"^/data-ops", "dataops"),
    (r"^/site/opt-outs", "optouts"),
    (r"^/site/staff", "staff"),
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


def help_key(slug: str, role: str) -> str:
    """J-4 (D-1224, walk F-01): the help text of a page for the role reading it: ``help.page.<slug>.<role>`` where the
    catalogue has one (the weekly page as the coordinator reads it), else the page's own ``help.page.<slug>``."""
    from console.i18n import CATALOGUES

    own = f"help.page.{slug}.{role}"
    return own if own in CATALOGUES["en"] else f"help.page.{slug}"


_STUDY_IN_PATH = re.compile(r"^/studies/([^/?#]+)")


def own_study(back: str, studies: list[str], logged: list[str]) -> str:
    """D-398 (UX-029): the study the help examples name. The study of the page the help was opened from, else the
    first study whose delegation log lists this account, else the first study in scope ("" when there is none)."""
    m = _STUDY_IN_PATH.match(back)
    if m and m.group(1).upper() in studies:
        return m.group(1).upper()
    for rs in studies:
        if rs in logged:
            return rs
    return studies[0] if studies else ""


def _safe_back(path: str) -> str:
    return local_path(path, "/home")


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
            # D-1241: the patient page's own question (``Helpers.reads``: the ``phi.view`` row, then the study's
            # delegation log; D-147, D-273). Where it says no, no patient of this study is looked for, grant or no
            # grant: the answer is the answer for a number or prefix that does not exist (break-glass opens a patient
            # from the grant's own page, where the use is recorded, D-430)
            if not h.reads(sess.user, rs):
                continue
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
                if is_erased(pid):  # D-875: an erased row is no patient to find
                    continue
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
    def _totp_on(username: str) -> bool:
        """DEMO-JA: the account signs in with a second factor, so "two-step sign-in comes later" is not shown."""
        ident = getattr(h, "identity", None)
        return bool(ident is not None and ident.settings.totp_required and not h.users.is_sso(username))

    def my_roles(sess: Session) -> list[dict[str, Any]]:
        """9f-1: the signed-in person's own delegation-log entries that are in force today, in the studies this
        account sees, with the ticked tasks (a sub-investigator's) and, from two weeks before its last day, the days
        left (9f-4 a). Their own rows only (``TeamStore.entries_for``): nobody else's entry is read."""
        team = getattr(h, "team", None)
        if team is None:
            return []
        day, seen = h.today(), set(studies_of(sess))
        return [
            {"rs": e.ruleset.upper(), "role": e.role, "tasks": e.tasks, "start": e.start, "end": e.end,
             "left": e.days_left(day)}
            for e in team.entries_for(sess.user.username)
            if e.ruleset.upper() in seen and e.active_on(day)
        ]  # fmt: skip

    def account_page(request: Request, sess: Session, status: int = 200, **ctx: Any) -> Response:
        """S22 My account: the facts, the person's own roles (9f-1), their preferences (10F-1, D-1387) and the
        password. ``ctx``: ``saved``, ``error``, ``fe`` (a failed preferences POST) and ``last_login``."""
        u = sess.user
        mine = h.users.prefs(u.username)
        options = {k: [(v, prefs.LABELS[k][v]) for v in vals] for k, vals in prefs.KEYS.items()}  # labels: keys
        base: dict[str, Any] = {"saved": False, "saved_prefs": False, "error": "", "fe": None, "last_login": ""}
        return h.page(
            request,
            "account.html",
            sess,
            status=status,
            my_roles=my_roles(sess),
            me=u,
            sso=h.users.is_sso(u.username),
            studies=studies_of(sess),
            must_change=h.users.must_change(u.username),  # D-279: someone else set this password
            totp_on=_totp_on(u.username),
            prefs=mine,
            pref_options=options,
            pref_labels=prefs.FIELD_LABELS,
            **{**base, **ctx},
        )

    @app.get("/account")
    def account(request: Request, saved: str = "") -> Response:
        sess = h.need(request)
        u = sess.user
        last = next(
            (r.ts for r in bk.audit(None, 2000) if r.event == "console.login" and r.actor == f"console:{u.username}"),
            "",
        )
        return account_page(request, sess, last_login=last[:16].replace("T", " "), saved=saved == "1",
                            saved_prefs=saved == "prefs")  # fmt: skip

    @app.post("/account/prefs")
    async def account_prefs(request: Request) -> Response:
        """10F-1 (D-1387): the signed-in person's own preferences, nobody else's (the name is the session's, never a
        field). Each posted key must hold a value of its closed set (``console.prefs.KEYS``), else the page answers
        400 with the summary and nothing is stored; a key not posted is left as it is. Each change is audited
        (who, key, from, to). A language chosen here is also the session's at once."""
        sess = h.need(request)
        form = await request.form()
        if not h.csrf_ok(sess, str(form.get("csrf") or "")):
            raise h.problem(400, "csrf")
        posted = {k: str(form.get(k) or "") for k in prefs.KEYS if k in form}
        bad = prefs.problems(posted)
        if bad:
            fe = form_errors.failed(prefs.FORM, prefs.PREFIX, bad, [(k, v) for k, v in form.multi_items()])
            return account_page(request, sess, status=form_errors.FAILED, fe=fe)
        u = sess.user
        for key, before, after in h.users.set_prefs(u.username, posted):
            au.append("console.pref_set", actor=h.actor(sess),
                      detail={"user": u.username, "key": key, "from": before, "to": after})  # fmt: skip
        lang = prefs.session_lang(h.users.prefs(u.username))
        if lang is not None and "lang" in posted:
            h.users.set_lang(sess, lang)
        return RedirectResponse("/account?saved=prefs", status_code=303)

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
        elif new == current:  # D-279: replacing a password someone else set with itself is no change
            error = "account.err.same"
        elif h.users.authenticate(u.username, current, source=source_of(request.client.host if request.client
                                                                          else None)) is None:  # fmt: skip
            error = "account.err.current"
        else:
            try:
                h.users.set_password(u.username, new, must_change=False, owner=True)  # D-279, D-447: the owner chose it
            except AuthError as exc:  # D-447: which rule refused it (history, breached list, length)
                error = getattr(exc, "code", "account.err.policy")
        if not error:
            au.append("console.user", actor=h.actor(sess), detail={"action": "password", "user": u.username})
            return RedirectResponse("/login", status_code=303)  # set_password signs the account out everywhere
        return account_page(request, sess, status=400, error=error)

    # ------------------------------------------------------------------ S29 Help panel
    @app.get("/help")
    def help_panel(request: Request, back: str = "/home") -> Response:
        sess = h.need(request)
        target = _safe_back(back)
        studies = studies_of(sess)
        team = h.team
        logged = [
            r for r in studies if team is not None and any(e.username == sess.user.username for e in team.entries(r))
        ]
        return h.page(
            request,
            "help.html",
            sess,
            slug=help_slug(target.split("?")[0]),
            page_key=help_key(help_slug(target.split("?")[0]), sess.user.role).removeprefix("help.page."),
            back=target,
            studies=studies,
            mine=own_study(target, studies, logged),
        )

    @app.get("/help/guide")
    def role_guide(request: Request) -> Response:
        """T-317 (D-774): the signed-in account's own role guide in its language, printable; the same text as
        ``docs/guides/<role>.<lang>.md`` (``console.guides``), built from this help catalogue."""
        from console import guides

        sess = h.need(request)
        role = sess.user.role if sess.user.role in guides.ROLES else "viewer"
        return h.page(request, "role_guide.html", sess, role=role, sections=guides.sections)  # in the page's language

    about.register(app, h)  # T-617a: /about, the third-party notices (NOTICE), beside the help panel

    # ------------------------------------------------------------------ S37 Notices received
    @app.get("/notices/received")
    def notices_received(request: Request) -> Response:
        sess = h.need(request)
        rows = [
            {
                "kind": k,
                "day": d,
                "at": a,  # a UTC instant; the page shows it in the site's zone (T-513, UX-020)
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
        today = h.today()  # the site's date (D-270)
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
            if r.event not in ("ingest.done", "ingest.failed", "ingest.held"):  # held: dataflow P0-2
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

    def _model_builds() -> list[dict[str, Any]] | None:
        read = getattr(bk, "model_builds", None)
        return build_rows(read()) if callable(read) else None

    def admin_page(request: Request, sess: Session, tab: str, notice: str = "", **flt: str) -> Response:
        tab = tab if tab in TABS else "health"
        ctx: dict[str, Any] = {"tab": tab, "tabs": TABS, "notice": notice}
        if tab == "health":
            from tb_common.refdata import status_or_none

            ctx.update(
                admin_ctx(sess),
                health=bk.health(),
                models=bk.models(),
                model_builds=_model_builds(),  # T-012b: each pinned build and its qualification record
                refdata=status_or_none(),
                term_refused=terminology_refused.on_box(),  # E-TERM-3 (D-1048): a site list the box does not read
                tier_lacks=tier_words.lacks(),  # 10E-17 (D-1244): the tier's absences, worded as a status
                ops=h.ops_summary() if h.ops_summary is not None else None,
                **(h.admin_extra(sess) if h.admin_extra is not None else {}),  # T-209c: backup, update, accounts
            )  # D-178: the Operations tile
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
                # T-746 (D-474): every failed scheduler job (job.retry_scheduled); a person's job when the role may
                # start its type (D-146)
                can_retry={j.job_id for j in sel if j.state == "failed" and may_retry(sess.user.role, j)},
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
            sign = actor.assert_for(h, sess, "request.prepare", None, "POST", f"/jobs/{job.job_id}/cancel", {})
            fn(job.job_id, h.actor(sess), headers=sign)  # T-715 refuse mode (D-871): the verified administrator
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

    def retry_scheduled(sess: Session, job: Job) -> Response:
        """T-746 (D-474): the orchestrator copies the failed scheduler job (type, study, options, inputs) and checks
        the signed role, the job's state and origin, and that none of its type and study is unfinished; the console
        sends the job's id and the administrator's reply mailbox only."""
        if not sess.user.mailbox:
            raise h.problem(400, "request.refused", reason="this account has no mailbox (console.cli set-mailbox)")
        fn = getattr(bk, "retry_scheduled_job", None)
        if not callable(fn):
            raise Unavailable("this backend cannot retry a scheduled job")
        try:
            body = {"reply_to": sess.user.mailbox}  # T-715 refuse mode (D-871): signed as the verified person
            sign = actor.assert_for(h, sess, "job.retry_scheduled", None, "POST", f"/jobs/{job.job_id}/retry", body)
            new = fn(job.job_id, reply_to=sess.user.mailbox, by=h.actor(sess), role=sess.user.role, headers=sign)
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

    @app.post("/admin/jobs/{job_id}/retry")
    def job_retry(request: Request, job_id: str, csrf: str = Form(""), confirm: str = Form("")) -> Response:
        sess, job = job_for_admin(request, job_id, csrf)
        if job.state != "failed":
            raise h.problem(409, "admin.jobs.not_retryable")
        if not may_retry(sess.user.role, job):
            raise h.problem(403, "forbidden")
        if confirm != "yes":
            return h.page(request, "admin_confirm.html", sess, job=job, action="retry")
        if scheduler_job(job):
            return retry_scheduled(sess, job)
        requested_by = job.requested_by
        if requested_by.strip().lower() in INTERNAL_PRINCIPALS:  # T-713 (D-464): never named over HTTP
            if not sess.user.mailbox:
                raise h.problem(400, "request.refused", reason="this account has no mailbox (console.cli set-mailbox)")
            requested_by = sess.user.mailbox  # the administrator retries it, under the administrator's role
        req = JobCreate(
            type=job.type,
            ruleset=job.ruleset,
            options=dict(job.options or {}),
            comment=job.comment,
            requested_by=requested_by,
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
