"""The support-session switch (card 10K-15, D-1364; owner decision 99: no standing access for support; SO-15).

Runbook 21's supervised remote session is the hospital's own screen share from a hospital PC. Before it starts, the
hospital's administrator turns this switch on at ``/ops/support-session`` (an optional ticket number). While it is on:

* every patient-level page and route is refused to **every** role. The refusal sits in the one permission function,
  ``tb_common.authz.permit``: this module marks each request as under a support session, and ``permit`` then refuses
  every action outside ``SUPPORT_SESSION_OPEN`` (the operations and account rows, the switch itself). A patient page
  asks ``permit`` (T-102c, D-425), so a new one is closed by construction, and so is a new matrix row;
* a refusal (403) says, in the page's language, that a support session is running and when it ends at the latest;
  ``/api/v1`` answers ``{"error": "support.session_on"}``;
* the administrator's pages carry a banner (``templates/_support_banner.html``);
* the start and the end are audit events (``console.support_session_start``, ``console.support_session_end``): who,
  when, the ticket, and how it ended (``hand`` or ``auto``).

**It ends by itself 2 hours after it started**, checked at every request against the stored start time
(``SupportSessionStore.current``): no timer, so a restart or a stopped scheduler can neither keep it on past its 2
hours nor drop it early. The first request after the end writes the row's end (at the latest end, not later) and the
audit event, once. **On doubt the patient pages stay closed:** when the state cannot be read (the trial database does
not answer), the request runs as under a session (``support.session_unknown``).

It narrows only: the one new row (``support.session``) is the administrator's, the hospital's own operator (runbook
21, tier 1), and it opens nothing. No support person signs in; nothing here reads patient data.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from tb_common import authz

from console import i18n_support
from console.breakglass_store import SupportError, SupportSession, SupportSessionStore
from console.home import Helpers
from console.i18n import CATALOGUES
from console.timefmt import local_time, site_zone

log = logging.getLogger("console.support_session")
PAGE = "/ops/support-session"
ON = "support.session_on"  # the refusal while a session runs
UNKNOWN = "support.session_unknown"  # the refusal when the state could not be read (closed on doubt)
SYSTEM = "console:support-session"  # the actor of an automatic end
# the pages of one job: a CASE job is about one patient (its sheet, its counts by criterion), so during a session its
# pages are refused like a patient page, whatever the role (the review of D-1364)
_JOB_PAGE = re.compile(r"^/pilot/jobs/([0-9A-HJKMNP-TV-Z]{26})(?:/|$)")
ONE_PATIENT_JOBS = frozenset({"CASE"})

for _lang, _cat in (("en", i18n_support.EN), ("ja", i18n_support.JA), ("zh-TW", i18n_support.ZH)):
    CATALOGUES[_lang].update(_cat)


# the EDC door's routes a browser opens as a page (D-1364, the review of the EDC door): the EDC's sign-in, and a tool
# call's confirmation posted from the form of /admin/edc; their refusal is the page in the person's language
_EDC_SIGN_IN = "/api/edc/oidc/authorize"
_EDC_CONFIRM = re.compile(r"^/api/edc/tools/[^/]+/confirm$")
_FORM = "application/x-www-form-urlencoded"


def browser_page(request: Request) -> bool:
    """Is a refusal of this request the problem page (else the JSON answer of an ``/api/`` route)?"""
    path = request.url.path
    if not path.startswith("/api/") or path == _EDC_SIGN_IN:
        return True
    return bool(_EDC_CONFIRM.match(path)) and (request.headers.get("content-type") or "").startswith(_FORM)


def _detail(s: SupportSession) -> dict[str, Any]:
    return {"session": s.id, "started_by": s.started_by, "started_at": s.started_at, "ends_at": s.ends_at,
            **({"ticket": s.ticket} if s.ticket else {})}  # fmt: skip


class SupportGuard:
    """The middleware: reads the state once per request, marks the request for ``permit``, explains a refusal."""

    def __init__(self, h: Helpers, store: SupportSessionStore) -> None:
        self.h = h
        self.store = store

    def state(self) -> tuple[SupportSession | None, bool]:
        """(the open session, closed on doubt). The end events not yet written (an automatic end, or one whose
        event failed before) are written here, each once (``SupportSessionStore.audit_end``); one that fails again
        is tried at the next request, and the request goes on."""
        try:
            live, unaudited = self.store.current(self.h.clock(), self.moved_event)
        except Exception as e:
            log.warning("support session: state not read (%s); patient pages stay closed", type(e).__name__)
            return None, True
        for s in unaudited:
            try:
                self.store.audit_end(s.id, self.end_event)
            except Exception as e:
                log.warning("support session %s: end event not written (%s); tried again", s.id, type(e).__name__)
        return live, False

    def moved_event(self, before: SupportSession, after: SupportSession) -> None:
        """A start later than the clock (the clock was moved back) set to the request's time: the trail says so."""
        self.h.au.append("console.support_session_moved", actor=SYSTEM,
                         detail={**_detail(after), "started_at_was": before.started_at})  # fmt: skip

    def end_event(self, s: SupportSession) -> None:
        actor = f"console:{s.ended_by}" if s.how == "hand" and s.ended_by else SYSTEM
        self.h.au.append("console.support_session_end", actor=actor,
                         detail={**_detail(s), "how": s.how or "auto", "ended_at": s.ended_at})  # fmt: skip

    def session(self, request: Request) -> Any:
        from console.app import COOKIE  # console.app imports this module

        try:
            return self.h.users.session(request.cookies.get(COOKIE), touch=False)
        except Exception:
            return None

    def refusal(self, request: Request, live: SupportSession | None) -> Response:
        key = ON if live is not None and live.ends_at else UNKNOWN
        until = local_time(live.ends_at, site_zone(self.h.bk), 16) if live is not None and live.ends_at else ""
        if not browser_page(request):
            return JSONResponse({"error": key, "detail": {"until": live.ends_at if live else ""}}, status_code=403)
        # the page is rendered as if at "/": the refused URL (a study, a pseudonym) is not repeated on it, in a
        # link, a form's way back or the feedback control
        bare = Request({**request.scope, "path": "/", "raw_path": b"/", "query_string": b""}, request.receive)
        return self.h.page(bare, "problem.html", self.session(request), status=403, key=key,
                           values={"until": until})  # fmt: skip

    def one_patient_job(self, path: str) -> bool:
        """A job page about one patient (a CASE job): a patient page, closed during a session to every role."""
        m = _JOB_PAGE.match(path)
        if not m:
            return False
        try:
            job = self.h.bk.get_job(m.group(1))
        except Exception:
            return True  # closed on doubt
        return job is not None and str(getattr(job, "type", "")) in ONE_PATIENT_JOBS

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path.startswith("/static/"):
            return await call_next(request)
        live, unknown = await run_in_threadpool(self.state)
        request.state.support_session = live  # the banner (templates/_support_banner.html)
        request.state.support_unknown = unknown
        marked = live is not None or unknown
        token = authz.support_session_begin(marked)
        try:
            if marked and await run_in_threadpool(self.one_patient_job, request.url.path):
                return self.refusal(request, live)
            resp = await call_next(request)
            if marked and resp.status_code == 403:
                resp = self.refusal(request, live)  # rendered under the mark: its menu offers no patient page
        finally:
            authz.support_session_end(token)
        return resp


