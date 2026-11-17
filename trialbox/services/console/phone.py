"""J-3 (D-1222; the journey review's E-1, E-2/E-M2, E-4, E-M1, E-M4, E-M5): the console on a phone.

* **The flag.** ``layout.phone_first`` (``tb_common.flags``, audited, off by default) is read for each page request by a
  small middleware and kept in ``request.state.phone_first``. ``base.html`` then gives ``<body>`` the class
  ``phone-first``, and the stylesheet's phone-first rules are scoped under it; the week page, the patient sheet, the
  participant's page and the menu's "More" read the same value where the order of the page changes. With the flag
  off every page is as before. It is switched on ``/ops/flags`` by the administrator, with a reason. The read runs in a
  worker thread (never on the event loop), only for pages (not ``/static``, ``/api/``, ``/healthz``, ``/metrics``, the
  manifest, the icons or ``/link``), and its answer, a failed read included (then "off"), is kept 5 seconds: a flag
  store that is down costs at most one attempt per 5 seconds.
* **A link from another site** (a mail, a chat). The session cookie is ``SameSite=Strict`` and stays so: a navigation
  from another site arrives without it. Such a navigation (``Sec-Fetch-Site: cross-site``, ``Sec-Fetch-Mode:
  navigate``) to a console page is answered with the console's own small page ``/link``: "You followed a link to
  <page>. [Continue]". Continue is a tap on this site, so the cookie goes with it: with a live session the page opens,
  without one the sign-in form leads back to it. Continue goes only to an HTML page of this console; a file or an
  action (a name with a dot such as ``.xlsx`` or ``.csv``, an export, a print, a job's files, ``/cmd``, ``/api/``, and
  whatever ``next_page.safe_next`` refuses) goes to the home page instead. So a page on another site can open the
  console, but never download, export, search or act in the person's name, with or without a live session.
* **Add to home screen.** ``/manifest.webmanifest`` (name, colours, start page, two icons) and ``/favicon.ico``, served
  by the box itself from ``static/icons``; no offline mode and no service worker. Both are public, like ``/static``:
  the browser fetches a manifest without the session cookie. They are plain routes, not pages: no session, no audit.

Not here: the form guard and the kept long forms (``static/console.js``, ``data_entry.html``)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import jinja2
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from tb_common.flags import Flags

from console import i18n_phone
from console.i18n import CATALOGUES, pick_language, translate
from console.next_page import safe_next

FLAG = "layout.phone_first"
HERE = Path(__file__).resolve().parent
ICONS = HERE / "static" / "icons"
THEME = "#253a5e"  # the banner's colour (console.css --banner)
BACKGROUND = "#f6f7f9"  # the page's colour (console.css --bg)
#: the browser may keep these a day; a new icon ships with a new box version anyway
CACHE = "public, max-age=86400"
#: how long a read of the flag, a failed one included, is kept (as tb_common.flags.CACHE_SECONDS)
FLAG_SECONDS = 5.0
#: paths that are not pages: the flag is not read for them, and a link from another site to them is not answered
NOT_PAGES = ("/static/", "/api/", "/healthz", "/metrics", "/manifest.webmanifest", "/favicon.ico", "/link")
#: paths a link from another site reaches as before: the sign-in and its steps, the one-time sign-in link (its code
#: rides after "#"), the identity provider's return
ARRIVALS = ("/login", "/logout", "/enrol", "/auth/")
#: path segments of a file, an export or an action: Continue never goes there (a last segment with a dot is a file)
NOT_CONTINUED = ("cmd", "export", "files", "view", "print", "download", "api")

for _lang, _cat in (("en", i18n_phone.EN), ("ja", i18n_phone.JA), ("zh-TW", i18n_phone.ZH)):
    CATALOGUES[_lang].update(_cat)

_clock = time.monotonic
_kept: tuple[bool, float] | None = None
_lock = asyncio.Lock()


def _read() -> bool:
    """One read of the flag store; raises when it does not answer."""
    return Flags().row(FLAG) == "on"


def clear_cache() -> None:
    global _kept
    _kept = None


def _fresh() -> bool | None:
    if _kept is not None and _clock() - _kept[1] < FLAG_SECONDS:
        return _kept[0]
    return None


def _keep(read: Any) -> bool:
    global _kept
    try:
        value = bool(read())
    except Exception:  # the store is down, not installed, no URL: off, and not asked again for 5 s
        value = False
    _kept = (value, _clock())
    return value


def flag_on() -> bool:
    """The flag says ``on``. Off when it is unset, unreadable or there is no flag store (never raises)."""
    got = _fresh()
    return got if got is not None else _keep(_read)


async def flag_on_async() -> bool:
    got = _fresh()
    if got is not None:
        return got
    async with _lock:  # one read at a time; the others take its answer
        got = _fresh()
        if got is not None:
            return got
        value = await run_in_threadpool(_read_safe)
        return _keep(lambda: value)


def _read_safe() -> bool:
    try:
        return _read()
    except Exception:
        return False


def page_path(path: str) -> bool:
    return not any(path == p.rstrip("/") or path.startswith(p) for p in NOT_PAGES)


def continue_to(raw: str) -> str:
    """Where Continue on ``/link`` goes: ``raw`` when it is an HTML page of this console, else the home page."""
    page = safe_next(raw)
    if not page:
        return "/home"
    segments = [s for s in urlsplit(page).path.lower().split("/") if s]
    if not segments or "." in segments[-1] or any(s in NOT_CONTINUED for s in segments):
        return "/home"
    return page


def cross_site_page(scope: Scope) -> bool:
    """A navigation from another site to a page of this console (not an arrival such as the sign-in)."""
    if scope.get("method") != "GET":
        return False
    path = str(scope.get("path", ""))
    if not page_path(path) or any(path == a.rstrip("/") or path.startswith(a) for a in ARRIVALS):
        return False
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    return headers.get("sec-fetch-site") == "cross-site" and headers.get("sec-fetch-mode") == "navigate"


class PhoneFirst:
    """For each page request: a link from another site goes to ``/link``; else the flag into the request's state."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            if cross_site_page(scope):
                query = scope.get("query_string", b"").decode("latin-1")
                asked = str(scope.get("path", "")) + (f"?{query}" if query else "")
                await RedirectResponse("/link?to=" + quote(asked, safe=""), status_code=303)(scope, receive, send)
                return
            if page_path(str(scope.get("path", ""))):
                scope.setdefault("state", {})["phone_first"] = await flag_on_async()
        await self.app(scope, receive, send)


