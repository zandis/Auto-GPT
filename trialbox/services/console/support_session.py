"""The support-session switch (card 10K-15, D-1364; owner decision 99: no standing access for support; SO-15).

Runbook 21's supervised remote session is the hospital's own screen share from a hospital PC. Before it starts, the
hospital's administrator turns this switch on at ``/ops/support-session`` (an optional ticket number). While it is on:

* every patient-level page and route is refused to **every** role. The refusal sits in the one permission function,
  ``tb_common.authz.permit``: this module marks each request as under a support session, and ``permit`` then refuses
  every action outside ``SUPPORT_SESSION_OPEN`` (the operations and account rows, the switch itself). A patient page
  asks ``permit`` (T-102c, D-425), so a new one is closed by construction, and so is a new matrix row;
* a refusal (403) says, in the page's language, that a support session is running and when it ends at the latest;
  ``/api/v1`` answers ``{"error": "support.session_on"}``;
* the review of aeb978e6: a page that mixes staff and patient-linked content is an open row, so the closing is also
  content-based: the helpers that hand a page patient-linked content ask ``tb_common.authz.session_on()`` and answer
  nothing (the page says what is closed); a job's pages and files are closed unless named in
  ``JOBS_OPEN_DURING_A_SESSION`` and ``DOWNLOADS_OPEN_DURING_A_SESSION`` (the ``aggregate`` tag is not trusted); an
  answer begun before a start that ends after it is refused, and a start waits for those answers (H4); mail is held
  at the mail gateway (H5, D-1364);
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
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from tb_common import authz

from console import form_errors, i18n_support
from console.breakglass_store import _TICKET, SupportError, SupportSession, SupportSessionStore
from console.home import Helpers
from console.i18n import CATALOGUES
from console.timefmt import local_time, site_zone

log = logging.getLogger("console.support_session")
PAGE = "/ops/support-session"
ON = "support.session_on"  # the refusal while a session runs
UNKNOWN = "support.session_unknown"  # the refusal when the state could not be read (closed on doubt)
SYSTEM = "console:support-session"  # the actor of an automatic end
SWITCH_ROUTES = frozenset({PAGE, PAGE + "/end"})  # the switch's own answers are never refused by it
# The review of aeb978e6 (H2, H3): a job's pages and files are open rows that can carry patient-linked content (a
# CASE sheet, a SUBMIT job's pid, a NAV draft named by a pseudonym, an ingest report whose validation messages name a
# patient though it is tagged aggregate). During a session they are closed by default; open are only the job types
# and the files named here, each with why it holds no patient-linked field. A new job type or file is closed until
# it is added after a review.
_JOB_ROUTE = re.compile(r"^/pilot/jobs/([0-9A-HJKMNP-TV-Z]{26})(/.*)?$")
JOBS_OPEN_DURING_A_SESSION: dict[str, str] = {
    "FEAS": "the feasibility counts per criterion and step; its patient-level file is not given (below)",
    "SCREEN": "the run's counts; its rows ask phi.view (closed) and its candidate list is not read (home.load)",
}
# (job type, file name pattern, why): every other file of every job is refused during a session, whatever its tag
DOWNLOADS_OPEN_DURING_A_SESSION: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("FEAS", re.compile(r"^feasibility_[A-Za-z0-9_.-]+(?<!\.raw)\.(?:pdf|json)$"),
     "the feasibility report: counts per criterion and step, small counts suppressed; never a row"),
    ("FEAS", re.compile(r"^feasprofile_[A-Za-z0-9_.-]+\.json$"),
     "the site profile the report used: settings and coverage counts, no patient"),
)  # fmt: skip
# the routes of one job that serve a file or a patient's data: closed unless the file is in the list above
_JOB_FILE = re.compile(r"^/(?:files|view)/([^/]+)$")
_JOB_CLOSED = re.compile(r"^/(?:sponsor-pack\.zip|reveal|release)$")
_CASCADE_FILE = re.compile(r"^/pilot/cascade/[^/]+/files/")  # a cascade run's files: not reviewed, so closed
# H4: a start waits at most this long for the answers begun before it (in this process) to be sent or refused
DRAIN_S = 15.0
_STALE_S = 600.0  # an answer whose body was never read (the client went away) stops counting after this


def download_open(job_type: str, filename: str) -> bool:
    """Is this job's file in ``DOWNLOADS_OPEN_DURING_A_SESSION``?"""
    return any(job_type == k and rx.match(filename) for k, rx, _ in DOWNLOADS_OPEN_DURING_A_SESSION)


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
        self._lock = threading.Lock()
        self._open: dict[int, float] = {}  # H4: answers begun outside a session, body not yet sent
        self._seq = 0
        self.generation = 0  # one more at each start in this process

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

    def closed_route(self, request: Request) -> bool:
        """A job's page or file that is not in the lists above (closed by default), or a cascade run's file. Asked only
        for a signed-in request (a signed-out one gets the route's own sign-in answer, the review's item 8: no job
        type is told to a stranger); the refusal is audited as every other (``console.denied``)."""
        path = request.url.path
        m = _JOB_ROUTE.match(path)
        if m is None and not _CASCADE_FILE.match(path):
            return False
        sess = self.session(request)
        if sess is None:
            return False
        if m is not None:
            try:
                job = self.h.bk.get_job(m.group(1))
            except Exception:
                job = False  # closed on doubt
            if job is None:
                return False  # no such job: the route's own 404
            kind = str(getattr(job, "type", "")) if job else ""
            rest = m.group(2) or ""
            f = _JOB_FILE.match(rest)
            if (
                job
                and kind in JOBS_OPEN_DURING_A_SESSION
                and not _JOB_CLOSED.match(rest)
                and (f is None or download_open(kind, f.group(1)))
            ):
                return False
        self.h.au.append("console.denied", actor=self.h.actor(sess),
                         detail={"action": path[:80], "why": "support session"})  # fmt: skip
        return True

    # ------------------------------------------------------------------ H4: answers begun before a start
    def _enter(self) -> int:
        with self._lock:
            self._seq += 1
            self._open[self._seq] = time.monotonic()
            return self._seq

    def _leave(self, n: int) -> None:
        with self._lock:
            self._open.pop(n, None)

    def running(self) -> int:
        """Answers of this process begun outside a session whose body is not yet sent (a stale one not counted)."""
        cut = time.monotonic() - _STALE_S
        with self._lock:
            return sum(1 for t in self._open.values() if t > cut)

    def drain(self, own: int = 1, wait_s: float | None = None) -> bool:
        """After a start: wait until the answers begun before it in this process (``own``: the start's own) are sent
        or refused, at most ``wait_s``. True when none is left. Every one still running is refused at its end, or
        stopped at its next part (``_track``), so what the confirmation says holds."""
        end = time.monotonic() + (DRAIN_S if wait_s is None else wait_s)
        while self.running() > own:
            if time.monotonic() >= end:
                return False
            time.sleep(0.05)
        return True

    def started_here(self) -> None:
        """A session started in this process: an answer begun before it stops at its next part."""
        with self._lock:
            self.generation += 1

    def _track(self, resp: Response, n: int) -> Response:
        inner = getattr(resp, "body_iterator", None)
        if inner is None:
            self._leave(n)
            return resp
        gen = self.generation

        async def body() -> Any:
            try:
                async for chunk in inner:
                    if self.generation != gen:
                        log.warning("support session: an answer begun before the start was stopped")
                        break
                    yield chunk
            finally:
                self._leave(n)

        resp.body_iterator = body()  # type: ignore[attr-defined]
        return resp

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path.startswith("/static/"):
            return await call_next(request)
        live, unknown = await run_in_threadpool(self.state)
        request.state.support_session = live  # the banner (templates/_support_banner.html)
        request.state.support_unknown = unknown
        marked = live is not None or unknown
        n = 0 if marked else self._enter()
        token = authz.support_session_begin(marked)
        try:
            if marked and await run_in_threadpool(self.closed_route, request):
                return self.refusal(request, live)
            resp = await call_next(request)
            if marked and resp.status_code == 403:
                resp = self.refusal(request, live)  # rendered under the mark: its menu offers no patient page
            elif not marked and request.url.path not in SWITCH_ROUTES:
                # H4: begun before a session, done after it started: refused before a byte of it leaves
                live2, unknown2 = await run_in_threadpool(self.state)
                if live2 is not None or unknown2:
                    request.state.support_session = live2
                    again = authz.support_session_begin(True)
                    try:
                        resp = self.refusal(request, live2)
                    finally:
                        authz.support_session_end(again)
            if n:
                resp, n = self._track(resp, n), 0
        finally:
            if n:
                self._leave(n)
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

    def render(request: Request, sess: Any, done: str = "", err: str = "", wait: str = "", fe: Any = None,
               status: int = 200) -> Response:  # fmt: skip
        # every row not ended, read without its times, so that a damaged row can always be ended from here
        rows = st.open_rows()
        # the review's item 9: the confirmation says what is true now, not what the URL says: "on" only while a
        # session is open (this request ran under it), "ended" only while none is
        on = bool(rows) and bool(getattr(request.state, "support_session", None) or authz.session_on())
        shown = "start" if done == "start" and on else "end" if done == "end" and not rows else ""
        return h.page(request, "support_session.html", sess, status=status, open_rows=rows, recent=st.recent(),
                      minutes=authz.SUPPORT_SESSION_MINUTES, done=shown, waited=shown == "start" and wait == "1",
                      drain_s=int(DRAIN_S), err=err if err.startswith("support.err.") else "", fe=fe)  # fmt: skip

    @app.get(PAGE)
    def page(request: Request, done: str = "", err: str = "", wait: str = "") -> Response:
        return render(request, admin(request), done, err, wait)

    @app.post(PAGE)
    def start(request: Request, csrf: str = Form(""), ticket: str = Form(""), confirm: str = Form("")) -> Response:
        sess = admin(request, csrf)
        # 9k-6a (D-1376): a wrong ticket or no tick is the form again (400) with the summary tied to each field;
        # runbook 21 rules 1 and 2, ticked: a form posted without the tick starts nothing
        bad = [("ticket", "support.err.ticket")] if ticket.strip() and not _TICKET.match(ticket.strip()) else []
        bad += [("confirm", "support.err.confirm")] if confirm != "yes" else []
        if bad:
            fe = form_errors.failed("support-start", "support", bad, {"ticket": ticket[:80], "confirm": confirm})
            return render(request, sess, fe=fe, status=form_errors.FAILED)

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
        # H4: the confirmation is shown only once the answers begun before the start in this process were sent or
        # refused, or after DRAIN_S seconds (then it says so); the console runs as one process (deploy/compose)
        guard.started_here()
        drained = guard.drain()
        return RedirectResponse(f"{PAGE}?done=start" + ("" if drained else "&wait=1"), status_code=303)

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
