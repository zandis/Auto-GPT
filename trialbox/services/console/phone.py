"""J-3 (D-1222; the journey review's E-1, E-M1, E-M2, E-4, E-M4, E-M5): the console on a phone.

* **The flag** ``layout.phone_first`` (``tb_common.flags``, audited, off by default) changes what a phone shows
  first. A small middleware puts its value in ``request.state.phone_first`` for each page; ``base.html`` then gives
  ``<body>`` the class ``phone-first``, and the stylesheet's phone-first rules are scoped under it; the week page, the
  patient sheet, the participant's page and the menu's "More" read the same value where the order of the page
  changes. Off, every page is as before. It is switched on ``/ops/flags`` by the administrator, with a reason. A page
  never waits for the flag store: it gets the value last read (off before the first read, and off after a failed
  one), and when that value is older than 5 seconds one background thread reads it again; a store that hangs or
  refuses delays no page. Not read for ``/static``, ``/api/``, ``/healthz``, ``/metrics``, the manifest, the icons
  or ``/link``.
* **A link from another site** (a mail, a chat), with or without the flag. The session cookie is ``SameSite=Strict``
  and stays so: a navigation from another site arrives without it. Such a navigation (``Sec-Fetch-Site:
  cross-site``, ``Sec-Fetch-Mode: navigate``, a GET) to a console page is answered with the console's own page
  ``/link``. Continue there is a tap on this site, so the cookie goes with it. It opens only one of the pages of
  :data:`ALLOWED` (the pages the box's own mails link to, the home page, the week page, a participant's page, the SAE
  register, the account and Help), with only the query parameters that page names, each value checked; the address is
  rebuilt from the page's pattern, never echoed. Anything else, including a disguised or encoded address, opens the
  home page. The page names the page from the catalogue, never by the address it was given. The sign-in and its
  steps, ``/api/``, ``/static``, the manifest and the icons arrive as before.
* **Add to home screen.** ``/manifest.webmanifest`` (name, colours, start page, two icons) and ``/favicon.ico``, served
  by the box itself from ``static/icons``; no offline mode and no service worker. Both are public, like ``/static``:
  the browser fetches a manifest without the session cookie. They are plain routes, not pages: no session, no audit.

Not here: the form guard and the kept long forms (``static/console.js``, ``data_entry.html``)."""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode

import jinja2
from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from tb_common.flags import Flags

from console import i18n_phone
from console.i18n import CATALOGUES, pick_language, translate
from console.studies import WORKLISTS

FLAG = "layout.phone_first"
HERE = Path(__file__).resolve().parent
ICONS = HERE / "static" / "icons"
THEME = "#253a5e"  # the banner's colour (console.css --banner)
BACKGROUND = "#f6f7f9"  # the page's colour (console.css --bg)
#: the browser may keep these a day; a new icon ships with a new box version anyway
CACHE = "public, max-age=86400"
#: how old the value a page gets may be before one background read refreshes it (as tb_common.flags.CACHE_SECONDS)
FLAG_SECONDS = 5.0
#: paths that are not pages: the flag is not read for them, and a link from another site to them is not answered
NOT_PAGES = ("/static/", "/api/", "/healthz", "/metrics", "/manifest.webmanifest", "/favicon.ico", "/link")
#: paths a link from another site reaches as before: the sign-in and its steps, the one-time sign-in link (its code
#: rides after "#"), the identity provider's return
ARRIVALS = ("/login", "/logout", "/enrol", "/auth/")

for _lang, _cat in (("en", i18n_phone.EN), ("ja", i18n_phone.JA), ("zh-TW", i18n_phone.ZH)):
    CATALOGUES[_lang].update(_cat)


# ------------------------------------------------------------------------------------------------- the flag's read
_clock = time.monotonic
_kept: tuple[bool, float] | None = None
_guard = threading.Lock()  # guards _kept and _reading only, never held during a read
_reading = False


def _read() -> bool:
    """One read of the flag store; raises when it does not answer."""
    return Flags().row(FLAG) == "on"


def clear_cache() -> None:
    global _kept
    with _guard:
        _kept = None


def _refresh() -> None:
    global _kept, _reading
    try:
        value = bool(_read())
    except Exception:  # the store is down, not installed, no URL: off until the next read
        value = False
    with _guard:
        _kept = (value, _clock())
        _reading = False


def flag_now() -> bool:
    """The value last read, at once (off before the first read); a value older than 5 s starts one background read."""
    global _reading
    with _guard:
        kept = _kept
        stale = kept is None or _clock() - kept[1] >= FLAG_SECONDS
        start = stale and not _reading
        if start:
            _reading = True
    if start:
        threading.Thread(target=_refresh, name="phone-first-flag", daemon=True).start()
    return kept[0] if kept is not None else False


def flag_on() -> bool:
    """The flag read now, waiting for the store (a command line, a test); never raises."""
    global _reading
    with _guard:
        _reading = True
    _refresh()
    return flag_now()


