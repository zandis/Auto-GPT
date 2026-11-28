"""rc1's refusals in the console (the owner's ruling of 2026-11-20; review R22-34; ``tb_common.rc1_refusals``).

**Fail-closed by construction** (the integrator's ruling 7082962352): on a box the table refuses (PRODUCTION, an
unset ``TB_ENV`` and an unknown one; DEV, TEST and VALIDATION are allowed, D-1072) the console serves only
:data:`ALLOWED`: signing in and out, health, the ops and admin pages, aggregate counts and static files. Every other
route answers rc1's refusal whatever its method: ``patient_mail_and_downloads`` for a route that gives a file
(:data:`DOWNLOADS`), ``live_patient_lists`` for any other. A route the list does not know is refused. The deny-list
of the first version was dropped because two reviews found routes it missed.

The guard is the console's outermost middleware (``console.app`` registers it last, with ``add_middleware``), so it
reads the address as the browser sent it, before any rewrite (the people lists of J-5 included), and nothing inside
runs for a refused request: nothing is read from the store, rendered or sent. The refusal is the console's problem
page (403) with the table's message in the reader's language, JSON on ``/api/``, and one audited ``console.denied``
event with the refusal's name, the environment and the path (never a query or a body).

Two routes are allowed by what they hold, read from the job: ``/pilot/jobs/{id}``, the card of a job that lists no
patient (FEAS, CONSENT ...; a SCREEN, MICROBATCH, COHORT, NAV or CASE card shows its list or a case sheet), and a
job's aggregate file (``/pilot/jobs/{id}/files/{name}`` and ``/view/{name}``). A store that does not answer is a
refusal.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket
from tb_common import rc1_refusals

from console import i18n_rc1
from console.home import Helpers
from console.i18n import CATALOGUES

log = logging.getLogger("console.rc1")

for _lang, _cat in (("en", i18n_rc1.EN), ("ja", i18n_rc1.JA), ("zh-TW", i18n_rc1.ZH)):
    CATALOGUES[_lang].update(_cat)

#: the audited event of a refusal: the console's "page refused" (its family is the console's, D-718)
EVENT = "console.denied"
#: the jobs whose card shows a list of patients, one patient's sheet or a pseudonym (the list jobs of
#: ``orchestrator.scheduler.require_released``, and SUBMIT, whose card names the patient it submits)
LIST_JOBS = frozenset({"SCREEN", "MICROBATCH", "COHORT", "NAV", "CASE", "SUBMIT"})  # SUBMIT: its card shows a pid
JOB_CARD = re.compile(r"^/pilot/jobs/(?P<job>[^/]+)$")
JOB_FILE = re.compile(r"^/pilot/jobs/(?P<job>[^/]+)/(?:files|view)/(?P<name>[^/]+)$")
#: what a refused box still serves: (pattern, what it is). Every method of a matching path.
ALLOWED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), why)
    for p, why in (
        (r"^/login(?:/totp|/first-run(?:/answers)?)?$", "sign-in"),
        (r"^/logout$", "sign-out"),
        (r"^/enrol$", "sign-in: the second factor's enrolment"),
        (r"^/auth/oidc/(?:start|callback)$", "sign-in by the hospital's identity provider"),
        (r"^/api/v1/session$", "sign-in and sign-out on the API"),
        (r"^/account(?:/password|/prefs)?$", "sign-in: the account's password and its own preferences"),
        (r"^/(?:lang|role)$", "sign-in: the session's language and acting role"),
        (r"^/demo/ack$", "sign-in: the demonstration's acknowledgement"),
        (r"^/healthz$", "health"),
        (r"^/metrics$", "health: the box's metrics"),
        (r"^/$", "the administrator's overview (any other role is sent to its home page, which is refused)"),
        (r"^/jobs$", "ops: the jobs by their metadata"),
        (r"^/ops/(?:accounts/requests|flags|identity|ingest|notices|users)$", "ops pages"),
        (r"^/admin$", "admin: the administrator's page"),
        (r"^/admin/(?:accounts|edc|notice|redcap|ops)$", "admin pages: accounts, EDC, notice, REDCap, operations"),
        (r"^/admin/jobs/[^/]+/(?:cancel|retry)$", "admin: a job cancelled or retried, by its id"),
        (r"^(?:/api/v1)?/admin/still-needed(?:/[^/]+)?$", "admin: the site information still needed, by its keys"),
        (r"^/admin/models/canary$", "admin: the models' canary"),
        (r"^(?:/api/v1)?/admin/(?:health|data-step)$", "admin: M5's health page and data step (counts and ages)"),
        (r"^/admin/ops/network/[^/]+$", "admin: hospital IT's network sheet"),
        (r"^/admin/ops/[^/]+$", "admin: an operations request (backup, update, logs)"),
        (r"^/admin/redcap/[^/]+/test$", "admin: a REDCap connection's test"),
        (r"^/api/v1/admin/ops$", "ops on the API"),
        (r"^/audit$", "admin: the audit log"),
        (r"^(?:/api/v1)?/audit/verify$", "admin: the audit chain's check"),
        (r"^/reports(?:/research-office(?:\.xlsx)?)?$", "aggregate counts (small cells suppressed, D-270)"),
        (r"^/pilot/jobs/[^/]+/sponsor-pack\.zip$", "aggregate counts: a FEAS job's aggregate files (D-101)"),
        (r"^/static/.*$", "static files"),
        (r"^/(?:favicon\.ico|manifest\.webmanifest)$", "static files"),
        (r"^/(?:help(?:/guide)?|about(?:/NOTICE\.txt)?)$", "static files: the help and the notices"),
    )
)
#: the refused routes that give a file: refused as ``patient_mail_and_downloads``; any other as a live list
DOWNLOADS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"\.(?:xlsx|csv|zip|pdf|xml|json|txt)$",  # a file named by its address
        r"^/pilot/jobs/[^/]+/(?:files|view)/[^/]+$",
        r"^/pilot/cascade/[^/]+/files/[^/]+$",
        r"^/api/v1/studies/[^/]+/(?:enrolment|export)/[^/]+$",
        r"^/api/v1/studies/[^/]+/edc/(?:export/odm|copy)$",
        r"^/studies/[^/]+/edc/copy/[^/]+$",
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
        """The job, None when there is none (the route answers 404); a store that does not answer raises."""
        try:
            return self.h.bk.get_job(job_id)
        except KeyError:
            return None

    def _name_of(self, path: str) -> str:
        return "patient_mail_and_downloads" if any(p.search(path) for p in DOWNLOADS) else "live_patient_lists"

    def refusal_of(self, method: str, path: str, query: str = "") -> str | None:
        """The name of the refusal this request meets, or None. Every method (a websocket too); fail-closed: what
        :data:`ALLOWED` does not name is refused. ``query``: the audit page filtered to one patient is that patient's
        list (``/audit?pid=``, as ``/audit/patients/{pid}``), so it is refused."""
        name = self._name_of(path)
        if not (self.downloads_refused() if name == "patient_mail_and_downloads" else self.lists_refused()):
            return None
        if path == "/audit" and any(v.strip() for v in parse_qs(query).get("pid", [])):
            return name  # the audit log of one patient
        if any(p.match(path) for p, _ in ALLOWED):
            return None
        if m := JOB_CARD.match(path):
            try:
                job = self._job(m["job"])
            except Exception:  # the store does not answer: refused, never shown unchecked
                return name
            return name if job is not None and job.type in LIST_JOBS else None
        if m := JOB_FILE.match(path):
            try:
                job = self._job(m["job"])
            except Exception:
                return name
            out = next((o for o in (job.outputs or []) if o.filename == m["name"]), None) if job else None
            return name if out is None or out.tag != "aggregate" else None
        return name

    # ------------------------------------------------------------------ the refusal
    def session(self, request: HTTPConnection) -> Any:
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

    def refuse(self, request: HTTPConnection, name: str, path: str) -> Response:
        row = rc1_refusals.row(name)
        environment = rc1_refusals.environment(self.env)
        sess = self.session(request)
        who = f"console:{sess.user.username}" if sess is not None else "console:-"
        try:  # the path only: never a query or a body
            detail = {"refusal": name, "environment": environment, "action": path[:120]}
            self.h.au.append(EVENT, actor=who, detail=detail)
        except Exception:
            log.exception("rc1 guard: the refusal of %s was not audited", path[:120])
        if request.scope["type"] == "websocket":  # closed before it is accepted: nothing is sent
            return Response(status_code=403)
        if path.startswith("/api/"):
            return JSONResponse({"error": row.key, "detail": {"environment": environment}}, status_code=403)
        return self.h.page(request, "problem.html", sess, status=403, key=row.key,
                           values={"environment": environment})  # fmt: skip


def _path(scope: Scope) -> str:
    """The address as the console's routes read it: without the root path a proxy mounts it under."""
    path, root = str(scope.get("path") or "/"), str(scope.get("root_path") or "")
    return (path[len(root) :] or "/") if root and path.startswith(root) else path


