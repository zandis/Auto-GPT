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

for _lang, _cat in (("en", i18n_support.EN), ("ja", i18n_support.JA), ("zh-TW", i18n_support.ZH)):
    CATALOGUES[_lang].update(_cat)


def _detail(s: SupportSession) -> dict[str, Any]:
    return {"session": s.id, "started_by": s.started_by, "started_at": s.started_at, "ends_at": s.ends_at,
            **({"ticket": s.ticket} if s.ticket else {})}  # fmt: skip


class SupportGuard:
    """The middleware: reads the state once per request, marks the request for ``permit``, explains a refusal."""

    def __init__(self, h: Helpers, store: SupportSessionStore) -> None:
        self.h = h
        self.store = store

    def state(self) -> tuple[SupportSession | None, bool]:
        """(the open session, closed on doubt). An automatic end found here is audited by this call only."""
        try:
            live, lapsed = self.store.current(self.h.clock())
        except Exception as e:
            log.warning("support session: state not read (%s); patient pages stay closed", type(e).__name__)
            return None, True
        for s in lapsed:
            self.h.au.append("console.support_session_end", actor=SYSTEM,
                             detail={**_detail(s), "how": "auto", "ended_at": s.ended_at})  # fmt: skip
        return live, False

    def session(self, request: Request) -> Any:
        from console.app import COOKIE  # console.app imports this module

        try:
            return self.h.users.session(request.cookies.get(COOKIE), touch=False)
        except Exception:
            return None

    def refusal(self, request: Request, live: SupportSession | None) -> Response:
        key = ON if live is not None else UNKNOWN
        until = local_time(live.ends_at, site_zone(self.h.bk), 16) if live is not None else ""
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": key, "detail": {"until": live.ends_at if live else ""}}, status_code=403)
        return self.h.page(request, "problem.html", self.session(request), status=403, key=key,
                           values={"until": until})  # fmt: skip

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path.startswith("/static/"):
            return await call_next(request)
        live, unknown = await run_in_threadpool(self.state)
        request.state.support_session = live  # the banner (templates/_support_banner.html)
        request.state.support_unknown = unknown
        token = authz.support_session_begin(live is not None or unknown)
        try:
            resp = await call_next(request)
            if (live is not None or unknown) and resp.status_code == 403:
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
        live = getattr(request.state, "support_session", None)
        return h.page(request, "support_session.html", sess, live=live, recent=st.recent(),
                      minutes=authz.SUPPORT_SESSION_MINUTES, done=done if done in ("start", "end") else "",
                      err=err if err.startswith("support.err.") else "")  # fmt: skip

    @app.post(PAGE)
    def start(request: Request, csrf: str = Form(""), ticket: str = Form(""), confirm: str = Form("")) -> Response:
        sess = admin(request, csrf)
        if confirm != "yes":  # runbook 21 rules 1 and 2, ticked: a form posted without it starts nothing
            return RedirectResponse(f"{PAGE}?err=support.err.confirm", status_code=303)
        try:
            s = st.start(sess.user.username, ticket[:80], h.clock())
        except SupportError as exc:
            return RedirectResponse(f"{PAGE}?err={exc}", status_code=303)
        h.au.append("console.support_session_start", actor=h.actor(sess), detail=_detail(s))
        return RedirectResponse(f"{PAGE}?done=start", status_code=303)

    @app.post(PAGE + "/end")
    def end(request: Request, csrf: str = Form(""), session: int = Form(0)) -> Response:
        sess = admin(request, csrf)
        try:
            s = st.end(session, sess.user.username, h.clock())
        except SupportError as exc:
            return RedirectResponse(f"{PAGE}?err={exc}", status_code=303)
        h.au.append("console.support_session_end", actor=h.actor(sess),
                    detail={**_detail(s), "how": "hand", "ended_at": s.ended_at})  # fmt: skip
        return RedirectResponse(f"{PAGE}?done=end", status_code=303)

    return st
