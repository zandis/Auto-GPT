"""adapter API.

* ``POST /run`` runs one ingest (called by the orchestrator's 02:00 job).
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
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
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
