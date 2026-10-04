"""orchestrator HTTP service (SPEC §4.8): ``POST /jobs``, ``GET /jobs/{id}``, ``GET /jobs``, cancel; worker pool and
scheduler start with the app."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from lake.client import LakeHttp
from tb_common.audit import AuditLog
from tb_common.config import get_config
from tb_common.http import make_app
from tb_common.objstore import from_config
from tb_contracts import Job, JobCreate

from orchestrator.clients import AdapterHttp, CompilerHttp, MailHttp, ParserHttp
from orchestrator.core import Orchestrator, Rejected, Services
from orchestrator.db import JobDB
from orchestrator.scenarios import registry

_orch: Orchestrator | None = None


def orch() -> Orchestrator:
    global _orch
    if _orch is None:
        cfg = get_config()
        data = Path(os.environ.get("TB_ORCH_DIR", str(Path(cfg.env.data_dir) / "orchestrator")))
        services = Services(
            lake=LakeHttp(cfg.env.lake_url),
            parser=ParserHttp(cfg.env.doc_parser_url),
            compiler=CompilerHttp(cfg.env.compiler_url),
            mail=MailHttp(cfg.env.mail_gateway_url),
            adapter=AdapterHttp(cfg.env.adapter_url),
        )
        _orch = Orchestrator(
            cfg,
            JobDB(data / "jobs.sqlite"),
            from_config(),
            AuditLog(cfg.env.audit_path, cfg.env.tz),
            services,
            registry(),
            cfg.env.rulesets_path,
            data,
            workers=int(os.environ.get("TB_WORKERS", "4")),
        )
    return _orch


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    o = orch()
    o.start()
    sched: Any = None
    if os.environ.get("TB_SCHEDULER", "1") != "0":
        from orchestrator.scheduler import start

        sched = start(o)
    try:
        yield
    finally:
        if sched is not None:
            sched.shutdown(wait=False)
        o.stop()


def _queue() -> dict[str, Any]:
    o = orch()
    return {"queued_or_running": len(o.db.find(state="running")) + len(o.db.find(state="received"))}


app = make_app("orchestrator", checks=[_queue], lifespan=lifespan)


@app.post("/jobs")
def create_job(req: JobCreate) -> Job:
    try:
        return orch().create(req)
    except Rejected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> Job:
    job = orch().db.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    return job


@app.get("/jobs")
def list_jobs(
    state: str | None = None, ruleset: str | None = None, type: str | None = None, limit: int = 50
) -> list[Job]:
    return orch().db.find(state=state, ruleset=ruleset, type_=type, limit=min(limit, 500))


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, by: str) -> Job:
    try:
        return orch().cancel(job_id, by)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such job") from exc
