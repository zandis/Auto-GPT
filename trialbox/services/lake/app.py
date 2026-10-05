"""lake service: ``/query`` (Arrow IPC), ``/chunks/search``, ``/rebuild`` (SPEC §4.5)."""

from __future__ import annotations

import os
from pathlib import Path

import pyarrow as pa
from embed_service.embedder import Embedder, from_env
from fastapi import HTTPException, Response
from tb_common.http import make_app
from tb_contracts import (
    ChunkHit,
    ChunkSearchRequest,
    ChunkSearchResult,
    LakeQuery,
    RebuildRequest,
    RebuildResult,
)

from lake.sqlguard import SqlRejected
from lake.store import Lake

ARROW_STREAM = "application/vnd.apache.arrow.stream"
_lake: Lake | None = None
_embedder: Embedder | None = None


def lake() -> Lake:
    global _lake
    if _lake is None:
        _lake = Lake(Path(os.environ.get("TB_LAKE_DIR", "/data/lake")), os.environ.get("TB_TZ", "Asia/Taipei"))
    return _lake


def embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = from_env(os.environ.get("TB_LAKE_EMBEDDER", "http"), os.environ.get("EMBED_URL"))
    return _embedder


app = make_app("lake", checks=[lambda: {"snapshot": lake().current() or "none"}])


def to_ipc(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return bytes(sink.getvalue().to_pybytes())


@app.post("/query")
def query(req: LakeQuery) -> Response:
    try:
        table = lake().query(
            req.sql, list(req.params or []), req.snapshot.isoformat() if req.snapshot else None, req.timeout_s
        )
    except SqlRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # duckdb errors -> 422 with the engine message (no data echoed)
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {str(exc)[:500]}") from exc
    return Response(content=to_ipc(table), media_type=ARROW_STREAM)


@app.post("/chunks/search")
def chunks_search(req: ChunkSearchRequest) -> ChunkSearchResult:
    try:
        hits = lake().search(
            req.pid,
            req.query,
            embedder(),
            req.k,
            req.date_from,
            req.date_to,
            req.snapshot.isoformat() if req.snapshot else None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ChunkSearchResult(hits=[ChunkHit(**h) for h in hits])


@app.post("/rebuild")
def rebuild(req: RebuildRequest) -> RebuildResult:
    stats = lake().rebuild(req.snapshot.isoformat(), embedder(), Path(req.ndjson_dir) if req.ndjson_dir else None)
    return RebuildResult(
        snapshot=stats.snapshot,
        tables=stats.tables,
        chunks=stats.chunks,
        embedded_new=stats.embedded_new,
        seconds=stats.seconds,
    )
