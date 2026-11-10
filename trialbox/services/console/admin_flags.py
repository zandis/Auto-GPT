"""``/ops/flags``: the feature flags of the box (T-008, D-207, MR-090; ``tb_common.flags``).

Administrators only: anyone else gets 403 (and a ``console.denied`` audit event). The page lists every declared flag
with its value, when, by whom and why it last changed, and the last changes. A change needs a reason, goes through
one confirmation sheet (P-10), and is one ``flag_event`` row and one ``flag.set`` audit event with the actor and the
reason. The sheet carries the value it showed: Yes is refused when the flag changed in between. An undeclared flag
name, a value outside the declared ones, no reason or a reason over 500 characters is refused with 400; a flag store
that does not answer is a 503 page.

When the console starts (``register``, called from ``create_app``) the flags are seeded: a flag that has no row yet
takes its seed variable (``TB_LAKE_SOURCE``) or its declared default; after that the variable is ignored.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from tb_common.db import ENV as DB_URL_ENV
from tb_common.db import Database
from tb_common.flags import DECLARED, MAX_REASON, SCHEMA, Flags, check_value

from console import i18n_flags
from console.home import Helpers
from console.i18n import CATALOGUES, LANGS, translate

log = logging.getLogger("console.flags")

for _lang, _cat in (("en", i18n_flags.EN), ("ja", i18n_flags.JA), ("zh-TW", i18n_flags.ZH)):
    CATALOGUES[_lang].update(_cat)


def seed_at_start(h: Helpers) -> list[dict[str, Any]]:
    """The console's start is a first start for a database whose flags were never seeded. Never stops the console:
    a box without a trial database (some tools) or one that cannot reach it logs and carries on."""
    try:
        return Flags(audit=h.au).seed()
    except LookupError:
        return []  # no TB_DB_URL: no flag store here
    except Exception as e:  # loud: until a start seeds the flags, the seed variables still decide (doctor warns)
        log.error("flags NOT seeded at start (%s: %s): the seed variables still decide", type(e).__name__, e)
        return []


def register(app: FastAPI, h: Helpers) -> None:
    seed_at_start(h)

    def admin(request: Request, csrf: str | None = None) -> Any:
        sess = h.need(request)
        if csrf is not None and not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        if not sess.user.is_admin:
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    def stored(fn: Any) -> Any:
        """A read or a change of the flag store; a store that does not answer is a 503 page, not a 500."""
        try:
            return fn()
        except ValueError:
            raise
        except Exception as e:
            log.warning("flag store unavailable (%s: %s)", type(e).__name__, e)
            raise h.problem(503, "unavailable", detail="the trial database (feature flags)") from e

    @app.get("/ops/flags", response_class=HTMLResponse)
    def flags_view(request: Request) -> Response:
        sess = admin(request)

        def read() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            with Database.connect(os.environ.get(DB_URL_ENV), SCHEMA) as db:  # one connection for the page
                store = Flags(db)
                return store.all(), store.events(limit=50)

        flags, events = stored(read)
        return h.page(request, "ops_flags.html", sess, flags=flags, events=events)

    @app.post("/ops/flags")
    def flags_set(
        request: Request,
        csrf: str = Form(""),
        name: str = Form(""),
        value: str = Form(""),
        reason: str = Form(""),
        confirm: str = Form(""),
        old: str | None = Form(None),
    ) -> Response:
        sess = admin(request, csrf)
        if name not in DECLARED:
            raise h.problem(400, "request.refused", reason=f"undeclared flag {name[:60]!r}")
        try:
            new = check_value(name, value)
        except ValueError as e:
            raise h.problem(400, "request.refused", reason=str(e)) from e
        why = " ".join(reason.split())
        if not why:
            raise h.problem(400, "request.refused", reason="a flag change needs a reason")
        if len(why) > MAX_REASON:  # never cut: the audit trail holds the reason the person confirmed
            raise h.problem(400, "request.refused", reason=f"the reason is {len(why)} characters; at most {MAX_REASON}")
        store = Flags(audit=h.au)
        if confirm != "yes":
            lang = sess.lang if sess.lang in LANGS else "en"
            have = stored(lambda: store.row(name))
            text = translate(lang, "flags.confirm", flag=name, old=have or translate(lang, "flags.unset"), new=new,
                             reason=why)  # fmt: skip
            # the value shown on the sheet travels with it: Yes is refused when the flag changed in between
            fields = {"name": name, "value": new, "reason": why, "old": have or ""}
            assert h.confirm is not None
            return h.confirm(request, sess, text, "/ops/flags", fields, "/ops/flags")
        # ``old`` comes from the confirmation sheet ("" = it showed "not set"); a direct POST carries none
        expect: dict[str, Any] = {} if old is None else {"expect_old": old or None}
        try:
            stored(lambda: store.set(name, new, actor=h.actor(sess), reason=why, **expect))
        except ValueError as e:
            raise h.problem(400, "request.refused", reason=str(e)) from e
        return RedirectResponse(f"/ops/flags#flag-{name}", status_code=303)