class Rc1Layer:
    """The guard as a plain ASGI layer, the console's outermost: every HTTP request and every websocket meets it
    before any other middleware (``BaseHTTPMiddleware`` lets a websocket through unasked)."""

    def __init__(self, app: ASGIApp, guard: Rc1Guard) -> None:
        self.app = app
        self.guard = guard

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = _path(scope)
        method = str(scope.get("method") or "WEBSOCKET")
        query = bytes(scope.get("query_string") or b"").decode("latin-1")
        name = await run_in_threadpool(self.guard.refusal_of, method, path, query)  # it may ask the job store
        if name is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await run_in_threadpool(self.guard.refuse, WebSocket(scope, receive, send), name, path)
            await send({"type": "websocket.close", "code": 1008})  # policy violation, before accept
            return
        resp = await run_in_threadpool(self.guard.refuse, Request(scope, receive), name, path)
        from console.app import CSP  # outermost: the console's headers middleware never sees this answer

        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        await resp(scope, receive, send)  # before the route: nothing is read, rendered or sent


def register(app: FastAPI, h: Helpers, environment: str) -> Rc1Guard:
    """Install the guard as the console's outermost middleware: ``console.app`` calls this after every other
    middleware is added, and ``add_middleware`` puts it in front of them all."""
    g = Rc1Guard(h, environment)
    app.state.rc1_guard = g
    app.add_middleware(Rc1Layer, guard=g)
    return g
