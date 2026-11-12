"""adapter API.

* ``POST /run`` starts one ingest and answers 202 with its run id; ``GET /run/<id>`` reports its state and, when done,
  the ingest report (the orchestrator's nightly job and the console poll it; T-690, D-472).
* ``POST /publish`` publishes a held night (the steward's accept; T-723, D-489) as a job; ``GET /publish/<id>``
  reports its state and its steps.
* ``POST /$validate`` (D-137): JP Core ``$validate``, offline. Body ``{"resources": [...]}`` checks those resources
  (one resource gives its FHIR ``OperationOutcome``); ``{"snapshot": "YYYY-MM-DD", "per_type": 50}`` checks a sample of
  a written snapshot (the newest when ``snapshot`` is empty). The answer lists every failure in plain words.
* ``GET /terminology`` (D-137): which licensed code lists (MEDIS 標準病名, JLAC10, YJ) are loaded, with version and
  source; ``POST /terminology/load`` loads one release from a file on the box (``path``) or sent in ``b64``.

Every call goes through ``make_app``'s service-token rule (writes always; reads as configured).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import logging
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from tb_common.http import make_app
from tb_contracts import IngestRequest, dump

from adapter.cli import build_config
from adapter.pipeline import SiteKeyError, run_ingest

log = logging.getLogger("adapter")
app = make_app("adapter")
_running = threading.Lock()
#: T-723 review: set while a steward's accept publishes a held night. A nightly run that arrives then waits for it
#: (its job says ``waiting``) and is not refused: an accept must never make the night's ingest fail
_accepting = threading.Event()
#: T-690 (D-472): the ingest runs of this process by id, the newest last (one ingest at a time; nights are one a day,
#: so this holds a few small reports; a restart forgets them and a poller then reports the run lost)
_runs: dict[str, dict[str, Any]] = {}
#: T-723 (D-489): the publishes of held nights (the steward's accept) of this process by id; as ``_runs``
_publishes: dict[str, dict[str, Any]] = {}


def _spawn(run: Callable[[], None]) -> None:
    threading.Thread(target=run, name="adapter-ingest", daemon=True).start()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@app.post("/run", status_code=202)
def run(req: IngestRequest) -> JSONResponse:
    """T-690 (D-472): start one ingest and answer 202 with its run id; ``GET /run/<id>`` follows it (``running``,
    ``done`` with the ingest report, ``refused`` when the site key is missing or changed, ``failed``). The night is
    never timed by the caller (OD-10). A second start while an ingest runs is 409. While a steward's accept
    publishes a held night (T-723) the run is taken and waits for it: its state is ``running`` with the detail
    "waiting for a publish", and it starts when the publish ends."""
    waits = False
    if not _running.acquire(blocking=False):
        if not _accepting.is_set():
            busy = next((r["run"] for r in reversed(_runs.values()) if r["state"] == "running"), "")
            raise HTTPException(status_code=409, detail="an ingest is already running", headers={"X-TB-Run": busy})
        waits = True
    try:
        ac, default_kind, default_path = build_config()
        path = req.path or default_path
        if req.source != default_kind and not req.path:
            raise HTTPException(status_code=400, detail="path required when overriding the source type")
    except BaseException:
        if not waits:
            _running.release()
        raise
    rid = os.urandom(8).hex()
    state: dict[str, Any] = {"run": rid, "state": "running", "started": _now(), "ended": None,
                             "detail": "waiting for a publish to end" if waits else ""}  # fmt: skip
    _runs[rid] = state

    def work() -> None:
        if waits:  # behind the accept, however long it takes (never timed: OD-10)
            _running.acquire()
            state["detail"] = ""
        try:
            report = run_ingest(
                ac,
                req.source,
                path or os.environ.get("TB_SOURCE_PATH", ""),
                since=req.since,
                snapshot=req.snapshot.isoformat() if req.snapshot else None,
                load_fhir=req.load_fhir,
                rebuild_lake=req.rebuild_lake,
                validate=req.validate_,
            )
            state.update(state="done", report=dump(report))
        except SiteKeyError as exc:  # T-612: refused before anything was read or written
            state.update(state="refused", detail=f"night refused: {exc}")
        except Exception as exc:
            log.exception("ingest run %s failed", rid)
            state.update(state="failed", detail=f"{type(exc).__name__}: {str(exc)[:500]}")
        finally:
            state["ended"] = _now()
            _running.release()

    _spawn(work)
    return JSONResponse(dict(state), status_code=202, headers={"Location": f"/run/{rid}"})


@app.get("/run/{rid}")
def run_state(rid: str) -> dict[str, Any]:
    """The state of one ingest run of this process (404: unknown here, e.g. the adapter restarted)."""
    st = _runs.get(rid)
    if st is None:
        raise HTTPException(status_code=404, detail="unknown run (the adapter may have restarted)")
    return dict(st)


@app.get("/run")
def latest_run() -> dict[str, Any]:
    """The newest ingest run of this process, or ``{"state": "none"}``."""
    return dict(next(reversed(_runs.values()))) if _runs else {"state": "none"}


class PublishBody(BaseModel):
    snapshot: str
    source: str = ""
    attempt: int | None = None


@app.post("/publish", status_code=202)
def publish(body: PublishBody) -> JSONResponse:
    """T-723 (D-489): the steward's accept. Publishes the held night's folder as it stands, with the same function
    a night that passed the gate goes through (``adapter.publish``), as a job: 202 and a run id, ``GET
    /publish/<id>`` follows it (``running``, ``done``, ``busy`` when a job holds the snapshot, ``stale`` when a
    newer night is already served, ``failed`` with the step). ``done`` means the night is served (``promoted``).
    A night that was published already (its folder says it passed and every step of its record ended) is answered
    ``done`` at once: an accept whose end the console lost is recorded by accepting again (review HIGH-2).
    Refused at once, nothing touched: no held night of that date (404), an attempt that is not the newest of its
    night (409), an ingest or another publish running (409)."""
    from datacore.dataops import DataOps

    from adapter.publish import NothingToPublish, held_folder, publish_held, published

    if not _running.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="an ingest or a publish is already running")
    _accepting.set()  # second review (L1): from here a night's run waits, also while the accept is still checked
    try:
        ac = build_config()[0]
        try:
            held_folder(ac, body.snapshot)
        except NothingToPublish as exc:
            if published(ac, body.snapshot):
                _accepting.clear()
                _running.release()
                rid = os.urandom(8).hex()
                _publishes[rid] = {"run": rid, "state": "done", "started": _now(), "ended": _now(), "detail":
                                   "published already", "snapshot": body.snapshot, "steps": {},
                                   "promoted": True}  # fmt: skip
                return JSONResponse(dict(_publishes[rid]), status_code=202, headers={"Location": f"/publish/{rid}"})
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if body.source and body.attempt is not None:
            ops = DataOps(ac.db_url or os.environ.get("TB_DB_URL"))
            try:
                newest = max((b.attempt for b in ops.batches(source=body.source) if b.snapshot == body.snapshot),
                             default=body.attempt)  # fmt: skip
            finally:
                ops.close()
            if newest != body.attempt:
                raise HTTPException(
                    status_code=409,
                    detail=f"attempt {body.attempt} of night {body.snapshot} is not the newest ({newest}): decide "
                    "the newest attempt",
                )
    except BaseException:
        _accepting.clear()
        _running.release()
        raise
    rid = os.urandom(8).hex()
    state: dict[str, Any] = {"run": rid, "state": "running", "started": _now(), "ended": None, "detail": "",
                             "snapshot": body.snapshot, "steps": {}}  # fmt: skip
    _publishes[rid] = state

    def work() -> None:
        try:
            out = publish_held(ac, body.snapshot, on_step=lambda _s, steps: state.update(steps=steps))
            state.update(steps=dict(out.steps), promoted=out.promoted)
            if out.ok and out.promoted:  # review HIGH-1: "done" is a night that is served, nothing less
                state.update(state="done")
            else:
                ended = "busy" if out.lake_busy else "stale" if out.stale else "failed"
                state.update(state=ended, detail="; ".join(out.errors)[:500])
        except Exception as exc:
            log.exception("publish %s failed", rid)
            state.update(state="failed", detail=f"{type(exc).__name__}: {str(exc)[:500]}")
            # second review (H1): what the lake serves is read, also when the publish raised. Unreadable: it stays
            # unset, and the console keeps the accept recorded
            with contextlib.suppress(OSError):
                state["promoted"] = (ac.lake_dir / "CURRENT").read_text(encoding="utf-8").strip() == body.snapshot
        finally:
            state["ended"] = _now()
            _accepting.clear()
            _running.release()

    _spawn(work)
    return JSONResponse(dict(state), status_code=202, headers={"Location": f"/publish/{rid}"})


@app.get("/publish/{rid}")
def publish_state(rid: str) -> dict[str, Any]:
    """The state of one publish of this process (404: unknown here, e.g. the adapter restarted)."""
    st = _publishes.get(rid)
    if st is None:
        raise HTTPException(status_code=404, detail="unknown publish (the adapter may have restarted)")
    return dict(st)


class ValidateBody(BaseModel):
    resources: list[dict[str, Any]] | None = None
    snapshot: str = ""
    per_type: int = Field(default=50, ge=1, le=5000)


@app.post("/$validate")
def validate(body: ValidateBody) -> dict[str, Any]:
    from adapter import licensed
    from adapter.ndjson import list_snapshots, snapshot_dir
    from adapter.validate.jpcore import JpCoreValidator, sample_per_type, validate_snapshot

    terms = licensed.tables()
    if body.resources is not None:
        v = JpCoreValidator(terms)
        if len(body.resources) == 1:
            one = v.check(body.resources[0])
            return {"ok": one.ok, "resource": one.resource, "profile": one.profile, "outcome": one.operation_outcome()}
        rep = v.validate(sample_per_type(body.resources, body.per_type))
    else:
        lake = Path(os.environ.get("TB_LAKE_DIR") or build_config()[0].lake_dir)
        snap = body.snapshot or (list_snapshots(lake) or [""])[-1]
        if not snap or not snapshot_dir(lake, snap).is_dir():
            raise HTTPException(status_code=404, detail=f"no snapshot {snap or '(none written yet)'}")
        rep = validate_snapshot(snapshot_dir(lake, snap), body.per_type, terms)
    return {"ok": rep.errors == 0, **rep.as_json()}


class LoadBody(BaseModel):
    kind: str
    version: str
    by: str
    path: str = ""
    b64: str = ""
    name: str = ""
    columns: list[str] | None = None


@app.get("/terminology")
def terminology() -> list[dict[str, Any]]:
    from adapter import licensed

    return licensed.status()


@app.post("/terminology/load")
def terminology_load(body: LoadBody) -> dict[str, Any]:
    from adapter.licensed import LicensedError, TermStore

    if body.b64:
        try:
            data, source = base64.b64decode(body.b64, validate=True), body.name or "upload"
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="b64 is not base64") from exc
    elif body.path:
        p = Path(body.path)
        if not p.is_file():
            raise HTTPException(status_code=404, detail=f"no file at {body.path}")
        data, source = p.read_bytes(), p.name
    else:
        raise HTTPException(status_code=400, detail="send the file as path or b64")
    st = TermStore()
    try:
        return st.load(body.kind, data, version=body.version, source=source, by=body.by, columns=body.columns)
    except LicensedError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    finally:
        st.close()
