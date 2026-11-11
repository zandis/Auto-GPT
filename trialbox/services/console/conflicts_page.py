"""``/data/conflicts``: the clinical conflicts of the whole database for the data steward (T-201, D-426).

Two sources that give different values for one patient item (the hospital feed against a PI's sheet or the site's
own input) are a conflict in the OMOP store of record (``tb_conflict``). While it is open the item is unknown, and
unknown never excludes a patient (D-130). This page lists the open conflicts (``?all=1``: the trail, every state),
each with the patient's pseudonym, the item, every source's value and when it was found, and lets the steward keep
one of the values or keep the item unknown, with a reason (``omop.conflicts.resolve``). The matrix's
``conflicts.resolve`` guards both routes: anyone else gets 403 and a ``console.denied`` event. A store that cannot be
reached is a 503 page, never a 500.

This is not the study's "Trial-record differences" page (``/studies/{rs}/conflicts``, ``console.data_pages``), which
compares TrialBox's trial values with REDCap's (FIT-018: the two never share a name).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from tb_common.authz import permit
from tb_common.db import DatabaseError

from console import i18n_conflicts
from console.auth import Session
from console.home import Helpers
from console.i18n import CATALOGUES

log = logging.getLogger("console.conflicts")

for _lang, _cat in (("en", i18n_conflicts.EN), ("ja", i18n_conflicts.JA), ("zh-TW", i18n_conflicts.ZH)):
    CATALOGUES[_lang].update(_cat)

ACTION = "conflicts.resolve"
MAX_REASON = 500


def register(app: FastAPI, h: Helpers) -> None:
    lock = threading.Lock()
    held: dict[str, Any] = {}

    def store() -> Any:
        """The OMOP store (``TB_OMOP_DB_URL``, else ``TB_DB_URL``), opened once; 503 when it cannot be reached."""
        from omop import schema

        with lock:
            if "db" not in held:
                try:
                    held["db"] = schema.connect()
                except (DatabaseError, schema.OmopError) as e:
                    log.warning("OMOP store unreachable on /data/conflicts (%s)", type(e).__name__)
                    raise h.problem(503, "conflicts.err.store") from e
            return held["db"]

    def guard(request: Request) -> Session:
        sess = h.need(request)
        if not permit(sess.user.role, ACTION):
            h.au.append("console.denied", actor=h.actor(sess), detail={"action": request.url.path[:80]})
            raise h.problem(403, "forbidden")
        return sess

    @app.get("/data/conflicts", response_class=HTMLResponse)
    def conflicts_view(
        request: Request, every: str = Query("", alias="all"), done: str = "", err: str = ""
    ) -> Response:
        sess = guard(request)
        from omop import conflicts

        db = store()
        try:
            rows = conflicts.listing(db, everything=bool(every))
            per_item = conflicts.counts(db)
        except DatabaseError as e:
            log.warning("OMOP store failed on /data/conflicts (%s)", type(e).__name__)
            raise h.problem(503, "conflicts.err.store") from e
        return h.page(
            request,
            "conflicts.html",
            sess,
            rows=rows,
            per_item=per_item,
            everything=bool(every),
            done=done == "1",
            err=err if err in ("reason", "choice", "state") else "",
            unknown=conflicts.UNKNOWN,
        )

    @app.post("/data/conflicts/{cid}/resolve")
    def conflicts_resolve(
        request: Request, cid: int, csrf: str = Form(""), choice: str = Form(""), reason: str = Form("")
    ) -> Response:
        sess = guard(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        from omop import conflicts
        from omop.schema import OmopError

        why = reason.strip()[:MAX_REASON]
        if not why:
            return RedirectResponse("/data/conflicts?err=reason", status_code=303)
        db = store()
        c = conflicts.one(db, cid)
        if c is None:
            raise h.problem(404, "notfound")
        if c.state != "open":
            return RedirectResponse("/data/conflicts?err=state", status_code=303)
        if choice != conflicts.UNKNOWN and choice not in c.values:
            return RedirectResponse("/data/conflicts?err=choice", status_code=303)
        try:
            got = conflicts.resolve(db, cid, choice, by=h.actor(sess), reason=why, authority="steward")
        except OmopError:  # settled by someone else in the meantime
            return RedirectResponse("/data/conflicts?err=state", status_code=303)
        h.au.append(
            "console.conflict_resolved",
            actor=h.actor(sess),
            detail={"conflict": cid, "item": got.item, "resolution": got.resolution, "authority": got.authority},
        )
        return RedirectResponse("/data/conflicts?done=1", status_code=303)
