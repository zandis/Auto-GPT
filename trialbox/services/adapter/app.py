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
import json
import logging
import os
import subprocess
import sys
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

from adapter import runs
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


RUN_MODES = ("process", "thread")
#: the ingest processes this service started, by run id (D-663): for the thread that waits for each
_children: dict[str, subprocess.Popen[bytes]] = {}


def run_mode() -> str:
    """``TB_ADAPTER_RUN`` (D-663): ``process`` (the default, what a box runs): the night's ingest is a process of
    its own with its run record on disk; killed, it does not take the service with it, and a restart of the service
    does not forget it. ``thread``: in this process, for a configuration handed to the service in memory (another
    process cannot be given it)."""
    mode = os.environ.get("TB_ADAPTER_RUN", "process").strip().lower()
    if mode not in RUN_MODES:
        raise ValueError(f"TB_ADAPTER_RUN is {mode!r}; use one of {', '.join(RUN_MODES)}")
    return mode


def _lake_dir() -> Path:
    return Path(os.environ.get("TB_LAKE_DIR") or build_config()[0].lake_dir)


def _run_command(lock_fd: int, spec: dict[str, Any]) -> list[str]:
    return [sys.executable, "-m", "adapter.run_job", str(lock_fd), json.dumps(spec)]


def _child_env() -> dict[str, str]:
    """The ingest's process imports what this process imports: this process's import path is handed on, whatever
    put it there (the image's ``PYTHONPATH``, a test runner's own setting)."""
    return {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}


def _run_in_process(state: dict[str, Any], lake_dir: Path, request: dict[str, Any]) -> None:
    """Run one ingest as ``python -m adapter.run_job`` and wait for it (called in the service's waiting thread, which
    holds ``_running``). The child inherits the run lock's open file; this process closes its end and never
    unlocks. The run's record is on disk from before the child starts; the child writes its end. A child that ends
    without an answer is ``failed``, with its exit code when it ended by itself."""
    rid = str(state["run"])
    proc: subprocess.Popen[bytes] | None = None
    unreadable = False
    try:
        try:
            lock = runs.RunLock(lake_dir)
        except runs.RunLockHeld:
            other = runs.holder(lake_dir)
            state.update(state="failed", detail=f"an ingest is already running (run {other or 'unknown'}): this run "
                                               "was not started")  # fmt: skip
            return
        try:
            runs.hold(lake_dir, rid)
            runs.write(lake_dir, state)
            runs.prune(lake_dir)
            spec = {"state": dict(state), "lake_dir": str(lake_dir), "request": request}
            proc = subprocess.Popen(
                _run_command(lock.fileno(), spec), pass_fds=[lock.fileno()], stdin=subprocess.DEVNULL, env=_child_env()
            )
        finally:
            lock.hand_over()  # closed, never unlocked: an unlock would take the lock from the child
        _children[rid] = proc
        code = proc.wait()
        end = runs.read(lake_dir, rid)
        if end is None:  # the record cannot be read now: say so, and do not write over what the child wrote
            state.update(state="failed", detail="the run's record could not be read when the ingest's process ended")
            unreadable = True
            return
        if end.get("state") == "failed" and end.get("detail") == runs.ENDED_WITHOUT_ANSWER and code > 0:
            end = {**end, "detail": f"the ingest's process ended with exit code {code} and no answer (the adapter's "
                                    "log has its error)"}  # fmt: skip
        state.update(end)
    except Exception as exc:
        log.exception("ingest run %s could not be run as a process", rid)
        if proc is not None and proc.poll() is None:  # never a run behind a "failed" answer
            proc.kill()
            proc.wait()
        state.update(state="failed", detail=f"the ingest's process could not be run ({type(exc).__name__})")
    finally:
        _children.pop(rid, None)
        if state.get("state") == "running":
            state.update(state="failed", detail=runs.ENDED_WITHOUT_ANSWER)
        state["ended"] = state.get("ended") or _now()
        if not unreadable:
            with contextlib.suppress(Exception):
                runs.write(lake_dir, state)


@app.post("/run", status_code=202)
def run(req: IngestRequest) -> JSONResponse:
    """T-690 (D-472): start one ingest and answer 202 with its run id; ``GET /run/<id>`` follows it (``running``,
    ``done`` with the ingest report, ``refused`` when the site key is missing or changed, ``failed``). The night is
    never timed by the caller (OD-10). A second start while an ingest runs is 409. While a steward's accept
    publishes a held night (T-723) the run is taken and waits for it: its state is ``running`` with the detail
    "waiting for a publish", and it starts when the publish ends."""
    waits = False
    gate = _running  # the lock this run takes is the one it gives back
    if not gate.acquire(blocking=False):
        if not _accepting.is_set():
            busy = next((r["run"] for r in reversed(_runs.values()) if r["state"] == "running"), "")
            raise HTTPException(status_code=409, detail="an ingest is already running", headers={"X-TB-Run": busy})
        waits = True
    try:
        ac, default_kind, default_path = build_config()
        path = req.path or default_path
        if req.source != default_kind and not req.path:
            raise HTTPException(status_code=400, detail="path required when overriding the source type")
        process = run_mode() == "process"
        if process and not waits and runs.running(ac.lake_dir):
            # D-663: an ingest this service did not start (it was started before the service restarted) still runs
            busy = runs.holder(ac.lake_dir)
            raise HTTPException(status_code=409, detail="an ingest is already running", headers={"X-TB-Run": busy})
    except BaseException:
        if not waits:
            gate.release()
        raise
    rid = os.urandom(8).hex()
    state: dict[str, Any] = {"run": rid, "state": "running", "started": _now(), "ended": None,
                             "detail": "waiting for a publish to end" if waits else ""}  # fmt: skip
    _runs[rid] = state

    def work() -> None:
        if waits:  # behind the accept, however long it takes (never timed: OD-10)
            gate.acquire()
            state["detail"] = ""
        if process:  # D-663: the night is a process of its own; this thread starts it and waits for it
            try:
                _run_in_process(state, ac.lake_dir, {
                    "source": req.source, "path": path, "since": req.since,
                    "snapshot": req.snapshot.isoformat() if req.snapshot else None, "load_fhir": req.load_fhir,
                    "rebuild_lake": req.rebuild_lake, "validate": req.validate_,
                })  # fmt: skip
            finally:
                gate.release()
            return
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
            gate.release()

    _spawn(work)
    return JSONResponse(dict(state), status_code=202, headers={"Location": f"/run/{rid}"})


@app.get("/run/{rid}")
def run_state(rid: str) -> dict[str, Any]:
    """The state of one ingest run of this process (404: unknown here, e.g. the adapter restarted)."""
    st = _runs.get(rid)
    if st is None and rid.isalnum():  # D-663: a run of an earlier life of this service is on disk
        with contextlib.suppress(Exception):
            st = runs.read(_lake_dir(), rid)
    if st is None:
        raise HTTPException(status_code=404, detail="unknown run (the adapter may have restarted)")
    return dict(st)


@app.get("/run")
def latest_run() -> dict[str, Any]:
    """The newest ingest run of this process, or ``{"state": "none"}``."""
    if _runs:
        return dict(next(reversed(_runs.values())))
    with contextlib.suppress(Exception):  # D-663: nothing in this life of the service: the newest run on disk
        on_disk = runs.all_runs(_lake_dir())
        if on_disk:
            return dict(on_disk[-1])
    return {"state": "none"}


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
        if run_mode() == "process" and runs.running(ac.lake_dir):  # D-663: an ingest of an earlier life still runs
            raise HTTPException(status_code=409, detail="an ingest or a publish is already running")
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
