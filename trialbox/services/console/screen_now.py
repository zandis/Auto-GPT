"""M8 (R1-N1): "Screen now" (``/studies/{rs}/screen-now``): a coordinator or investigator screens one study now and
reads the list on the same page, instead of waiting for the night.

It starts the same ``SCREEN`` job the console's request page starts (the scenario is unchanged), under the rule of
:func:`orchestrator.scheduler.screen_now_plan`: one per study at a time (a second request joins the first), queued
behind a night that has not ended with the wait stated, and never a change of the night's snapshot or an ingest. The
right is the request page's own (``command.SCREEN`` for the study). The time shown is the median of the study's last
measured runs; with none it says so. The list is the job's page, marked "screened now at <time>"; the night's list is
not replaced. A failed job says its step and keeps the previous list.

Audit: ``console.screen_now`` with ``action`` started, queued, joined or refused (the request itself is audited by
``console.request`` as for any job); a role that may not start it is a ``console.denied`` line.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from orchestrator import scheduler as sched
from tb_contracts import Job

from console.form_errors import FAILED, FieldError, FormErrors
from console.home import Helpers
from console.i18n import CATALOGUES
from console.i18n_screennow import EN, JA, ZH

for _lang, _cat in (("en", EN), ("ja", JA), ("zh-TW", ZH)):
    CATALOGUES[_lang].update(_cat)

_RS = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
ACTIVE = ("received", "parsing", "compiling", "awaiting_approval", "running", "reporting")
_ASK = threading.Lock()  # ponytail: one process's lock; the orchestrator's job id is not made from the study


def register(app: FastAPI, h: Helpers, _env: Mapping[str, str] | None = None) -> None:
    def study(request: Request) -> tuple[Any, str]:
        sess = h.need(request)
        rs = str(request.path_params["rs"]).strip().upper()
        if not _RS.match(rs) or not sess.user.sees_study(rs):
            raise h.problem(404, "notfound")  # the same answer for a study that is not there and one not seen
        return sess, rs

    def approved(rs: str) -> str | None:
        return next((r.version or "" for r in h.bk.rulesets() if r.id.upper() == rs and r.status == "approved"), None)

    def state_of(rs: str) -> dict[str, Any]:
        active: list[Job] = []
        for st in ACTIVE:
            active += h.bk.list_jobs(state=st)
        done = h.bk.list_jobs(state="done")
        mine = [j for j in done if (j.ruleset or "").upper() == rs]
        shots = [j for j in mine if j.type == "SCREEN"]
        last = max(shots, key=lambda j: (j.updated_at or j.received_at, j.job_id), default=None)
        lists = [j for j in mine if j.type in sched.LIST_TYPES and j.metrics and j.metrics.patients_scoped > 0]
        ran = max(lists, key=lambda j: (j.updated_at or j.received_at, j.job_id), default=None)
        failed = [j for j in h.bk.list_jobs(state="failed", ruleset=rs) if j.type == "SCREEN"]
        bad = max(failed, key=lambda j: (j.updated_at or j.received_at, j.job_id), default=None)
        if (
            bad is not None
            and last is not None
            and (bad.updated_at or bad.received_at) < (last.updated_at or last.received_at)
        ):
            bad = None  # a later run passed: the failure is history
        plan = sched.screen_now_plan(active, rs)
        behind = sum(
            1 for j in active if j.type in sched.NIGHT_TYPES
        )  # a job of this study joined or not, the night is ahead
        per = sched.per_1000_seconds(done, rs)
        scope = ran.metrics.patients_scoped if ran and ran.metrics else None
        snap = ran.snapshot_date if ran else None
        return {
            "plan": plan,
            "running": next((j for j in active if j.job_id == plan.job_id), None),
            "per_1000": None if per is None else round(per, 1),
            "scope": scope,
            "minutes": None if per is None or not scope else round(per * scope / 1000 / 60, 1),
            "behind": behind,
            "wait_minutes": _minutes(sched.expected_wait(active, done)) if behind else None,
            "last": last,
            "failed": bad,
            "stale": snap.isoformat() if snap and (h.today() - snap).days > sched.STALE_DAYS else "",
        }

    def render(request: Request, sess: Any, rs: str, status: int = 200, **extra: Any) -> Response:
        st = state_of(rs)
        busy = st["plan"].action == "join" or bool(st["behind"])
        fe = extra.pop("fe", None)
        return h.page(request, "screen_now.html", sess, status, rs=rs, version=approved(rs), st=st, fe=fe,
                      may_start=h.may_run(sess.user, rs, "SCREEN"), refresh=busy,
                      refresh_url=f"/studies/{rs}/screen-now", **extra)  # fmt: skip

    @app.get("/studies/{rs}/screen-now", response_class=HTMLResponse)
    def screen_now_page(request: Request, rs: str, joined: str = "", queued: str = "") -> Response:
        sess, rs = study(request)
        return render(request, sess, rs, joined=joined == "1", queued=queued == "1")

    @app.post("/studies/{rs}/screen-now")
    def screen_now_start(request: Request, rs: str, csrf: str = Form(""), all_dept: str = Form("")) -> Response:
        sess, rs = study(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not h.may_run(sess.user, rs, "SCREEN"):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": f"screen-now {rs}"})
            raise h.problem(403, "forbidden")

        def said(action: str, **more: Any) -> None:
            h.au.append("console.screen_now", ruleset=rs, actor=h.actor(sess), detail={"action": action, **more})

        version = approved(rs)
        if version is None:
            said("refused", why="no approved ruleset")
            return render(request, sess, rs, 409, error="screennow.no_ruleset")
        with _ASK:  # the plan and the submit are one step: two requests together make one job
            st = state_of(rs)
            plan = st["plan"]
            if plan.action == "join":
                said("joined", job=plan.job_id)
                return RedirectResponse(f"/studies/{rs}/screen-now?joined=1", status_code=303)
            if st["scope"] is None and all_dept != "1":  # a scope that cannot be counted is asked about, never assumed
                fe = FormErrors("screen-now", "sn", (FieldError("all_dept", "screennow.ask_scope"),))
                return render(request, sess, rs, FAILED, fe=fe)
            if h.submit is None:
                raise h.problem(503, "request.refused", reason="this console cannot start a job")
            job = h.submit(sess, f"SCREEN {rs} version={version}")
        said("queued" if plan.action == "queue" else "started", job=job.job_id, behind=plan.behind)
        return RedirectResponse(f"/studies/{rs}/screen-now" + ("?queued=1" if plan.action == "queue" else ""), 303)


def _minutes(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds / 60, 1)
