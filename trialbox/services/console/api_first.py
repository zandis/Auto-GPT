"""T-657 (D-444): every state-changing ``/api/v1`` route checks the session, and the permit that does not depend on
the body, before FastAPI reads the body (ROLE-019).

FastAPI validates a request body before the handler runs, and the handlers asked for the session and the permit
first thing inside. So an anonymous POST answered 422 with the body's schema instead of 401, and an account the
handler would refuse got 422 too: the role x route matrix scored about twenty API rows "Y" for every role.

The console's router builds every route with :class:`GuardedRoute` (``install``), so a route any module adds later
gets the same guard without a hand-kept list:

- the route's first dependency signs the bearer token in (``Helpers.api_session``: 401, the must-change refusal and
  the scope check of D-146), before body validation;
- then the endpoint's own pre-body check runs, declared at the route with ``@before_body(check)``: the module's
  existing guard (study visible, role row, delegation task) with the session; ``check(sess, request)`` raises the
  refusal. Where the exact permit row depends on the body (switch on or off, a mark that needs "approach" or
  "screen"), the check refuses an account that holds none of the possible rows; the handler still asks the exact
  one, so nothing here is more permissive than the handler's ``permit`` call.
- a body that is not JSON at all fails before any dependency; ``validation_first`` answers it with the same guard,
  so it too gets 401 or 403 before 422.

``@page_twin(path)`` names, at an ``/api/v1`` route, the page route it is the twin of when the two paths differ
(FIT-019, D-125: every screen action through the token API). ``tests/console/test_api_twin_check.py`` walks the
route table and holds both rules."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

API = "/api/v1/"
CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# (method, path) -> why the route runs without a session. Short on purpose; the twin-check test reads it.
SESSION_OPEN: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/session"): "signing in: it is what gives the session",
    ("DELETE", "/api/v1/session"): "signing out: ends the token it is given and answers ok without one",
}
PRE_BODY = "__tb_before_body__"
TWINS = "__tb_page_twins__"

Check = Callable[[Any, Request], None]


def before_body(check: Check) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare the endpoint's permit check that does not need the body; put it under ``@app.post(...)``."""

    def mark(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, PRE_BODY, check)
        return fn

    return mark


def page_twin(*paths: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare the page route(s) this ``/api/v1`` route is the twin of, when the paths differ (FIT-019)."""

    def mark(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, TWINS, (*getattr(fn, TWINS, ()), *paths))
        return fn

    return mark


def guarded(path: str, methods: Any) -> bool:
    """A state-changing ``/api/v1`` route that is not one of the session's own routes."""
    ms = {str(m).upper() for m in methods or ()}
    return path.startswith(API) and bool(ms & CHANGING) and not any((m, path) in SESSION_OPEN for m in ms)


def _run(request: Request, check: Check | None) -> None:
    h = request.app.state.helpers
    sess = h.api_session(request)  # 401 / 403 must-change / D-146 scope refusal
    if check is not None:
        check(sess, request)


def _guard_for(endpoint: Callable[..., Any]) -> Callable[[Request], None]:
    check: Check | None = getattr(endpoint, PRE_BODY, None)

    def api_first(request: Request) -> None:
        _run(request, check)

    api_first.__tb_api_first__ = True  # type: ignore[attr-defined]
    return api_first


def is_guard(call: Any) -> bool:
    return bool(getattr(call, "__tb_api_first__", False))


class GuardedRoute(APIRoute):
    """An ``APIRoute`` whose state-changing ``/api/v1`` routes depend first on :func:`_guard_for`."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        if guarded(path, kwargs.get("methods")):
            kwargs["dependencies"] = [Depends(_guard_for(endpoint)), *(kwargs.get("dependencies") or [])]
        super().__init__(path, endpoint, **kwargs)


async def validation_first(request: Request, exc: Exception) -> Response:
    """A body FastAPI could not even parse fails before the dependencies: the guard runs here first."""
    route = request.scope.get("route")
    if isinstance(route, APIRoute) and guarded(route.path, {request.method}):
        try:
            await run_in_threadpool(_run, request, getattr(route.endpoint, PRE_BODY, None))
        except Exception as refusal:  # answered by the app's own handler (an exception here is not re-dispatched)
            for kind in type(refusal).__mro__:
                handler = request.app.exception_handlers.get(kind)
                if handler is not None:
                    return await handler(request, refusal)  # type: ignore[no-any-return]
            raise
    assert isinstance(exc, RequestValidationError)
    return await request_validation_exception_handler(request, exc)


def install(app: FastAPI) -> None:
    """Call right after ``FastAPI(...)``, before any route is added."""
    app.router.route_class = GuardedRoute
    app.add_exception_handler(RequestValidationError, validation_first)