def manifest() -> dict[str, Any]:
    """The web manifest: the console as an app on a phone's home screen, opening the start page in its own window."""
    icon = "/static/icons/icon-{0}.png"
    return {
        "id": "/",
        "name": "TrialBox",
        "short_name": "TrialBox",
        "lang": "en",  # the name is the product's, the same in every language
        "dir": "ltr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "theme_color": THEME,
        "background_color": BACKGROUND,
        "icons": [
            {"src": icon.format(192), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": icon.format(512), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": icon.format(512), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": "/static/icons/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        ],
    }


_pages = jinja2.Environment(loader=jinja2.FileSystemLoader(str(HERE / "templates")), autoescape=True)


def link_page(request: Request) -> Response:
    """``/link``: the console's own page for a link that came from another site (no session is read here)."""
    lang = pick_language(request.headers.get("accept-language"))
    asked = request.query_params.get("to", "")
    target = continue_to(asked)
    shown = urlsplit(safe_next(asked)).path or "/"
    html = _pages.get_template("link_continue.html").render(
        lang=lang, t=lambda key, **v: translate(lang, key, **v), target=target, shown=shown,
        is_file=target != safe_next(asked),
    )  # fmt: skip
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def register(app: FastAPI) -> None:
    app.add_middleware(PhoneFirst)

    async def web_manifest(_request: Request) -> Response:
        body = json.dumps(manifest(), ensure_ascii=False, separators=(",", ":"))
        return Response(body, media_type="application/manifest+json", headers={"Cache-Control": CACHE})

    async def favicon(_request: Request) -> Response:
        return FileResponse(ICONS / "favicon.ico", media_type="image/x-icon", headers={"Cache-Control": CACHE})

    async def link(request: Request) -> Response:
        return link_page(request)

    # plain routes like the /static mount, not pages: the page walks (role matrix, wording) do not visit them
    app.add_route("/manifest.webmanifest", web_manifest, methods=["GET"], include_in_schema=False)
    app.add_route("/favicon.ico", favicon, methods=["GET"], include_in_schema=False)
    app.add_route("/link", link, methods=["GET"], include_in_schema=False)
