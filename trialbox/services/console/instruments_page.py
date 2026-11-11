"""``/data/instruments``: the instrument copyright register for the data steward (T-307, WS-04.5, D-375).

The administrator (the box's data steward) sees each licensed instrument of ``catalogue/instruments.csv``: who holds
it, whether a licence is needed, what its terms say and where they were read, and its catalogue items with what this
site may keep of each (the catalogue's ``storable``, raised by the site's switch). A switch raises what the site keeps
of one instrument and needs the site's licence reference: with an empty one it is refused (400) and audited
(``instrument.switch_refused``); an accepted one is the site set-up store's setting and an ``instrument.switch``
event with the actor, the level and the reference. Going back to the catalogue's level needs no reference. Anyone
else gets 403 and a ``console.denied`` event. An unreadable register is a 503 page, never a 500.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from tb_common import catalogue, instruments

from console import i18n_instruments
from console.home import Helpers
from console.i18n import CATALOGUES

log = logging.getLogger("console.instruments")

for _lang, _cat in (("en", i18n_instruments.EN), ("ja", i18n_instruments.JA), ("zh-TW", i18n_instruments.ZH)):
    CATALOGUES[_lang].update(_cat)


def _store() -> Any:
    from sitesetup.store import SetupStore  # the site set-up store holds the box's switches (schema ``sitesetup``)

    return SetupStore()


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
            st = _store()
        except Exception as e:  # no trial database here: the catalogue's levels hold, shown as such
            log.warning("site set-up store unavailable on /data/instruments (%s: %s)", type(e).__name__, e)
            return {}
        try:
            return instruments.switches(st.setting(instruments.SETTING))
        finally:
            st.close()

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
        actor = h.actor(sess)
        at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            st = _store()
        except Exception as e:
            log.warning("site set-up store unavailable on a switch (%s: %s)", type(e).__name__, e)
            raise h.problem(503, "instruments.err.store") from e
        try:
            have = instruments.switches(st.setting(instruments.SETTING))
            try:
                new = instruments.switch(have, iid[:40], storable, licence_ref, actor, at)
            except instruments.SwitchRefused as e:
                h.au.append("instrument.switch_refused", actor=actor,
                            detail={"instrument": iid[:40], "storable": storable[:40], "why": e.code})  # fmt: skip
                raise h.problem(400, f"instruments.err.{e.code}", instrument=iid[:40]) from e
            except catalogue.CatalogueError as e:
                raise h.problem(503, "instruments.err.register") from e
            st.set_setting(instruments.SETTING, instruments.dump(new), actor, at)
        finally:
            st.close()
        s = new.get(iid)
        h.au.append("instrument.switch", actor=actor,
                    detail={"instrument": iid, "storable": s.storable if s else "catalogue",
                            "licence_ref": s.licence_ref if s else ""})  # fmt: skip
        return RedirectResponse(f"/data/instruments?done={iid}#ins-{iid}", status_code=303)
