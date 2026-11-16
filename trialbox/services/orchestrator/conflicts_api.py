"""NEW-ARCH-3 slice 2 (D-865): the clinical conflicts of the OMOP store of record over the orchestrator's routes.

The console's ``/data/conflicts`` page (T-201, D-426) opened the OMOP store itself to list the open conflicts
(``tb_conflict``) and to settle one (``omop.conflicts.resolve``): a process boundary that was no data boundary (the
deep review's ARCH-005). Now the page asks these routes:

* ``GET /omop/conflicts`` (``?all=1``: the trail, every state): the conflicts with each patient's pseudonym, the
  item and every source's value, and the open count per item. A patient read: the console signs it for the
  matrix's ``conflicts.resolve`` (``tb_common.patient_reads``), the right that has always guarded the page.
* ``POST /omop/conflicts/{cid}/resolve``: the steward's choice (one of the claimed values, or ``unknown``) with a
  reason, by the verified person (``require_actor("conflicts.resolve")``). 404 for no such conflict; 409 for one
  settled already; 400 for a choice nobody claimed or no reason. The console writes ``console.conflict_resolved``.

A store that cannot be reached is a 503."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from tb_common.actor_v3 import Claim
from tb_common.db import DatabaseError

from orchestrator.actor import require_actor

log = logging.getLogger("orchestrator.conflicts")

ACTION = "conflicts.resolve"
AS_STEWARD = require_actor(ACTION)
READ = require_actor(ACTION)
MAX_REASON = 500


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # the person is the verified one, never a field
    choice: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=MAX_REASON)


def _row(c: Any) -> dict[str, Any]:
    return asdict(c)


def router(store: Callable[[], Any]) -> APIRouter:
    """``store()``: the OMOP store of record, open (``omop.schema.connect``); raises when it cannot be reached."""
    r = APIRouter()

    def db() -> Any:
        from omop.schema import OmopError

        try:
            return store()
        except (DatabaseError, OmopError) as exc:
            log.warning("OMOP store unavailable for the conflicts (%s)", type(exc).__name__)
            raise HTTPException(status_code=503, detail={"code": "store", "message": "the store is not here"}) from exc

    @r.get("/omop/conflicts", dependencies=[READ])
    def conflicts_list(every: str = Query("", alias="all")) -> dict[str, Any]:
        from omop import conflicts

        d = db()
        try:
            rows = conflicts.listing(d, everything=bool(every))
            per_item = conflicts.counts(d)
        except DatabaseError as exc:
            log.warning("OMOP store failed on the conflicts (%s)", type(exc).__name__)
            raise HTTPException(status_code=503, detail={"code": "store", "message": "the store failed"}) from exc
        return {"rows": [_row(c) for c in rows], "counts": per_item, "unknown": conflicts.UNKNOWN}

    @r.post("/omop/conflicts/{cid}/resolve")
    def conflicts_resolve(cid: int, body: ResolveBody, who: Claim = AS_STEWARD) -> dict[str, Any]:
        from omop import conflicts
        from omop.schema import OmopError

        why = body.reason.strip()[:MAX_REASON]
        if not why:
            raise HTTPException(status_code=400, detail={"code": "reason", "message": "a reason is needed"})
        d = db()
        c = conflicts.one(d, cid)
        if c is None:
            raise HTTPException(status_code=404, detail={"code": "notfound", "message": "no such conflict"})
        if c.state != "open":
            raise HTTPException(status_code=409, detail={"code": "state", "message": "settled already"})
        if body.choice != conflicts.UNKNOWN and body.choice not in c.values:
            raise HTTPException(status_code=400, detail={"code": "choice", "message": "a value nobody claimed"})
        try:
            got = conflicts.resolve(d, cid, body.choice, by=who.name, reason=why, authority="steward")
        except OmopError as exc:  # settled by someone else in the meantime
            raise HTTPException(status_code=409, detail={"code": "state", "message": "settled already"}) from exc
        return {"conflict": cid, "item": got.item, "resolution": got.resolution, "authority": got.authority}

    return r
