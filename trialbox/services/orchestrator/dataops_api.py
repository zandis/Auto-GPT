"""NEW-ARCH-3 (D-761): the data operations of the night (``datacore.dataops``) over the orchestrator's routes.

The console read and changed the ``dataops`` schema itself (its database role held it): a process boundary that
was no data boundary (the deep review's ARCH-005). Now the console's data-operations page asks these routes; the
console's role leaves the schema. The steward's accept or reject (``dataops.decide``) is one signed route, and the
publish of an accepted night runs here, next to the store, through the adapter's ``POST /publish`` (the
orchestrator's alone, D-760): the console holds no promoter any more.

Reads answer a night's rows as the store keeps them: counts and step names, never a patient's row (D-443)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from tb_common.actor_v3 import Claim
from tb_common.config import site_tz
from tb_common.db import DatabaseError
from tb_common.http import ServiceError

from orchestrator.actor import require_actor

log = logging.getLogger("orchestrator.dataops")

AS_DECIDER = require_actor("dataops.decide")


class DecideBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(min_length=1, max_length=10)
    reason: str = Field(default="", max_length=500)


class PublishFailed(RuntimeError):
    """The publish of an accepted night did not end "done" (``datacore.dataops.DataOps.decide`` reads the marks)."""

    nothing_served = False
    not_started = False


def promoter(adapter: Any, poll: Any = None) -> Callable[[Any], None]:
    """T-723 (D-489), here since NEW-ARCH-3: start the adapter's publish of the held night and follow it to its end
    (a polled job, never timed: D-472). Anything but ``done`` raises and the night stays held; a publish that ended
    without serving the night says ``nothing_served``, a refusal before any start ``not_started``. Posted once."""

    def promote(batch: Any) -> None:
        from tb_common.jobpoll import JobLost, Poll

        body = {"snapshot": batch.snapshot, "source": batch.source, "attempt": batch.attempt}
        try:
            started = adapter.publish(body)
        except ServiceError as exc:
            err = PublishFailed(f"the adapter did not start the publish (HTTP {exc.status})")
            err.nothing_served, err.not_started = exc.status == 404, exc.status == 409
            raise err from exc
        rid = str(started.get("run") or "")

        def read() -> dict[str, Any]:
            try:
                state: dict[str, Any] = adapter.publish_state(rid)
            except ServiceError as exc:
                if exc.status == 404:
                    raise JobLost(f"the adapter no longer knows publish {rid} (it restarted)") from None
                raise
            return state

        st = started if started.get("state") != "running" else (poll or Poll()).until_done(read, "publish")
        if st.get("state") != "done":
            err = PublishFailed(f"the publish ended {st.get('state')}")
            err.nothing_served = st.get("promoted") is False
            raise err

    return promote


def router(ops: Callable[[], Any], adapter: Callable[[], Any], audit: Callable[[], Any],
           poll: Any = None) -> APIRouter:  # fmt: skip
    """``ops``: the ``DataOps`` store; ``adapter``: the adapter client (``AdapterHttp``) or None; ``audit``: the
    box's audit writer."""
    from datacore.dataops import MAX_PAGE, STATES, DataOpsError

    r = APIRouter()

    def store() -> Any:
        try:
            return ops()
        except DatabaseError as exc:
            log.warning("dataops store unreachable (%s)", type(exc).__name__)
            raise HTTPException(status_code=503, detail={"why": "store"}) from exc

    def rows(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except DatabaseError as exc:
            log.warning("dataops store failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=503, detail={"why": "store"}) from exc

    @r.get("/dataops/can-publish")
    def can_publish() -> dict[str, bool]:
        """Whether an accept can publish here (this service has the adapter); the page offers Accept only then."""
        return {"publish": adapter() is not None}

    @r.get("/dataops/sources")
    def sources() -> list[dict[str, Any]]:
        return [b.as_dict() for b in rows(store().sources)]

    @r.get("/dataops/held")
    def held() -> list[dict[str, Any]]:
        return [b.as_dict() for b in rows(store().held)]

    @r.get("/dataops/counts")
    def counts() -> dict[str, int]:
        out: dict[str, int] = rows(store().counts)
        return out

    @r.get("/dataops/history")
    def history(state: str = "", source: str = "", limit: int = Query(50, ge=1, le=MAX_PAGE + 1),
                before: int | None = Query(None, ge=1)) -> list[dict[str, Any]]:  # fmt: skip
        st = state if state in STATES else None
        s = store()
        return [b.as_dict() for b in rows(lambda: s.history(st, source.strip()[:80] or None, limit=limit,
                                                             before=before))]  # fmt: skip

    @r.get("/dataops/batches/{bid}")
    def batch(bid: int) -> dict[str, Any]:
        b = rows(lambda: store().batch(bid))
        if b is None:
            raise HTTPException(status_code=404, detail={"why": "not_found"})
        out: dict[str, Any] = b.as_dict()
        return out

    @r.get("/dataops/batches/{bid}/steps")
    def steps(bid: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = rows(lambda: store().steps(bid))
        return out

    @r.post("/dataops/batches/{bid}/decide")
    def decide(bid: int, body: DecideBody, claim: Claim = AS_DECIDER) -> dict[str, Any]:
        """The steward's accept or reject of a held night, with a reason, under the verified person. Accept runs the
        publish (``promoter``); a refusal of the store answers 409 with its ``why`` (``decision``, ``reason``,
        ``not_found``, ``not_held``, ``publishing``), a publish that did not end "done" 502 with its marks."""
        a = adapter()
        hook = promoter(a, poll) if a is not None else None
        if body.decision == "accept" and hook is None:
            raise HTTPException(status_code=409, detail={"why": "promote"})
        at = datetime.now(ZoneInfo(site_tz())).isoformat(timespec="seconds")
        s = store()
        try:
            done = rows(lambda: s.decide(audit(), bid, body.decision, by=claim.sub, at=at, reason=body.reason,
                                         promote=hook))  # fmt: skip
        except DataOpsError as exc:
            raise HTTPException(status_code=409, detail={"why": exc.why, "message": exc.message}) from exc
        except PublishFailed as exc:
            raise HTTPException(status_code=502, detail={"why": "promote", "nothing_served": exc.nothing_served,
                                                         "not_started": exc.not_started}) from exc  # fmt: skip
        except HTTPException:
            raise
        except Exception as exc:  # the publish's end is not known (its job was lost): the accept stays recorded
            log.warning("publish of batch %s ended unknown (%s)", bid, type(exc).__name__)
            raise HTTPException(status_code=502, detail={"why": "promote", "nothing_served": False,
                                                         "not_started": False}) from exc  # fmt: skip
        out: dict[str, Any] = done.as_dict()
        return out

    return r
