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
only when its snapshot became the one served. The promoter is :func:`adapter_promoter` (T-723, D-489): the
adapter's publish of the held night, the same function a night that passed the gate goes through. ``register``
takes it as ``promote``; without one (a console with no adapter) an accept is refused with a message and the night
stays held. Reject needs no promotion (``CURRENT`` keeps the previous snapshot, D-149).

**API.** ``/api/v1/data/sources``, ``/api/v1/data/batches`` (``state``, ``source``, ``limit``, ``before``),
``/api/v1/data/batches/{id}`` and ``POST /api/v1/data/batches/{id}/decide`` answer the same functions with the
same checks. The session and the right are checked before the body is read: an unauthenticated empty body is 401,
never 422.

A store that cannot be reached is a 503, never a 500.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, get_args
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from tb_common.authz import permit
from tb_common.config import site_tz
from tb_common.db import DatabaseError
from tb_contracts.generated.models import DqdCheckRow

from console import i18n_dataops
from console.api_first import page_twin
from console.auth import Session
from console.home import Helpers
from console.i18n import CATALOGUES

log = logging.getLogger("console.dataops")

for _lang, _cat in (("en", i18n_dataops.EN), ("ja", i18n_dataops.JA), ("zh-TW", i18n_dataops.ZH)):
    CATALOGUES[_lang].update(_cat)

VIEW = "dataops.view"
DECIDE = "dataops.decide"
#: the states a listed DQD row may carry, as the ingest_report contract names them (omop.dqd.failed[].status)
DQD_STATES = frozenset(get_args(DqdCheckRow.model_fields["status"].annotation))
MAX_REASON = 500
PAGE = 50
# the light of a source from its newest night: held or stopped is red, a steward's reject (the box serves the night
# before) and a night still on the line are amber, a published night is green
LIGHT = {"PUBLISHED": "green", "HELD": "red", "FAILED": "red", "REJECTED": "amber"}
ERRORS = ("reason", "decision", "state", "promote", "publishing")

#: (method, path, body) -> the headers of the accepting person's signed claim (``console.actor.assert_for``)
Sign = Callable[[str, str, Any], dict[str, str]]


class PromoteFailed(RuntimeError):
    """The publish of an accepted night did not end "done". ``nothing_served``: it ended and the night is not
    served (an ordinary held night again); otherwise its end is not known (the accept stays recorded)."""

    nothing_served = False
    #: refused before anything started (the adapter was busy, or the orchestrator refused): this accept started
    #: nothing and learned nothing about an earlier one
    not_started = False


@dataclass(frozen=True)
class NightRow:
    """One ``dataops.batch`` row as the orchestrator's routes answer it (the fields of ``datacore.dataops.Batch``;
    the console imports no module of the store, NEW-ARCH-3)."""

    id: int
    source: str
    snapshot: str
    attempt: int
    state: str
    seq: int
    started_at: str
    changed_at: str
    changed_by: str
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class DecisionRefused(ValueError):
    """The store refused the steward's decision; ``why`` as ``datacore.dataops.DataOpsError`` says it (``decision``,
    ``reason``, ``not_found``, ``not_held``, ``publishing``, ``promote``)."""

    def __init__(self, why: str, message: str = "") -> None:
        super().__init__(why)
        self.why = why
        self.message = message or why


@dataclass(frozen=True)
class Decided:
    """The steward's decision as the orchestrator answered it: the row, and ``publishing`` when the accept is
    recorded and the night's publish still runs there (it ends as PUBLISHED, or held again)."""

    row: NightRow
    publishing: bool = False


