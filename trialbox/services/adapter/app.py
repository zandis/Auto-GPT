"""adapter trigger API: ``POST /run`` runs one ingest (called by the orchestrator's 02:00 job)."""

from __future__ import annotations

import os
import threading

from fastapi import HTTPException
from tb_common.http import make_app
from tb_contracts import IngestReport, IngestRequest

from adapter.cli import build_config
from adapter.pipeline import run_ingest

app = make_app("adapter")
_running = threading.Lock()


@app.post("/run")
def run(req: IngestRequest) -> IngestReport:
    if not _running.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="an ingest is already running")
    try:
        ac, default_kind, default_path = build_config()
        path = req.path or default_path
        if req.source != default_kind and not req.path:
            raise HTTPException(status_code=400, detail="path required when overriding the source type")
        return run_ingest(
            ac,
            req.source,
            path or os.environ.get("TB_SOURCE_PATH", ""),
            since=req.since,
            snapshot=req.snapshot.isoformat() if req.snapshot else None,
            load_fhir=req.load_fhir,
            rebuild_lake=req.rebuild_lake,
            validate=req.validate_,
        )
    finally:
        _running.release()
