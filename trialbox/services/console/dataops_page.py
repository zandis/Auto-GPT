"""``/data-ops``: the data-operations console (T-112b, D-443; the second half of TB-ASSESS-01 T-112).

Every ingest night is one ``dataops.batch`` row (T-112a, D-427). This page shows the newest night of each source as
a light (a held or failed night is red), the held nights with the steward's accept and reject, and the ingest
history newest first, filtered by state and source and cut by the store (``DataOps.history``: never a whole table
read and filtered here). ``/data-ops/batches/{id}`` shows one night's trail (every step, who, when, why, and the
audit event that recorded it). The clinical conflicts are the next page (``/data/conflicts``, T-201); the two link
to each other.

**Who.** ``dataops.view`` (the steward and the administrator: the rows hold tables and counts, never a patient) reads;
``dataops.decide`` (the steward only) accepts or rejects a held night, with a reason. Anyone else gets 403 and a
``console.denied`` event.

**Accept.** ``DataOps.decide`` runs the promotion of the night inside its transaction, so a night is ``PUBLISHED``
only when its snapshot became the one served. The lake side of that promotion is not built yet (D-443, Open):
``register`` takes a ``promote`` callable, and without one an accept is refused with a message and the night stays
held. Reject needs no promotion (``CURRENT`` keeps the previous snapshot, D-149) and works now.

**API.** ``/api/v1/data/sources``, ``/api/v1/data/batches`` (``state``, ``source``, ``limit``, ``before``),
``/api/v1/data/batches/{id}`` and ``POST /api/v1/data/batches/{id}/decide`` answer the same functions with the
same checks. The session and the right are checked before the body is read: an unauthenticated empty body is 401,
never 422.

A store that cannot be reached is a 503, never a 500.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from tb_common.authz import permit
from tb_common.config import site_tz
from tb_common.db import DatabaseError

from console import i18n_dataops
from console.auth import Session
from console.home import Helpers
from console.i18n import CATALOGUES

log = logging.getLogger("console.dataops")

for _lang, _cat in (("en", i18n_dataops.EN), ("ja", i18n_dataops.JA), ("zh-TW", i18n_dataops.ZH)):
    CATALOGUES[_lang].update(_cat)

VIEW = "dataops.view"
DECIDE = "dataops.decide"
MAX_REASON = 500
PAGE = 50
# the light of a source from its newest night: held or stopped is red, a steward's reject (the box serves the night
# before) and a night still on the line are amber, a published night is green
LIGHT = {"PUBLISHED": "green", "HELD": "red", "FAILED": "red", "REJECTED": "amber"}
ERRORS = ("reason", "decision", "state", "promote")

Promote = Callable[[Any], None]


class PromoteFailed(RuntimeError):
    """The promotion of an accepted night raised: ``DataOps.decide`` rolled back, the night stays held."""


def light(state: str) -> str:
    return LIGHT.get(state, "amber")


def register(app: FastAPI, h: Helpers, promote: Promote | None = None) -> None:
    lock = threading.Lock()
    held: dict[str, Any] = {}

    def store() -> Any:
        """The ``dataops`` schema of the trial database (``TB_DB_URL``), opened once; 503 when it cannot be reached."""
        from datacore.dataops import DataOps

        with lock:
            if "ops" not in held:
                try:
                    held["ops"] = DataOps()
                except DatabaseError as e:
                    log.warning("dataops store unreachable (%s)", type(e).__name__)
                    raise h.problem(503, "dataops.err.store") from e
            return held["ops"]

    def read(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except DatabaseError as e:
            log.warning("dataops store failed (%s)", type(e).__name__)
            raise h.problem(503, "dataops.err.store") from e

    def deny(request: Request, sess: Session) -> Exception:
        h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
        return h.problem(403, "forbidden")

    def guard(request: Request, action: str, sess: Session | None = None) -> Session:
        sess = sess or h.need(request)
        if not permit(sess.user.role, action):
            raise deny(request, sess)
        return sess

    def api_guard(request: Request, action: str) -> Session:
        assert h.api_session is not None, "console.home.register runs first"
        return guard(request, action, h.api_session(request))

    def now() -> str:
        return datetime.now(ZoneInfo(site_tz())).isoformat(timespec="seconds")

    def history(state: str, source: str, limit: int, before: int | None) -> tuple[list[Any], int | None]:
        from datacore.dataops import STATES

        ops = store()
        st = state if state in STATES else None
        rows = read(lambda: ops.history(st, source.strip()[:80] or None, limit=limit + 1, before=before))
        more = len(rows) > limit
        rows = rows[:limit]
        return rows, (rows[-1].id if more and rows else None)

    def decide(sess: Session, bid: int, decision: str, reason: str) -> Any:
        """The steward's accept or reject (``DataOps.decide``). Raises ``DataOpsError`` with ``why``: ``decision``,
        ``reason``, ``not_found``, ``not_held``, ``step`` or ``promote``."""
        from datacore.dataops import DataOpsError

        why = reason.strip()[:MAX_REASON]
        if decision == "accept" and promote is None:
            raise DataOpsError("promote", "accepting a held night needs the lake's promotion, not built yet (D-443)")

        def run(b: Any) -> None:
            assert promote is not None
            try:
                promote(b)
            except Exception as e:
                log.warning("promotion of batch %s failed (%s)", bid, type(e).__name__)
                raise PromoteFailed(type(e).__name__) from e

        ops = store()
        hook = run if promote is not None else None
        return read(lambda: ops.decide(h.au, bid, decision, by=h.actor(sess), at=now(), reason=why, promote=hook))

    # ------------------------------------------------------------------ pages
    @app.get("/data-ops", response_class=HTMLResponse)
    def dataops_view(
        request: Request,
        state: str = "",
        source: str = "",
        before: int | None = Query(None, ge=1),
        done: str = "",
        err: str = "",
    ) -> Response:
        sess = guard(request, VIEW)
        ops = store()
        sources = read(ops.sources)
        waiting = read(ops.held)
        rows, nxt = history(state, source, PAGE, before)
        return h.page(
            request,
            "dataops.html",
            sess,
            sources=[{**b.as_dict(), "light": light(b.state)} for b in sources],
            waiting=waiting,
            rows=rows,
            counts=read(ops.counts),
            state=state,
            source=source,
            next_before=nxt,
            may_decide=permit(sess.user.role, DECIDE),
            can_accept=promote is not None,
            done=done if done in ("accept", "reject") else "",
            err=err if err in ERRORS else "",
        )

    @app.get("/data-ops/batches/{bid}", response_class=HTMLResponse)
    def dataops_batch(request: Request, bid: int) -> Response:
        sess = guard(request, VIEW)
        ops = store()
        b = read(lambda: ops.batch(bid))
        if b is None:
            raise h.problem(404, "notfound")
        return h.page(
            request,
            "dataops_batch.html",
            sess,
            b=b,
            steps=read(lambda: ops.steps(bid)),
            may_decide=permit(sess.user.role, DECIDE),
            can_accept=promote is not None,
        )

    @app.post("/data-ops/batches/{bid}/decide")
    def dataops_decide(
        request: Request, bid: int, csrf: str = Form(""), decision: str = Form(""), reason: str = Form("")
    ) -> Response:
        sess = guard(request, DECIDE)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        from datacore.dataops import DataOpsError

        try:
            decide(sess, bid, decision, reason)
        except DataOpsError as e:
            if e.why == "not_found":
                raise h.problem(404, "notfound") from e
            code = {"not_held": "state", "step": "state", "by": "reason"}.get(e.why, e.why)
            return RedirectResponse(f"/data-ops?err={code if code in ERRORS else 'state'}", status_code=303)
        except PromoteFailed:  # the night stays held (DataOps.decide's transaction)
            return RedirectResponse("/data-ops?err=promote", status_code=303)
        return RedirectResponse(f"/data-ops?done={decision}", status_code=303)

    # ------------------------------------------------------------------ /api/v1 (the same functions)
    @app.get("/api/v1/data/sources")
    def api_sources(request: Request) -> dict[str, Any]:
        api_guard(request, VIEW)
        ops = store()
        rows = read(ops.sources)
        return {"sources": [{**b.as_dict(), "light": light(b.state)} for b in rows], "counts": read(ops.counts)}

    @app.get("/api/v1/data/batches")
    def api_batches(
        request: Request,
        state: str = "",
        source: str = "",
        limit: int = Query(PAGE, ge=1, le=200),
        before: int | None = Query(None, ge=1),
    ) -> dict[str, Any]:
        api_guard(request, VIEW)
        rows, nxt = history(state, source, limit, before)
        return {"batches": [b.as_dict() for b in rows], "next_before": nxt}

    @app.get("/api/v1/data/batches/{bid}")
    def api_batch(request: Request, bid: int) -> dict[str, Any]:
        api_guard(request, VIEW)
        ops = store()
        b = read(lambda: ops.batch(bid))
        if b is None:
            raise h.problem(404, "notfound")
        return {"batch": b.as_dict(), "steps": read(lambda: ops.steps(bid))}

    @app.post("/api/v1/data/batches/{bid}/decide")
    async def api_decide(request: Request, bid: int) -> dict[str, Any]:
        sess = api_guard(request, DECIDE)  # the session and the right first; the body only then
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise h.problem(400, "request.refused", code="DATAOPS-BODY", reason="a JSON object", fields="")
        from datacore.dataops import DataOpsError

        decision, reason = str(body.get("decision") or ""), str(body.get("reason") or "")
        try:
            b = decide(sess, bid, decision, reason)
        except DataOpsError as e:
            if e.why == "not_found":
                raise h.problem(404, "notfound") from e
            status = 409 if e.why in ("not_held", "step", "promote") else 400
            raise h.problem(status, "request.refused", code=f"DATAOPS-{e.why.upper()}", reason=e.message,
                            fields="") from e  # fmt: skip
        except PromoteFailed as e:  # the night stays held
            raise h.problem(409, "request.refused", code="DATAOPS-PROMOTE", reason="the promotion failed; the "
                            "night stays held", fields="") from e  # fmt: skip
        return {"batch": b.as_dict()}