class OrchOps:
    """NEW-ARCH-3 (D-761): the night's data operations over the orchestrator's routes (``/dataops/...``), with the
    method names of ``datacore.dataops.DataOps`` that this page reads. The console opens no ``dataops`` store and its
    database role leaves the schema. The steward's decision is one signed request; the orchestrator runs the
    publish of an accepted night (D-760). Posted with the client that never retries: a retry could meet the publish
    the first request started."""

    def __init__(self, bk: Any) -> None:
        self.bk = bk

    @staticmethod
    def _batch(row: dict[str, Any]) -> NightRow:
        from dataclasses import fields

        return NightRow(**{f.name: row[f.name] for f in fields(NightRow)})

    def _get(self, path: str) -> Any:
        return self.bk.orch.get_json(path)

    def can_publish(self) -> bool:
        return bool(self._get("/dataops/can-publish").get("publish"))

    def sources(self) -> list[Any]:
        return [self._batch(r) for r in self._get("/dataops/sources")]

    def held(self) -> list[Any]:
        return [self._batch(r) for r in self._get("/dataops/held")]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = self._get("/dataops/counts")
        return out

    def history(self, state: str | None, source: str | None, *, limit: int, before: int | None) -> list[Any]:
        from urllib.parse import urlencode

        q = {"limit": limit, **({"state": state} if state else {}), **({"source": source} if source else {}),
             **({"before": before} if before else {})}  # fmt: skip
        return [self._batch(r) for r in self._get(f"/dataops/history?{urlencode(q)}")]

    def batch(self, bid: int) -> Any:
        from tb_common.http import ServiceError

        try:
            return self._batch(self._get(f"/dataops/batches/{int(bid)}"))
        except ServiceError as exc:
            if exc.status == 404:
                return None
            raise

    def steps(self, bid: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = self._get(f"/dataops/batches/{int(bid)}/steps")
        return out

    def decide(self, bid: int, decision: str, reason: str, sign: Sign) -> Any:
        """The steward's accept or reject, signed as the steward. Raises ``DecisionRefused`` with the store's ``why``
        (409) and ``PromoteFailed`` with the publish's marks (502)."""
        from tb_common.http import ServiceError

        if decision not in ("accept", "reject"):  # the review: refused here as the store refuses it, nothing sent
            raise DecisionRefused("decision", "decision must be accept or reject")
        path, body = f"/dataops/batches/{int(bid)}/decide", {"decision": decision, "reason": reason}
        once = getattr(self.bk, "orch_once", None) or self.bk.orch
        try:
            r = once.post_raw(path, body, sign("POST", path, body))
            got = r.json()
            row = self._batch(got)
            return Decided(row, bool(got.get("publishing")))
        except ServiceError as exc:
            detail = _detail(exc.detail)
            if exc.status == 409:
                raise DecisionRefused(str(detail.get("why") or "state"), str(detail.get("message") or "")) from exc
            if exc.status == 502:
                err = PromoteFailed("the publish did not end done")
                err.nothing_served = bool(detail.get("nothing_served"))
                err.not_started = bool(detail.get("not_started"))
                raise err from exc
            if exc.status == 422:  # the request's shape: the store never saw it
                raise DecisionRefused("decision", "the decision was not understood") from exc
            if exc.status in (401, 403):  # the orchestrator refused the person before anything started
                if decision != "accept":
                    raise DecisionRefused("forbidden", "the orchestrator refused the decision") from exc
                err = PromoteFailed(f"the orchestrator refused the decision (HTTP {exc.status})")
                err.not_started = True
                raise err from exc
            if exc.status == 0 and decision == "accept":  # no answer: the accept may be recorded, its end not known
                raise PromoteFailed("no answer to the accept") from exc
            raise


def _detail(text: str) -> dict[str, Any]:
    """The ``detail`` object of an orchestrator refusal ({} when it is not one)."""
    try:
        got = json.loads(text).get("detail")
    except (ValueError, AttributeError):
        return {}
    return got if isinstance(got, dict) else {}


def unmapped_of(detail: Any) -> list[tuple[str, int]]:
    """NEW-DOPS-1 (D-708): the rows of a night that hold a value the mapping could not use, per source table, the
    largest first. It is D-580's counter as the night's row keeps it: rows left out (a code no look-up knows, an
    unknown status) and rows kept without the value (a unit not read: D-590), and rows whose code the reference
    data could not be asked for (D-593); a row is counted once per such value. The values are in the night's
    ``unmapped_codes.json``, never here. Every table is listed: no cut. A value that is not a table name
    with a count above zero is not shown."""
    kept = detail.get("unmapped") if isinstance(detail, dict) else None
    if not isinstance(kept, dict):
        return []
    rows = [(str(t), n) for t, n in kept.items() if t and isinstance(t, str) and type(n) is int and n > 0]
    return sorted(rows, key=lambda r: (-r[1], r[0]))


def site_profile_of(detail: Any) -> dict[str, Any] | None:
    """10B-6 (D-1233): the site profile a night was read with and its coverage counts, as the adapter's
    ``ingest.done`` event keeps them (``adapter.site_profile.summary``); None for a night read without one, or for a
    record that is not that shape. Counts and names of data types only, never a code or a value."""
    sp = detail.get("site_profile") if isinstance(detail, dict) else None
    if not isinstance(sp, dict):
        return None
    words = ("id", "version", "digest")
    counts = ("types_declared", "types_arrived", "unmapped_codes", "unmapped_rows", "verify_rows")
    lists = ("not_arrived", "not_declared")
    if not all(isinstance(sp.get(k), str) and sp[k] for k in words):
        return None
    if not all(type(sp.get(k)) is int and sp[k] >= 0 for k in counts):
        return None
    if not all(isinstance(sp.get(k), list) and all(isinstance(x, str) for x in sp[k]) for k in lists):
        return None
    # added with the review of #1128: a record written before has neither (none read, none counted)
    not_read = sp.get("not_read", [])
    facts = sp.get("facts_from_verify", 0)
    if not (isinstance(not_read, list) and all(isinstance(x, str) for x in not_read)):
        return None
    if not (type(facts) is int and facts >= 0):
        return None
    units, pending = sp.get("units_not_read_rows", 0), sp.get("pending")
    if not (type(units) is int and units >= 0) or not (pending is None or isinstance(pending, str)):
        return None
    return {**{k: sp[k] for k in (*words, *counts, *lists)}, "digest": sp["digest"][:12], "not_read": not_read,
            "facts_from_verify": facts, "units_not_read_rows": units,
            "pending": pending[:12] if pending else None}  # fmt: skip


#: 10B-23 (D-1254): a full night older than this, with nightly (delta) updates since, is shown as a warning. A week:
#: the night's weekly work (the Monday micro-batch and NAV, D-492) then always has a full night within its own week;
#: the reason in full is in D-1254. A constant, not a setting
FULL_NIGHT_STALE_DAYS = 7


def full_night_of(rows: Any, today: date) -> dict[str, Any] | None:
    """10B-23 (D-1254): the lake's record of its last full night, as the newest night row (by id) that carries it
    (``adapter.full_nights.said``, kept in the night's event): ``last_full`` (a date or None: not known), ``days``
    since it, ``deltas`` (nightly updates since) and ``warn``. None when no row carries a record of that shape, or
    when it says nothing (not known and no delta night): the page then shows no line."""
    best: tuple[int, dict[str, Any]] | None = None
    for b in rows:
        fn = b.detail.get("full_night") if isinstance(b.detail, dict) else None
        if not isinstance(fn, dict) or (best is not None and b.id <= best[0]):
            continue
        last, deltas = fn.get("last_full"), fn.get("deltas")
        if type(deltas) is not int or deltas < 0:
            continue
        if last is not None:
            try:
                day = date.fromisoformat(last) if isinstance(last, str) and len(last) == 10 else None
            except ValueError:
                day = None
            if day is None:
                continue
        best = (b.id, {"last_full": last, "deltas": deltas})
    if best is None:
        return None
    got = best[1]
    if got["last_full"] is None:
        return None if got["deltas"] == 0 else {**got, "days": None, "warn": True}
    days = max(0, (today - date.fromisoformat(got["last_full"])).days)  # a clock behind the night: today
    return {**got, "days": days, "warn": got["deltas"] > 0 and days > FULL_NIGHT_STALE_DAYS}


def dqd_of(detail: Any) -> dict[str, Any] | None:
    """H3-NLP §3.1: the data quality checks of the night's OMOP load that did not pass (``adapter.dual_write``):
    the counts and each row in DQD's words. None when the night carries none or a record of another shape."""
    omop = detail.get("omop") if isinstance(detail, dict) else None
    got = omop.get("dqd") if isinstance(omop, dict) else None
    if not isinstance(got, dict) or not all(isinstance(got.get(k), int) for k in ("checks", "fail", "known")):
        return None
    rows = got.get("failed")
    if not isinstance(rows, list) or not all(
        isinstance(r, dict) and isinstance(r.get("checkName"), str) and r.get("status") in DQD_STATES for r in rows
    ):
        return None
    return {"checks": got["checks"], "fail": got["fail"], "known": got["known"], "failed": rows}


def unmapped_kinds_of(detail: Any) -> dict[str, dict[str, int]]:
    """NEW-B-39 (D-740): the same rows per source table split by kind (``tb_common.unmapped.KINDS``: a code no look-up
    knows, a unit not read, the reference data not reached); counts only. A table whose split is not counts of the
    named kinds adding up to the table's total (:func:`unmapped_of`) is not shown."""
    from tb_common.unmapped import KINDS

    kept = detail.get("unmapped_kinds") if isinstance(detail, dict) else None
    if not isinstance(kept, dict):
        return {}
    totals = dict(unmapped_of(detail))
    out: dict[str, dict[str, int]] = {}
    for table, kinds in kept.items():
        if (
            isinstance(table, str)
            and table
            and isinstance(kinds, dict)
            and set(kinds) == set(KINDS)
            and all(type(n) is int and n >= 0 for n in kinds.values())
            and sum(kinds.values()) == totals.get(table)
        ):
            out[table] = {k: kinds[k] for k in KINDS}
    return out


def light(state: str) -> str:
    return LIGHT.get(state, "amber")


def register(app: FastAPI, h: Helpers) -> None:
    ops_client = OrchOps(h.bk)

    def store() -> Any:
        """The night's data operations, over the orchestrator's routes (NEW-ARCH-3, D-761)."""
        return ops_client

    def read(fn: Callable[[], Any]) -> Any:
        from tb_common.http import ServiceError

        from console.backend import Unavailable

        try:
            return fn()
        except (DatabaseError, Unavailable, ServiceError) as e:  # the orchestrator or its store cannot answer
            if isinstance(e, ServiceError) and 0 < e.status < 500:  # the review: 0 is "no answer", not a refusal
                raise
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
        ops = store()
        st = state.strip()[:20] or None  # the orchestrator reads only a state of the store
        rows = read(lambda: ops.history(st, source.strip()[:80] or None, limit=limit + 1, before=before))
        more = len(rows) > limit
        rows = rows[:limit]
        return rows, (rows[-1].id if more and rows else None)

    def decide(sess: Session, bid: int, decision: str, reason: str) -> Any:
        """The steward's accept or reject (``DataOps.decide``, at the orchestrator). Raises ``DecisionRefused``
        with ``why``: ``decision``,
        ``reason``, ``not_found``, ``not_held``, ``step`` or ``promote``."""

        why = reason.strip()[:MAX_REASON]

        def sign(method: str, path: str, body: Any) -> dict[str, str]:  # NEW-SEC-4 (D-760): the steward who decides
            from console import actor

            return actor.assert_for(h, sess, DECIDE, None, method, path, body)

        ops = store()
        return read(lambda: ops.decide(bid, decision, why, sign))

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
            sources=[
                {**b.as_dict(), "light": light(b.state), "unmapped": sum(n for _, n in unmapped_of(b.detail))}
                for b in sources
            ],
            waiting=waiting,
            rows=rows,
            counts=read(ops.counts),
            full_night=full_night_of([*sources, *rows], h.today()),  # 10B-23 (D-1254): the site's date
            state=state,
            source=source,
            next_before=nxt,
            may_decide=permit(sess.user.role, DECIDE),
            can_accept=read(ops.can_publish),  # NEW-ARCH-3: the orchestrator says whether an accept can publish
            done=done if done in ("accept", "reject", "publishing") else "",
            err=err if err in ERRORS else "",
        )

    def country_card() -> dict[str, Any] | None:
        from console.country_profile import card

        return card(h.bk)

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
            unmapped=unmapped_of(b.detail),
            dqd=dqd_of(b.detail),  # H3-NLP §3.1
            profile=site_profile_of(b.detail),  # 10B-6 (D-1233)
            layer=country_card() if site_profile_of(b.detail) else None,  # 10C-25 (D-1250): the country layer's lines
            may_decide=permit(sess.user.role, DECIDE),
            can_accept=read(ops.can_publish),  # NEW-ARCH-3: the orchestrator says whether an accept can publish
        )

    @app.post("/data-ops/batches/{bid}/decide")
    def dataops_decide(
        request: Request, bid: int, csrf: str = Form(""), decision: str = Form(""), reason: str = Form("")
    ) -> Response:
        sess = guard(request, DECIDE)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        try:
            got = decide(sess, bid, decision, reason)
        except DecisionRefused as e:
            if e.why == "not_found":
                raise h.problem(404, "notfound") from e
            if e.why == "forbidden":
                raise h.problem(403, "forbidden") from e
            code = {"not_held": "state", "step": "state", "by": "reason"}.get(e.why, e.why)
            return RedirectResponse(f"/data-ops?err={code if code in ERRORS else 'state'}", status_code=303)
        except PromoteFailed as e:  # the night stays held; its accept stays recorded unless nothing is served
            served_none = e.nothing_served or e.not_started  # nothing published: an ordinary held night
            return RedirectResponse(f"/data-ops?err={'promote' if served_none else 'publishing'}",
                                    status_code=303)  # fmt: skip
        done = "publishing" if got.publishing else decision
        return RedirectResponse(f"/data-ops?done={done}", status_code=303)

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
        kinds = unmapped_kinds_of(b.detail)  # NEW-B-39 (D-740)
        return {"batch": b.as_dict(), "steps": read(lambda: ops.steps(bid)),
                "unmapped": [{"table": t, "rows": n, **({"kinds": kinds[t]} if t in kinds else {})}
                             for t, n in unmapped_of(b.detail)],
                "site_profile": site_profile_of(b.detail), "data_quality": dqd_of(b.detail)}  # fmt: skip

    @app.post("/api/v1/data/batches/{bid}/decide")
    @page_twin("/data-ops/batches/{bid}/decide")  # T-657 (D-444): the page's twin (FIT-019)
    async def api_decide(request: Request, bid: int) -> dict[str, Any]:
        sess = api_guard(request, DECIDE)  # the session and the right first; the body only then
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise h.problem(400, "request.refused", code="DATAOPS-BODY", reason="a JSON object", fields="")
        decision, reason = str(body.get("decision") or ""), str(body.get("reason") or "")
        try:
            b = decide(sess, bid, decision, reason)
        except DecisionRefused as e:
            if e.why == "not_found":
                raise h.problem(404, "notfound") from e
            if e.why == "forbidden":
                raise h.problem(403, "forbidden") from e
            status = 409 if e.why in ("not_held", "step", "promote") else 400
            raise h.problem(status, "request.refused", code=f"DATAOPS-{e.why.upper()}", reason=e.message,
                            fields="") from e  # fmt: skip
        except PromoteFailed as e:  # the night stays held
            why = (
                "the publish failed and nothing is served; the night stays held"
                if e.nothing_served or e.not_started
                else "the end of the publish is not known; the accept is recorded: accept again to record its end"
            )
            raise h.problem(409, "request.refused", code="DATAOPS-PROMOTE", reason=why, fields="") from e
        return {"batch": b.row.as_dict(), "publishing": b.publishing}
