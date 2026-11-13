"""``/ops/flags``: the feature flags of the box (T-008, D-207, MR-090; ``tb_common.flags``).

The administrator's page: anyone else gets 403 (and a ``console.denied`` audit event), except that the data steward
sees and changes the one flag ``screening.after_restore`` there (NEW-FLAG-1, D-706). The page lists every declared flag
with its value, when, by whom and why it last changed, and the last changes. A change needs a reason, goes through
one confirmation sheet (P-10), and is one ``flag_event`` row and one ``flag.set`` audit event with the actor and the
reason. An undeclared flag name or a value outside the declared ones is refused with 400. A flag store that does not
answer (the trial database is down) is a 503 page, on the list and on a change: never a 500, never a 400.

When the console starts (``register``, called from ``create_app``) the flags are seeded: a flag that has no row yet
takes its seed variable (``TB_LAKE_SOURCE``) or its declared default; after that the variable is ignored.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from tb_common.authz import permit
from tb_common.flags import DECLARED, MAX_REASON, Flags, check_value

from console import i18n_flags
from console.home import Helpers
from console.i18n import CATALOGUES, LANGS, translate

log = logging.getLogger("console.flags")
HOLD = "screening.after_restore"  # the hold after a restore (D-522)
T = TypeVar("T")

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

    def admin(request: Request, csrf: str | None = None, name: str | None = None) -> Any:
        """The session of an account that may open the page, and change flag ``name`` when one is given. The
        administrator: every flag. NEW-FLAG-1 (D-706): an account with the matrix row ``restore.release`` (the data
        steward, whom D-455 names for re-applying what a restore lost): the hold after a restore, and no other."""
        sess = h.need(request)
        if csrf is not None and not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        ok = sess.user.is_admin or (only_hold(sess) and name in (None, HOLD))
        if not ok:
            tried = {"flag": name[:60]} if name else {}  # which flag was tried, for whoever reads the refusal
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80], **tried})
            raise h.problem(403, "forbidden")
        return sess

    def only_hold(sess: Any) -> bool:
        return not sess.user.is_admin and permit(sess.user.role, "restore.release").allowed

    def stored(fn: Callable[[], T]) -> T:
        """A read or a change of the flag store; a store that does not answer is a 503 page. A ``ValueError`` (a
        refusal of the store's own rules) is the caller's to turn into a 400."""
        try:
            return fn()
        except ValueError:
            raise
        except Exception as e:
            log.warning("flag store unavailable on /ops/flags (%s: %s)", type(e).__name__, e)
            raise h.problem(503, "flags.err.store") from e

    @app.get("/ops/flags", response_class=HTMLResponse)
    def flags_view(request: Request) -> Response:
        sess = admin(request)
        store = Flags()
        flags, events = stored(lambda: (store.all(), store.events(limit=50)))
        if only_hold(sess):  # the steward's page is this one flag's: its value, and its own changes
            flags = [f for f in flags if f["name"] == HOLD]
            events = stored(lambda: store.events(HOLD, limit=50))
        return h.page(request, "ops_flags.html", sess, flags=flags, events=events)

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
        sess = admin(request, csrf, name)
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
        current = stored(lambda: store.row(name)) or ""  # the store is down: a 503 page, never a 500
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
            stored(lambda: store.set(name, new, actor=h.actor(sess), reason=why))
        except ValueError as e:  # the value it already has (the only refusal left after the checks above)
            raise h.problem(400, "flags.err.same", flag=name, value=new) from e
        return RedirectResponse(f"/ops/flags#flag-{name}", status_code=303)
