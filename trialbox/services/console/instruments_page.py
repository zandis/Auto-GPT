"""``/data/instruments``: the instrument copyright register for the data steward (T-307, WS-04.5, D-375).

The administrator (the box's data steward) sees each licensed instrument of ``catalogue/instruments.csv``: who holds
it, whether a licence is needed, what its terms say and where they were read, and its catalogue items with what this
site may keep of each (the catalogue's ``storable``, raised by the site's switch). A switch raises what the site keeps
of one instrument and needs the site's licence reference: with an empty one it is refused (400) and audited
(``instrument.switch_refused``); an accepted one is the site set-up store's setting and an ``instrument.switch``
event with the actor, the level and the reference. NEW-ARCH-3 slice 3 (D-864): the store is the orchestrator's;
the page reads it over ``GET /setup/instruments`` and a switch is one signed ``PUT /setup/instruments/{iid}``
(``site.setup``, and the orchestrator asks for the administrator as this page does). Going back to the
catalogue's level needs no reference. Anyone else gets 403 and a ``console.denied`` event. An unreadable
register is a 503 page, never a 500.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from tb_common import catalogue, instruments

from console import actor, i18n_instruments, s28
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.i18n import CATALOGUES

log = logging.getLogger("console.instruments")

for _lang, _cat in (("en", i18n_instruments.EN), ("ja", i18n_instruments.JA), ("zh-TW", i18n_instruments.ZH)):
    CATALOGUES[_lang].update(_cat)


def register(app: FastAPI, h: Helpers) -> None:
    def admin(request: Request, csrf: str | None = None) -> Any:
        sess = h.need(request)
        if csrf is not None and not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.is_admin:
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    def current() -> dict[str, instruments.Switch]:
        try:
            got = s28.call(h.bk, "GET", "/setup/instruments")
        except Exception as e:  # the orchestrator did not answer: the catalogue's levels hold, shown as such
            log.warning("instrument switches unavailable on /data/instruments (%s: %s)", type(e).__name__, e)
            return {}
        return instruments.switches(str(got.get("setting") or "") if isinstance(got, dict) else "")

    @app.get("/data/instruments", response_class=HTMLResponse)
    def instruments_view(request: Request, done: str = "") -> Response:
        sess = admin(request)
        try:
            rows = instruments.rows(current())
        except (OSError, KeyError, catalogue.CatalogueError) as e:
            log.warning("register unreadable on /data/instruments (%s: %s)", type(e).__name__, e)
            raise h.problem(503, "instruments.err.register") from e
        return h.page(request, "instruments.html", sess, rows=rows, levels=catalogue.STORABLE, done=done[:40])

    @app.post("/data/instruments/{iid}")
    def instruments_switch(
        request: Request,
        iid: str,
        csrf: str = Form(""),
        storable: str = Form(""),
        licence_ref: str = Form(""),
    ) -> Response:
        sess = admin(request, csrf)
        who = h.actor(sess)
        path = f"/setup/instruments/{quote(iid[:40], safe='')}"
        try:
            got = actor.call(h, sess, "site.setup", None, "PUT", path,
                             {"storable": storable[:40], "licence_ref": licence_ref[:200]})  # fmt: skip
        except Problem as e:
            if e.status == 400:
                h.au.append("instrument.switch_refused", actor=who,
                            detail={"instrument": iid[:40], "storable": storable[:40], "why": e.code})  # fmt: skip
                raise h.problem(400, f"instruments.err.{e.code}", instrument=iid[:40]) from e
            if e.code == "register":
                raise h.problem(503, "instruments.err.register") from e
            log.warning("instrument switch refused by the orchestrator (%s %s)", e.status, e.code)
            raise h.problem(503, "instruments.err.store") from e
        except Unavailable as e:
            log.warning("instrument switch: the orchestrator did not answer (%s)", e)
            raise h.problem(503, "instruments.err.store") from e
        h.au.append("instrument.switch", actor=who,
                    detail={"instrument": iid, "storable": str(got.get("storable") or "catalogue"),
                            "licence_ref": str(got.get("licence_ref") or "")})  # fmt: skip
        return RedirectResponse(f"/data/instruments?done={iid}#ins-{iid}", status_code=303)
