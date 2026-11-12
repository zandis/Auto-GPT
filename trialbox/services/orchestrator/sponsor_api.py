"""Orchestrator API of the sponsor's own words (T-302d, D-435), on the data core (``datacore.sponsor``).

* ``GET/PUT /studies/{rs}/sponsor/layout``: the study's sponsor layout (the screening log's columns in the
  sponsor's words, and how to read the sponsor's weekly sheet); every save is a new row, the newest in force.
* ``POST /studies/{rs}/sponsor/weekly``: the sponsor's weekly subject-status sheet (base64) read into one proposal
  per subject (``same``, ``step``, ``held``, ``unknown``); nothing is written.
* ``POST /studies/{rs}/sponsor/weekly/confirm``: the same sheet and the records a person confirmed: each one's
  ``step`` proposal becomes a lifecycle step (source ``sponsor_weekly``, the sheet's sha256 in its note), mirrored
  to the screening log and audited ``life.step``; a record without a ``step`` proposal is refused.

The person of every changing call is the verified one of a v3 assertion for ``study.setup`` on this study
(T-715, D-483; ``orchestrator.actor.require_actor``): no body names a person. Nothing here writes to the sponsor's
EDC.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from typing import Any

from datacore import sponsor as sp
from datacore.lifecycle import Lifecycle, LifeError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from tb_common.actor_v3 import Claim

from orchestrator.lifecycle_api import AS_ENTER, ApiHost, _rec, _refused, _rs, _today, mirror


class LayoutBody(BaseModel):
    layout: dict[str, Any]


class WeeklyBody(BaseModel):
    data: str = Field(min_length=1, max_length=3_000_000)  # base64; TB_SPONSOR_WEEKLY_MAX_BYTES bounds the bytes
    name: str = Field(default="", max_length=120)
    today: str = ""


class ConfirmBody(WeeklyBody):
    records: list[str] = Field(min_length=1, max_length=2000)


def _bad(exc: sp.SponsorError, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message, "where": exc.where})


def router(get: Callable[[], ApiHost]) -> APIRouter:
    r = APIRouter()

    def sheet(svc: ApiHost, rid: str, body: WeeklyBody, by: str) -> tuple[str, list[sp.WeeklyRow]]:
        try:
            data = base64.b64decode(body.data, validate=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "sponsor.base64", "message": "base64"}) from exc
        cur = sp.Layouts(svc.dc).get(rid)
        try:
            if cur is None:
                raise sp.SponsorError("sponsor.no_layout", "save the sponsor layout first")
            return sp.read_weekly(data, cur["layout"])
        except sp.SponsorError as exc:
            svc.audit.append("sponsor.weekly", ruleset=rid, actor=by,
                             detail={"file": hashlib.sha256(data).hexdigest()[:16],
                                     "refused": exc.code})  # fmt: skip
            raise _bad(exc) from exc

    @r.get("/studies/{rs}/sponsor/layout")
    def get_layout(rs: str) -> dict[str, Any]:
        rid = _rs(rs)
        layouts = sp.Layouts(get().dc)
        return {"study": rid, "current": layouts.get(rid), "history": layouts.history(rid),
                "columns": list(sp.LOG_COLUMNS), "date_formats": list(sp.DATE_FORMATS)}  # fmt: skip

    @r.put("/studies/{rs}/sponsor/layout")
    def put_layout(rs: str, body: LayoutBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        try:
            cur = sp.Layouts(svc.dc).put(rid, body.layout, who.name, svc.stamp())
        except sp.SponsorError as exc:
            svc.audit.append("sponsor.layout", ruleset=rid, actor=who.name, detail={"refused": exc.code})
            raise _bad(exc, 400) from exc
        svc.audit.append("sponsor.layout", ruleset=rid, actor=who.name,
                         detail={"id": cur["id"], "log": len(cur["layout"]["log"]),
                                 "weekly": "weekly" in cur["layout"]})  # fmt: skip
        return cur

    @r.post("/studies/{rs}/sponsor/weekly")
    def weekly(rs: str, body: WeeklyBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        sha, rows = sheet(svc, rid, body, who.name)
        props = sp.proposals(svc.dc, rid, rows, _today(svc, body.today))
        counts = {k: sum(1 for p in props if p["kind"] == k) for k in ("same", "step", "held", "unknown")}
        svc.audit.append("sponsor.weekly", ruleset=rid, actor=who.name,
                         detail={"file": sha[:16], "name": body.name[:120], **counts})  # fmt: skip
        return {"file": sha, "name": body.name, "proposals": props, "counts": counts}

    @r.post("/studies/{rs}/sponsor/weekly/confirm")
    def confirm(rs: str, body: ConfirmBody, who: Claim = AS_ENTER) -> dict[str, Any]:
        svc, rid = get(), _rs(rs)
        sha, rows = sheet(svc, rid, body, who.name)
        today = _today(svc, body.today)
        life = Lifecycle(svc.dc)
        recs = [_rec(x) for x in body.records]
        kinds = {p["record"]: p for p in sp.proposals(svc.dc, rid, rows, today)}
        for rec in recs:  # every record checked first: a refusal leaves no step taken
            p = kinds.get(rec)
            if p is None or p["kind"] != "step":
                why = "none" if p is None else str(p.get("why") or p["kind"])
                svc.audit.append("life.refused", ruleset=rid, actor=who.name,
                                 detail={"record": rec, "source": "sponsor_weekly", "why": why})  # fmt: skip
                raise _refused(LifeError(why, f"the sheet proposes no step for {rec}"))
        done: list[dict[str, Any]] = []
        for rec in recs:
            before = life.subject(rid, rec)
            try:
                sub = sp.confirm(svc.dc, rid, sha, rows, rec, by=who.name, at=svc.stamp(), today=today)
            except LifeError as exc:
                svc.audit.append("life.refused", ruleset=rid, actor=who.name,
                                 detail={"record": rec, "source": "sponsor_weekly", "why": exc.why})  # fmt: skip
                raise _refused(exc) from exc
            log_why = mirror(svc.registry, rid, str(sub["pid"]), str(sub["state"]), who.name, svc.now())
            svc.audit.append("life.step", ruleset=rid, actor=who.name,
                             detail={"record": rec, "steps": [[before["state"] if before else None, sub["state"]]],
                                     "reason": sub["reason"], "source": "sponsor_weekly",
                                     "file": sha[:16]})  # fmt: skip
            done.append({"subject": sub, "screening_log": log_why or "ok"})
        return {"file": sha, "done": done}

    return r