def register(app: FastAPI, h: Helpers, store: SupportSessionStore | None = None) -> SupportSessionStore:
    st = store if store is not None else SupportSessionStore()
    guard = SupportGuard(h, st)
    app.state.support_guard = guard
    # appended (innermost, as console.demo_guard): the console's security headers wrap its answers too
    app.user_middleware.append(Middleware(BaseHTTPMiddleware, dispatch=guard.dispatch))

    def admin(request: Request, csrf: str | None = None) -> Any:
        sess = h.need(request)
        if csrf is not None and not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not authz.permit(sess.user.role, "support.session"):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    @app.get(PAGE)
    def page(request: Request, done: str = "", err: str = "") -> Response:
        sess = admin(request)
        # every row not ended, read without its times, so that a damaged row can always be ended from here
        return h.page(request, "support_session.html", sess, open_rows=st.open_rows(), recent=st.recent(),
                      minutes=authz.SUPPORT_SESSION_MINUTES, done=done if done in ("start", "end") else "",
                      err=err if err.startswith("support.err.") else "")  # fmt: skip

    @app.post(PAGE)
    def start(request: Request, csrf: str = Form(""), ticket: str = Form(""), confirm: str = Form("")) -> Response:
        sess = admin(request, csrf)
        if confirm != "yes":  # runbook 21 rules 1 and 2, ticked: a form posted without it starts nothing
            return RedirectResponse(f"{PAGE}?err=support.err.confirm", status_code=303)

        # run before the insert commits: no event, no session. The audit trail is its own store, not this
        # transaction: a commit that fails after the append leaves a start event with no session (D-1364)
        def audit(s: SupportSession) -> None:
            h.au.append("console.support_session_start", actor=h.actor(sess), detail=_detail(s))

        try:
            st.start(sess.user.username, ticket[:80], h.clock(), audit)
        except SupportError as exc:
            return RedirectResponse(f"{PAGE}?err={exc}", status_code=303)
        except Exception as exc:  # the audit trail refused the event: nothing was started
            log.warning("support session not started: the start event was not written (%s)", type(exc).__name__)
            return RedirectResponse(f"{PAGE}?err=support.err.audit", status_code=303)
        return RedirectResponse(f"{PAGE}?done=start", status_code=303)

    @app.post(PAGE + "/end")
    def end(request: Request, csrf: str = Form(""), session: int = Form(0)) -> Response:
        sess = admin(request, csrf)
        try:
            st.end(session, sess.user.username, h.clock(), guard.end_event)
        except SupportError as exc:
            return RedirectResponse(f"{PAGE}?err={exc}", status_code=303)
        except Exception as exc:  # the audit trail refused the event: the session stays on; end it again
            log.warning("support session not ended: the end event was not written (%s)", type(exc).__name__)
            return RedirectResponse(f"{PAGE}?err=support.err.audit", status_code=303)
        return RedirectResponse(f"{PAGE}?done=end", status_code=303)

    return st
