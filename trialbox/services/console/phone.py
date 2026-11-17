"""J-3 (D-1222; the journey review's E-1, E-4, E-M1, E-M4, E-M5): the console on a phone.

* **The flag.** ``layout.phone_first`` (``tb_common.flags``, audited, off by default) is read once per request by a
  small middleware and kept in ``request.state.phone_first``. ``base.html`` then gives ``<body>`` the class
  ``phone-first``, and the stylesheet's phone-first rules are scoped under it; the week page, the patient sheet and the
  menu's "More" read the same value for the few places where the order of the page changes. With the flag off every
  page is as before. It is switched on ``/ops/flags`` by the administrator, with a reason.
* **Add to home screen.** ``/manifest.webmanifest`` (name, colours, start page, two icons) and ``/favicon.ico``, served
  by the box itself from ``static/icons``; no offline mode and no service worker. Both are public, like ``/static``:
  the browser fetches a manifest without the session cookie. They are plain routes, not pages: no session, no audit.

Not here: the form guard for long forms (``static/console.js``, ``data_entry.html``) and the sign-in page's same-site
hop for mail links (``console.app``'s ``/login``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from tb_common.flags import Flags

from console import i18n_phone
from console.i18n import CATALOGUES

FLAG = "layout.phone_first"
ICONS = Path(__file__).resolve().parent / "static" / "icons"
THEME = "#253a5e"  # the banner's colour (console.css --banner)
BACKGROUND = "#f6f7f9"  # the page's colour (console.css --bg)
#: the browser may keep these a day; a new icon ships with a new box version anyway
CACHE = "public, max-age=86400"

for _lang, _cat in (("en", i18n_phone.EN), ("ja", i18n_phone.JA), ("zh-TW", i18n_phone.ZH)):
    CATALOGUES[_lang].update(_cat)


def flag_on() -> bool:
    """The flag says ``on``. Off when it is unset, unreadable or there is no flag store (never raises)."""
    return Flags().get(FLAG, "off") == "on"


class PhoneFirst:
    """Reads the flag once per request (not for ``/static``) into ``request.state.phone_first``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not str(scope.get("path", "")).startswith("/static/"):
            scope.setdefault("state", {})["phone_first"] = flag_on()
        await self.app(scope, receive, send)


def manifest() -> dict[str, Any]:
    """The web manifest: the console as an app on a phone's home screen, opening the start page in its own window."""
    icon = "/static/icons/icon-{0}.png"
    return {
        "id": "/",
        "name": "TrialBox",
        "short_name": "TrialBox",
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


def register(app: FastAPI) -> None:
    app.add_middleware(PhoneFirst)

    async def web_manifest(_request: Request) -> Response:
        body = json.dumps(manifest(), ensure_ascii=False, separators=(",", ":"))
        return Response(body, media_type="application/manifest+json", headers={"Cache-Control": CACHE})

    async def favicon(_request: Request) -> Response:
        return FileResponse(ICONS / "favicon.ico", media_type="image/x-icon", headers={"Cache-Control": CACHE})

    # plain routes like the /static mount, not pages: the page walks (role matrix, wording) do not visit them
    app.add_route("/manifest.webmanifest", web_manifest, methods=["GET"], include_in_schema=False)
    app.add_route("/favicon.ico", favicon, methods=["GET"], include_in_schema=False)
