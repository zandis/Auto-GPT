"""rc1's refusals in the console (the owner's ruling of 2026-11-20; review R22-34; ``tb_common.rc1_refusals``).

Outside the environments the table allows (DEV, TEST and VALIDATION, D-1072: so on a PRODUCTION box, an unset
``TB_ENV`` and an unknown one), the console serves no stored live patient list and no patient-level download. One
route list, :data:`ROUTES`, read by one middleware installed as ``console.demo_guard``'s is (appended, inside the
console's headers middleware): a matching request is refused before its route runs, so nothing is read from the
store, nothing is rendered and nothing leaves. The refusal is the console's problem page (403) with the table's
message in the reader's language, JSON on ``/api/``, and one audited ``console.denied`` event with the refusal's
name, the environment and the path (never a query or a body).

What the list holds, and why (each a GET):

* ``live_patient_lists`` (the orchestrator refuses to make one: ``orchestrator.scheduler.require_released``):

  - ``/studies/{rs}/week``: the week's list of candidates of a study (``console.home``);
  - ``/studies/{rs}/cohort``: the members of the study's latest screening or micro-batch list
    (``console.screening_log``);
  - ``/pilot/jobs/{id}`` of a job that lists patients (SCREEN, MICROBATCH, COHORT, NAV, CASE): its card shows the
    stored list or the case sheet. Any other job's card (FEAS, CONSENT ...) is counts and stays open.

* ``patient_mail_and_downloads`` (the mail gateway holds the mail: ``mail_gateway.gateway.Gateway._still_current``):

  - ``/pilot/jobs/{id}/files/{name}`` and ``/pilot/jobs/{id}/view/{name}`` of an output that is not aggregate
    (``console.app``'s own test of a patient-level file); aggregate files stay open;
  - ``/studies/{rs}/screening-log.xlsx`` (``console.screening_log``): the sponsor's screening log, one row a person;
  - ``/pilot/registry/{rs}/export.xlsx`` (``console.app``): the study's registry with chart numbers;
  - ``/studies/{rs}/enrolment.{fmt}`` and ``/api/v1/studies/{rs}/enrolment/{fmt}`` (``console.lifecycle_pages``);
  - ``/studies/{rs}/export.{fmt}`` and ``/api/v1/studies/{rs}/export/{fmt}`` (``console.entry_pages``): the data
    core's records;
  - ``/studies/{rs}/edc/export.odm.xml`` and ``/api/v1/studies/{rs}/edc/export/odm`` (``console.edc_pages``);
  - ``/studies/{rs}/edc/copy.csv`` and ``/api/v1/studies/{rs}/edc/copy`` (``console.copy_assist_page``).

Not held, and why: ``/reports/research-office.xlsx`` (counts per study with small cells suppressed, no person),
``/pilot/jobs/{id}/sponsor-pack.zip`` (a FEAS job's aggregate files only), ``/week`` (the list of studies; a single
study's list is the guarded week page it redirects to).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from tb_common import rc1_refusals

from console import i18n_rc1
from console.home import Helpers
from console.i18n import CATALOGUES

log = logging.getLogger("console.rc1")

for _lang, _cat in (("en", i18n_rc1.EN), ("ja", i18n_rc1.JA), ("zh-TW", i18n_rc1.ZH)):
    CATALOGUES[_lang].update(_cat)

#: the audited event of a refusal: the console's "page refused" (its family is the console's, D-718)
EVENT = "console.denied"
#: the jobs whose card shows a list of patients or one patient's sheet (``orchestrator.scheduler.require_released``)
LIST_JOBS = frozenset({"SCREEN", "MICROBATCH", "COHORT", "NAV", "CASE"})
LISTS = "lists"
DOWNLOADS = "downloads"
JOB_CARD = re.compile(r"^/pilot/jobs/(?P<job>[^/]+)$")
JOB_FILE = re.compile(r"^/pilot/jobs/(?P<job>[^/]+)/(?:files|view)/(?P<name>[^/]+)$")
#: (pattern, what it holds) of every route refused as a whole; see the module's text for each one's reason
ROUTES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), kind)
    for p, kind in (
        (r"^/studies/[^/]+/week$", LISTS),
        (r"^/studies/[^/]+/cohort$", LISTS),
        (r"^/studies/[^/]+/screening-log\.xlsx$", DOWNLOADS),
        (r"^/pilot/registry/[^/]+/export\.xlsx$", DOWNLOADS),
        (r"^/studies/[^/]+/enrolment\.[^/]+$", DOWNLOADS),
        (r"^/api/v1/studies/[^/]+/enrolment/[^/]+$", DOWNLOADS),
        (r"^/studies/[^/]+/export\.[^/]+$", DOWNLOADS),
        (r"^/api/v1/studies/[^/]+/export/[^/]+$", DOWNLOADS),
        (r"^/studies/[^/]+/edc/export\.odm\.xml$", DOWNLOADS),
        (r"^/api/v1/studies/[^/]+/edc/export/odm$", DOWNLOADS),
        (r"^/studies/[^/]+/edc/copy\.csv$", DOWNLOADS),
        (r"^/api/v1/studies/[^/]+/edc/copy$", DOWNLOADS),
    )
)


class Rc1Guard:
    """The guard of one console app: the box's environment (the console's settings) and the refusals."""

    def __init__(self, h: Helpers, environment: str) -> None:
        self.h = h
        self.env = {"TB_ENV": environment}

    # ------------------------------------------------------------------ the two questions of the table
    def lists_refused(self) -> bool:
        return rc1_refusals.refused("live_patient_lists", self.env)

    def downloads_refused(self) -> bool:
        return rc1_refusals.refused("patient_mail_and_downloads", self.env)

    # ------------------------------------------------------------------ which refusal a request meets
    def _job(self, job_id: str) -> Any:
        """The job, None when there is none (the route answers 404); a store that does not answer is refused."""
        try:
            return self.h.bk.get_job(job_id)
        except KeyError:
            return None

    def refusal_of(self, method: str, path: str) -> str | None:
        """The name of the refusal this request meets, or None."""
        if method.upper() not in ("GET", "HEAD"):
            return None
        for pattern, kind in ROUTES:
            if pattern.match(path):
                return self._named(kind)
        if m := JOB_CARD.match(path):
            if not self.lists_refused():
                return None
            try:
                job = self._job(m["job"])
            except Exception:  # the store does not answer: refused, never shown unchecked
                return "live_patient_lists"
            return "live_patient_lists" if job is not None and job.type in LIST_JOBS else None
        if m := JOB_FILE.match(path):
            if not self.downloads_refused():
                return None
            try:
                job = self._job(m["job"])
            except Exception:
                return "patient_mail_and_downloads"
            out = next((o for o in (job.outputs or []) if o.filename == m["name"]), None) if job else None
            return "patient_mail_and_downloads" if out is not None and out.tag != "aggregate" else None
        return None

    def _named(self, kind: str) -> str | None:
        if kind == LISTS:
            return "live_patient_lists" if self.lists_refused() else None
        return "patient_mail_and_downloads" if self.downloads_refused() else None

    # ------------------------------------------------------------------ the refusal
    def session(self, request: Request) -> Any:
        """The live session of the request, None without one (reads only, as ``console.demo_guard`` does)."""
        from console.app import COOKIE  # console.app imports this module

        try:
            if request.url.path.startswith("/api/"):
                auth = request.headers.get("authorization") or ""
                token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
                return self.h.users.session(token, touch=False, api=True) if token else None
            return self.h.users.session(request.cookies.get(COOKIE), touch=False)
        except Exception as e:  # the store is down: the refusal stands, without a name
            log.warning("rc1 guard: session not read (%s)", type(e).__name__)
            return None

    def refuse(self, request: Request, name: str) -> Response:
        row = rc1_refusals.row(name)
        environment = rc1_refusals.environment(self.env)
        sess = self.session(request)
        who = f"console:{sess.user.username}" if sess is not None else "console:-"
        try:  # the path only: never a query or a body
            detail = {"refusal": name, "environment": environment, "action": request.url.path[:120]}
            self.h.au.append(EVENT, actor=who, detail=detail)
        except Exception:
            log.exception("rc1 guard: the refusal of %s was not audited", request.url.path[:120])
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": row.key, "detail": {"environment": environment}}, status_code=403)
        return self.h.page(request, "problem.html", sess, status=403, key=row.key,
                           values={"environment": environment})  # fmt: skip

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        name = self.refusal_of(request.method, request.url.path)
        if name is None:
            return await call_next(request)
        return self.refuse(request, name)  # before the route: nothing is read, rendered or sent


def register(app: FastAPI, h: Helpers, environment: str) -> Rc1Guard:
    """Install the guard on the console app: the middleware, appended as ``console.demo_guard`` appends its own."""
    g = Rc1Guard(h, environment)
    app.state.rc1_guard = g
    app.user_middleware.append(Middleware(BaseHTTPMiddleware, dispatch=g.dispatch))
    return g
