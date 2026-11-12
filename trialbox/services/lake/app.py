"""lake service: ``/query`` (Arrow IPC), ``/chunks/search``, ``/rebuild`` (SPEC §4.5)."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
from embed_service.embedder import Embedder, from_env
from fastapi import Header, HTTPException, Response
from fastapi.responses import JSONResponse
from tb_common.config import site_tz
from tb_common.http import make_app
from tb_common.phi_guard import site_mrn_regex
from tb_contracts import (
    ChunkHit,
    ChunkSearchRequest,
    ChunkSearchResult,
    LakeQuery,
    RebuildRequest,
)

from lake.sqlguard import SqlRejected
from lake.store import BUSY_HEADER, GENERATION_HEADER, Lake, LakeBusy, RebuildError, split_generation

ARROW_STREAM = "application/vnd.apache.arrow.stream"
_lake: Lake | None = None
_embedder: Embedder | None = None


def lake() -> Lake:
    global _lake
    if _lake is None:
        _lake = Lake(Path(os.environ.get("TB_LAKE_DIR", "/data/lake")), site_tz(), site_mrn_regex())  # T-600
    return _lake


def embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = from_env(os.environ.get("TB_LAKE_EMBEDDER", "http"), os.environ.get("EMBED_URL"))
    return _embedder


def _vec_check() -> dict[str, Any]:
    return vec_health()  # defined below, with the S2b route (D-449)


app = make_app("lake", checks=[lambda: {"snapshot": lake().current() or "none"}, _vec_check], protect_reads=True)


def to_ipc(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return bytes(sink.getvalue().to_pybytes())


def _named(snapshot: date | None, generation: str | None) -> str | None:
    """The snapshot a request reads: its date, or, with the header ``X-TB-Lake-Generation`` (T-724, D-490), that
    generation of its date. The header alone is refused: a generation is of a date."""
    snap = snapshot.isoformat() if snapshot else None
    if not generation:
        return snap
    if snap is None or not generation.isdigit() or int(generation) < 1:
        raise HTTPException(status_code=400, detail=f"{GENERATION_HEADER} is a number, beside the request's snapshot")
    return f"{snap}.g{int(generation)}"


@app.post("/query")
def query(req: LakeQuery, x_tb_lake_generation: str | None = Header(default=None)) -> Response:
    try:
        table = lake().query(req.sql, list(req.params or []), _named(req.snapshot, x_tb_lake_generation), req.timeout_s)
    except SqlRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # duckdb errors -> 422 with the engine message (no data echoed)
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {str(exc)[:500]}") from exc
    return Response(content=to_ipc(table), media_type=ARROW_STREAM)


@app.post("/chunks/search")
def chunks_search(
    req: ChunkSearchRequest, x_tb_lake_generation: str | None = Header(default=None)
) -> ChunkSearchResult:
    try:
        hits = lake().search(
            req.pid,
            req.query,
            embedder(),
            req.k,
            req.date_from,
            req.date_to,
            _named(req.snapshot, x_tb_lake_generation),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ChunkSearchResult(hits=[ChunkHit(**h) for h in hits])


_vec: Any = None
_vec_failed_at: float | None = None
VEC_RETRY_S = 300.0  # a store that would not open is tried again after this long, not on every pair (D-449)
#: answers of /vec/s2b since the service started, for its health line (D-449, review LOW 3)
VEC_COUNTS: dict[str, int] = {"vec_ranked": 0, "vec_fallback": 0}


def vec_store() -> Any:
    """The vector store (schema ``vec`` of ``TB_DB_URL``, this service's role, D-378), opened on first use; None when
    it cannot be opened (no database, no pgvector): S2b then ranks on the fly (D-449). A failed open is remembered for
    :data:`VEC_RETRY_S`, so a run does not reconnect, migrate and log on every pair. The search by patient needs no
    HNSW index, so none is made here (the indexer makes the model's)."""
    global _vec, _vec_failed_at
    import time

    if _vec is None:
        if _vec_failed_at is not None and time.monotonic() - _vec_failed_at < VEC_RETRY_S:
            return None
        try:
            from vec.store import VecStore

            _vec = VecStore()
            _vec_failed_at = None
        except Exception as exc:  # logged by name only: the URL may hold a password
            import logging

            _vec_failed_at = time.monotonic()
            logging.getLogger("lake").warning("vector store unavailable for S2b: %s", type(exc).__name__)
            return None
    return _vec


def vec_health() -> dict[str, Any]:
    """The S2b counts on ``/healthz`` once the store was asked at all (nothing while the flag is off)."""
    return dict(VEC_COUNTS) if any(VEC_COUNTS.values()) else {}


@app.post("/vec/s2b")
def vec_s2b(body: dict[str, Any]) -> dict[str, Any]:
    """T-203b (D-449, flag ``vec.s2b`` on the orchestrator's side): one patient's window notes ranked from the vector
    store on the pinned snapshot, or a fallback answer with its reason."""
    pid, dids, query, snap = body.get("pid"), body.get("dids"), body.get("query"), body.get("snapshot")
    if not isinstance(pid, str) or not isinstance(query, str) or not isinstance(dids, list):
        raise HTTPException(status_code=400, detail="pid, dids and query are required")
    if not all(isinstance(d, str) for d in dids) or not (snap is None or isinstance(snap, str)):
        raise HTTPException(status_code=400, detail="dids are note ids; snapshot is a snapshot id")
    from vec.s2b import UNAVAILABLE, fallback

    try:
        out = lake().vec_s2b(pid, dids, query, embedder(), vec_store(), snap)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # the store went away mid-run: the cascade falls back for this pair
        out = fallback(f"{UNAVAILABLE} ({type(exc).__name__})")
    VEC_COUNTS["vec_ranked" if out.get("state") == "vec" else "vec_fallback"] += 1
    return out


@app.post("/site")
def put_site(body: dict[str, Any]) -> dict[str, Any]:
    """D-135: the site's own inputs (FHIR resources by type from the orchestrator's site set-up); the next rebuild
    joins them to the snapshot. Proposed facts carry their basis tag and never reach a coded table."""
    resources = body.get("resources")
    if not isinstance(resources, dict) or not all(isinstance(v, list) for v in resources.values()):
        raise HTTPException(status_code=400, detail="resources: {type: [resource, ...]}")
    if not all(isinstance(k, str) and k.isalpha() and k[:1].isupper() for k in resources):
        raise HTTPException(status_code=400, detail="resource types are FHIR names")
    return {"counts": lake().put_site(resources)}


@app.post("/holds")
def put_hold(body: dict[str, Any]) -> dict[str, Any]:
    """T-305b (D-403): a running job holds the snapshot it pinned; it is neither rebuilt nor pruned until released."""
    snap, holder = body.get("snapshot"), body.get("holder")
    if not isinstance(snap, str) or not isinstance(holder, str):
        raise HTTPException(status_code=400, detail="snapshot and holder are strings")
    try:
        # T-724 (D-490): with ``pin`` the holder pins a generation (the date's newest, or the one named), which is
        # answered; a rebuild of the date then makes the next generation instead of being refused
        got = lake().hold(snap, holder, pin=body.get("pin") is True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"holder": holder, "snapshot": split_generation(got)[0], "generation": got if got != snap or
            split_generation(got)[1] is not None else None}  # fmt: skip


@app.delete("/holds/{holder}")
def delete_hold(holder: str) -> dict[str, Any]:
    return {"holder": holder, "released": lake().release(holder)}


@app.get("/holds")
def get_holds() -> dict[str, Any]:
    return {"holds": lake().holds()}


@app.get("/generations/{snapshot}")
def get_generations(snapshot: str) -> dict[str, Any]:
    """T-724 (D-490): the generations of a date on the box and the one the date names now (``generation``: None for
    a date built before generations). 404: no such snapshot."""
    try:
        snap = date.fromisoformat(snapshot).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="a snapshot is a date (YYYY-MM-DD)") from exc
    try:
        return {
            "snapshot": snap,
            "generation": lake().generation(snap),
            "generations": lake().generations(snap),
            "site_in_sync": lake().site_in_sync(snap),  # the served generation holds the site's inputs of now
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _spawn(run: Callable[[], None]) -> None:
    """A rebuild job runs in its own thread of this worker; a killed worker leaves its state ``interrupted``."""
    threading.Thread(target=run, name="lake-rebuild", daemon=True).start()


@app.post("/rebuild", status_code=202)
def rebuild(req: RebuildRequest) -> JSONResponse:
    """T-690 (D-472): start a rebuild as a job and answer 202 with its state; ``GET /rebuild/<snapshot>`` follows it.
    What is known at once is answered at once, nothing written: 409 with ``X-TB-Lake-Busy`` when a job holds the
    snapshot or another rebuild of it runs (D-462), 409 when its feed folder is missing (D-271). A refusal found while
    the records are read (no record, a drop, the OMOP store's) is the job's state ``refused``."""
    snap = req.snapshot.isoformat()
    try:
        job = lake().start_rebuild(snap, embedder(), Path(req.ndjson_dir) if req.ndjson_dir else None, spawn=_spawn)
    except LakeBusy as exc:  # D-462: held by a job or already building; nothing written, try again later
        raise HTTPException(status_code=409, detail=str(exc), headers={BUSY_HEADER: exc.reason}) from exc
    except RebuildError as exc:  # D-271: a missing feed is refused; CURRENT stays
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        from omop.schema import OmopError

        if isinstance(exc, OmopError):  # D-271: the OMOP store refused the batch (a mass tombstone, an older batch)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise
    return JSONResponse(job, status_code=202, headers={"Location": f"/rebuild/{snap}"})


@app.get("/rebuild/{snapshot}")
def rebuild_state(snapshot: str) -> dict[str, Any]:
    """The state of the snapshot's last rebuild job (``running``, ``done`` with its counts, ``busy``, ``refused``,
    ``failed``, ``interrupted``, or ``none``), read by any worker (T-690, D-472)."""
    try:
        snap = date.fromisoformat(snapshot).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="a snapshot is a date (YYYY-MM-DD)") from exc
    out: dict[str, Any] = lake().rebuild_state(snap)
    return out
