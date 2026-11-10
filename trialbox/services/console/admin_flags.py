"""``/ops/flags``: the feature flags of the box (T-008, D-207, MR-090; ``tb_common.flags``).

Administrators only: anyone else gets 403 (and a ``console.denied`` audit event). The page lists every declared flag
with its value, when, by whom and why it last changed, and the last changes. A change needs a reason, goes through
one confirmation sheet (P-10), and is one ``flag_event`` row and one ``flag.set`` audit event with the actor and the
reason. An undeclared flag name or a value outside the declared ones is refused with 400.

When the console starts (``register``, called from ``create_app``) the flags are seeded: a flag that has no row yet
takes its seed variable (``TB_LAKE_SOURCE``) or its declared default; after that the variable is ignored.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from tb_common.flags import DECLARED, MAX_REASON, Flags, check_value

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
    except Exception as e:
        log.warning("flags not seeded at start (%s: %s)", type(e).__name__, e)
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

    @app.get("/ops/flags", response_class=HTMLResponse)
    def flags_view(request: Request) -> Response:
        sess = admin(request)
        store = Flags()
        return h.page(request, "ops_flags.html", sess, flags=store.all(), events=store.events(limit=50))

    @app.post("/ops/flags")
    def flags_set(
        request: Request,
        csrf: str = Form(""),
        name: str = Form(""),
        value: str = Form(""),
        reason: str = Form(""),
        confirm: str = Form(""),
        old: str = Form(""),
    ) -> Response:
        sess = admin(request, csrf)
        if name not in DECLARED:
            raise h.problem(400, "flags.err.undeclared", flag=name[:60])
        try:
            new = check_value(name, value)
        except ValueError as e:
            raise h.problem(400, "flags.err.value", flag=name, values=", ".join(DECLARED[name].values)) from e
        why = " ".join(reason.split())
        if not why:
            raise h.problem(400, "flags.err.reason")
        if len(why) > MAX_REASON:
            raise h.problem(400, "flags.err.long", n=MAX_REASON)
        store = Flags(audit=h.au)
        try:
            current = store.row(name) or ""
        except Exception as e:  # the store is down: say so, never a 500
            log.warning("flag store unreadable on /ops/flags (%s)", type(e).__name__)
            raise h.problem(400, "flags.err.store") from e
        if confirm != "yes":
            lang = sess.lang if sess.lang in LANGS else "en"
            text = translate(lang, "flags.confirm", flag=name, old=current or translate(lang, "flags.unset"), new=new,
                             reason=why)  # fmt: skip
            fields = {"name": name, "value": new, "reason": why, "old": current}
            assert h.confirm is not None
            return h.confirm(request, sess, text, "/ops/flags", fields, "/ops/flags")
        if old != current:  # someone changed it after this sheet was shown: confirm again on the new value
            raise h.problem(400, "flags.err.stale", flag=name, now=current or "-")
        try:
            store.set(name, new, actor=h.actor(sess), reason=why)
        except ValueError as e:  # the value it already has (the only refusal left after the checks above)
            raise h.problem(400, "flags.err.same", flag=name, value=new) from e
        return RedirectResponse(f"/ops/flags#flag-{name}", status_code=303)
