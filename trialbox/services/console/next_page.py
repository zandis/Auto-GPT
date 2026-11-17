"""D-777 (UX-007): after a session ends, the person comes back to the page they were on.

The page is kept in a short cookie (:data:`NEXT_COOKIE`, 15 minutes, HttpOnly, SameSite=Strict) when a request finds
no live session (``console.app``), and used once at the end of a sign-in, with or without the authenticator step
(``console.app``, ``console.identity``). Only a path of this console is kept (:func:`safe_next`): never another
origin, never the sign-in pages themselves, never an API route."""

from __future__ import annotations

from urllib.parse import quote, unquote, urlsplit

from starlette.requests import Request
from starlette.responses import Response

from console.local_path import is_local

NEXT_COOKIE = "tb_console_next"
MAX_AGE = 900
_NOT_KEPT = ("/login", "/logout", "/enrol", "/api/", "/auth/", "/static/")


def safe_next(raw: str | None) -> str:
    """``raw`` when it is a path of this console worth returning to (with its query), else ""."""
    p = (raw or "").strip()
    if len(p) > 400 or not is_local(p):  # lane J's finding: every control, and "//" hidden by whitespace
        return ""
    path = urlsplit(p).path
    if any(path == x.rstrip("/") or path.startswith(x) for x in _NOT_KEPT):
        return ""
    return p


def page_of(request: Request) -> str:
    """The page the request belongs to: a GET's own path and query; for another method, the Referer's path and query
    when it is this console's own origin."""
    if request.method == "GET":
        q = request.url.query
        return safe_next(request.url.path + (f"?{q}" if q else ""))
    ref = urlsplit(request.headers.get("referer") or "")
    if ref.netloc and ref.netloc != request.url.netloc:
        return ""
    return safe_next(ref.path + (f"?{ref.query}" if ref.query else "")) if ref.path else ""


def remember(resp: Response, page: str, secure: bool) -> None:
    if page:
        resp.set_cookie(NEXT_COOKIE, quote(page, safe=""), max_age=MAX_AGE, httponly=True, samesite="strict",
                        secure=secure)  # fmt: skip


def take(request: Request, resp: Response) -> None:
    """Send ``resp`` (a redirect after sign-in) to the kept page, if any, and forget it."""
    page = safe_next(unquote(request.cookies.get(NEXT_COOKIE) or ""))
    if page:
        resp.headers["location"] = page
    resp.delete_cookie(NEXT_COOKIE)
