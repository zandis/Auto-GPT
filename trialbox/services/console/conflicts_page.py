"""``/data/conflicts``: the clinical conflicts of the whole database for the data steward (T-201, D-426).

Two sources that give different values for one patient item (the hospital feed against a PI's sheet or the site's
own input) are a conflict in the OMOP store of record (``tb_conflict``). While it is open the item is unknown, and
unknown never excludes a patient (D-130). This page lists the open conflicts (``?all=1``: the trail, every state),
each with the patient's pseudonym, the item, every source's value and when it was found, and lets the steward keep
one of the values or keep the item unknown, with a reason. The matrix's ``conflicts.resolve`` guards both routes:
anyone else gets 403 and a ``console.denied`` event. A store that cannot be reached is a 503 page, never a 500.
NEW-ARCH-3 slice 2 (D-865): the store is the orchestrator's; the page reads ``GET /omop/conflicts`` (a patient read,
signed for ``conflicts.resolve``) and a choice is one signed ``POST /omop/conflicts/{cid}/resolve``.

This is not the study's "Trial-record differences" page (``/studies/{rs}/conflicts``, ``console.data_pages``), which
compares TrialBox's trial values with REDCap's (FIT-018: the two never share a name).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from tb_common.authz import permit

from console import actor, i18n_conflicts, s28
from console.auth import Session
from console.backend import Problem, Unavailable
from console.home import Helpers
from console.i18n import CATALOGUES

log = logging.getLogger("console.conflicts")

for _lang, _cat in (("en", i18n_conflicts.EN), ("ja", i18n_conflicts.JA), ("zh-TW", i18n_conflicts.ZH)):
    CATALOGUES[_lang].update(_cat)

ACTION = "conflicts.resolve"
MAX_REASON = 500


UNKNOWN = "unknown"  # the choice that keeps the item unknown (the orchestrator's answer names it too)


@dataclass(frozen=True)
class ConflictView:
    """One conflict as the orchestrator's ``GET /omop/conflicts`` gives it (the page's rows)."""

    conflict_id: int
    pid: str
    kind: str
    item: str
    claims: list[dict[str, Any]]
    state: str
    detected_at: datetime | None
    detected_batch: str
    resolved_value: str | None
    resolution: str | None
    reason: str | None
    authority: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    closed_batch: str | None

    @property
    def values(self) -> list[str]:
        """The distinct claimed values, in the order the sources gave them (the hospital's first)."""
        return list(dict.fromkeys(str(c.get("value")) for c in self.claims if c.get("value") is not None))

    @staticmethod
    def of(row: dict[str, Any]) -> ConflictView:
        names = {f.name for f in fields(ConflictView)}
        got = {k: v for k, v in row.items() if k in names}
        for k in ("detected_at", "resolved_at"):
            got[k] = datetime.fromisoformat(got[k]) if isinstance(got.get(k), str) and got[k] else None
        return ConflictView(**got)


def register(app: FastAPI, h: Helpers) -> None:
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
        try:
            got = s28.call(h.bk, "GET", "/omop/conflicts" + ("?all=1" if every else ""))  # signed: a patient read
        except (Problem, Unavailable) as e:
            log.warning("conflicts unavailable on /data/conflicts (%s)", type(e).__name__)
            raise h.problem(503, "conflicts.err.store") from e
        rows = [ConflictView.of(r) for r in got.get("rows") or []]
        per_item = {str(k): int(v) for k, v in (got.get("counts") or {}).items()}
        return h.page(
            request,
            "conflicts.html",
            sess,
            rows=rows,
            per_item=per_item,
            everything=bool(every),
            done=done == "1",
            err=err if err in ("reason", "choice", "state") else "",
            unknown=UNKNOWN,
        )

    @app.post("/data/conflicts/{cid}/resolve")
    def conflicts_resolve(
        request: Request, cid: int, csrf: str = Form(""), choice: str = Form(""), reason: str = Form("")
    ) -> Response:
        sess = guard(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        why = reason.strip()[:MAX_REASON]
        if not why:
            return RedirectResponse("/data/conflicts?err=reason", status_code=303)
        if not choice:
            return RedirectResponse("/data/conflicts?err=choice", status_code=303)
        try:
            got = actor.call(h, sess, ACTION, None, "POST", f"/omop/conflicts/{int(cid)}/resolve",
                             {"choice": choice[:500], "reason": why})  # fmt: skip
        except Problem as e:
            if e.status == 404:
                raise h.problem(404, "notfound") from e
            if e.code in ("state", "choice", "reason"):
                return RedirectResponse(f"/data/conflicts?err={e.code}", status_code=303)
            log.warning("conflict not settled: the orchestrator answered %s %s", e.status, e.code)
            raise h.problem(503, "conflicts.err.store") from e
        except Unavailable as e:
            raise h.problem(503, "conflicts.err.store") from e
        h.au.append(
            "console.conflict_resolved",
            actor=h.actor(sess),
            detail={
                "conflict": cid,
                "item": got.get("item"),
                "resolution": got.get("resolution"),
                "authority": got.get("authority"),
            },
        )
        return RedirectResponse("/data/conflicts?done=1", status_code=303)