# ------------------------------------------------------------------------------------------------- /link
_RS = r"(?P<rs>[A-Z0-9][A-Z0-9_-]{0,15})"  # console.app._RULESET_ID
_RECORD = r"(?P<record>[A-Za-z0-9][A-Za-z0-9_-]{0,63})"


@dataclass(frozen=True)
class Allowed:
    """A page Continue may open: its path pattern, its name in the catalogue, the query parameters it keeps (name ->
    pattern of the value)."""

    name: str
    path: str
    keeps: tuple[tuple[str, str], ...] = ()


#: the pages a link from another site may open after the tap on /link: those the box's own mails link to
#: (``console.notify``: a study's week list, its participants, the home page, the mail settings) and the person's
#: everyday pages; nothing that answers a file or acts
ALLOWED: tuple[Allowed, ...] = (
    Allowed("link.page.home", r"/"),
    Allowed("link.page.home", r"/home"),
    Allowed("link.page.week_pick", r"/week"),
    Allowed("link.page.week", rf"/studies/{_RS}/week", (("list", "|".join(WORKLISTS)), ("pid", r"[0-9a-f]{32}"))),
    Allowed("link.page.subjects", rf"/studies/{_RS}/subjects"),
    Allowed("link.page.subject", rf"/studies/{_RS}/subjects/{_RECORD}"),
    Allowed("link.page.sae", r"/sae"),
    Allowed("link.page.notices", r"/settings/notices"),
    Allowed("link.page.account", r"/account"),
    Allowed("link.page.help", r"/help"),
)
_HOME: tuple[str, Allowed, dict[str, str]] = ("/home", ALLOWED[1], {})


def _clean(text: str) -> bool:
    """No control, format or separator character, no space, no DEL, no backslash, no percent sign, no "//"."""
    if "//" in text or "\\" in text or "%" in text:
        return False
    return all(ord(c) > 0x20 and ord(c) != 0x7F and unicodedata.category(c) not in ("Cc", "Cf", "Zl", "Zp", "Zs")
               for c in text)  # fmt: skip


def match(raw: str) -> tuple[str, Allowed, dict[str, str]]:
    """``(address, page, its values)`` Continue opens for ``raw``: one of :data:`ALLOWED`, rebuilt from its pattern;
    the home page for anything else."""
    text = unquote(raw or "")  # once: an address that needs a second decoding is not one of these
    if not text.startswith("/") or not _clean(text):
        return _HOME
    path, _, query = text.partition("?")
    for page in ALLOWED:
        m = re.fullmatch(page.path, path)
        if m is None:
            continue
        values = {k: v for k, v in m.groupdict().items() if v is not None}
        kept = []
        for name, pattern in page.keeps:
            got = [v for k, v in parse_qsl(query, keep_blank_values=False) if k == name]
            if got and re.fullmatch(pattern, got[0]):
                kept.append((name, got[0]))
        address = "/".join(quote(seg, safe="") for seg in path.split("/"))
        return address + (f"?{urlencode(kept)}" if kept else ""), page, values
    return _HOME


def continue_to(raw: str) -> str:
    return match(raw)[0]


def page_path(path: str) -> bool:
    return not any(path == p.rstrip("/") or path.startswith(p) for p in NOT_PAGES)


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
    """For each page request: a link from another site goes to ``/link``; else the flag into the request's state.
    Installed inside the console's headers middleware, so its answers carry the security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            if cross_site_page(scope):
                raw = scope.get("raw_path") or str(scope.get("path", "")).encode("utf-8")
                query = scope.get("query_string", b"")
                asked = raw.decode("latin-1") + (f"?{query.decode('latin-1')}" if query else "")
                resp = RedirectResponse("/link?to=" + quote(asked, safe=""), status_code=303)
                resp.headers["Cache-Control"] = "no-store"
                await resp(scope, receive, send)
                return
            if page_path(str(scope.get("path", ""))):
                scope.setdefault("state", {})["phone_first"] = flag_now()
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
    """``/link``: the console's own page for a link that came from another site (no session is read here). It names
    the page from the catalogue; a link to anything else gets a fixed sentence and the home page."""
    lang = pick_language(request.headers.get("accept-language"))
    asked = request.query_params.get("to", "")
    target, page, values = match(asked)
    known = (target, page, values) != _HOME or re.fullmatch(r"/(home)?", unquote(asked or "")) is not None
    html = _pages.get_template("link_continue.html").render(
        lang=lang, t=lambda key, **v: translate(lang, key, **v), target=target, known=known,
        page_name=translate(lang, page.name, **values),
    )  # fmt: skip
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def register(app: FastAPI) -> None:
    # appended, not inserted at the front as add_middleware does: inside the console's headers middleware, so the
    # 303 to /link and the /link page carry CSP, X-Frame-Options and Referrer-Policy (as demo_guard does)
    app.user_middleware.append(Middleware(PhoneFirst))

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
