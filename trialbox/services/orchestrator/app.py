"""orchestrator HTTP service (SPEC §4.8): ``POST /jobs``, ``GET /jobs/{id}``, ``GET /jobs``, cancel; worker pool and
scheduler start with the app."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Response
from lake.client import LakeHttp
from tb_common.audit import AuditLog
from tb_common.config import get_config
from tb_common.fhir import FhirEvaluator
from tb_common.http import make_app
from tb_common.llm import LlmClient
from tb_common.objstore import from_config
from tb_contracts import Job, JobCreate, RegistryEntry, RegistryEvent, RegistryPromote, RegistrySummary, RegistryUpdate

from orchestrator.candidates import CandidateRegistry, RegistryError
from orchestrator.clients import AdapterHttp, CompilerHttp, MailHttp, ParserHttp
from orchestrator.core import Orchestrator, Rejected, Services
from orchestrator.db import JobDB
from orchestrator.scenarios import registry

_orch: Orchestrator | None = None


def _pinned_today() -> Callable[[], date] | None:
    """``TB_TODAY=YYYY-MM-DD`` pins the orchestrator's clock. Test stack only (docker-compose.test.yml): the synthetic
    fixtures are generated relative to a fixed reference date, so date-windowed scenarios (NAV's 14-day appointment
    window) must not drift with the wall clock."""
    raw = os.environ.get("TB_TODAY", "").strip()
    if not raw:
        return None
    pinned = date.fromisoformat(raw)
    return lambda: pinned


def verifier_client(audit: AuditLog) -> LlmClient | None:
    """The second model for independent checks (the consent explainer): through the gateway when
    ``TB_GATEWAY_VERIFIER_MODEL`` names the V build (``v-verifier``; ``TB_GATEWAY_VERIFIER_URL`` defaults to
    ``TB_GATEWAY_URL``), else straight to ``LLM_VERIFIER_BASE_URL`` / ``LLM_VERIFIER_MODEL``; None when neither is
    set, and the step then says its output is unverified."""
    cfg = get_config()
    model = os.environ.get("TB_GATEWAY_VERIFIER_MODEL", "").strip()
    url = (os.environ.get("TB_GATEWAY_VERIFIER_URL") or os.environ.get("TB_GATEWAY_URL") or "").strip()
    if model and url:
        from tb_llm import GatewayClient

        gw = GatewayClient(url, cfg.env.service_name, model=model)
        return LlmClient(cfg.env.llm_base_url, model, service_name=cfg.env.service_name, audit=audit, gateway=gw)
    base = os.environ.get("LLM_VERIFIER_BASE_URL", "").strip()
    if base:
        model = os.environ.get("LLM_VERIFIER_MODEL", "").strip() or cfg.env.llm_model
        return LlmClient(base, model, service_name=cfg.env.service_name, audit=audit)
    return None


def orch() -> Orchestrator:
    global _orch
    if _orch is None:
        cfg = get_config()
        data = Path(os.environ.get("TB_ORCH_DIR", str(Path(cfg.env.data_dir) / "orchestrator")))
        audit = AuditLog(cfg.env.audit_path, cfg.env.tz)
        services = Services(
            lake=LakeHttp(cfg.env.lake_url),
            parser=ParserHttp(cfg.env.doc_parser_url),
            compiler=CompilerHttp(cfg.env.compiler_url),
            mail=MailHttp(cfg.env.mail_gateway_url),
            adapter=AdapterHttp(cfg.env.adapter_url),
            fhir=FhirEvaluator(cfg.env.fhir_base_url, workers=int(os.environ.get("TB_FHIR_WORKERS", "8"))),
            llm=LlmClient.from_config(audit),
            verifier=verifier_client(audit),
        )
        _orch = Orchestrator(
            cfg,
            JobDB(data / "jobs.sqlite"),
            from_config(),
            audit,
            services,
            registry(),
            cfg.env.rulesets_path,
            data,
            workers=int(os.environ.get("TB_WORKERS", "4")),
            today=_pinned_today(),
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


# ---------------------------------------------------------------------------------------- candidate registry (D-92)
def registry_of(o: Orchestrator) -> CandidateRegistry:
    return CandidateRegistry(o.db, o.audit, Path(o.cfg.env.secrets_dir), o.cfg.settings.mrn_regex)


def _now(o: Orchestrator) -> datetime:
    return datetime.now(ZoneInfo(o.cfg.settings.site.tz))


@app.get("/registry")
def registry_summaries() -> list[RegistrySummary]:
    return registry_of(orch()).summaries()


@app.get("/registry/{ruleset}")
def registry_rows(ruleset: str) -> list[RegistryEntry]:
    try:
        return registry_of(orch()).rows(ruleset)
    except RegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/registry/{ruleset}/events")
def registry_events(ruleset: str, pid: str | None = None) -> list[RegistryEvent]:
    try:
        return registry_of(orch()).events(ruleset, pid)
    except RegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/registry/{ruleset}")
def registry_update(ruleset: str, upd: RegistryUpdate) -> RegistryEntry:
    o = orch()
    try:
        return registry_of(o).update(ruleset, upd, _now(o))
    except RegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/registry/{ruleset}/promote")
def registry_promote(ruleset: str, req: RegistryPromote) -> dict[str, int]:
    o = orch()
    try:
        return {"added": registry_of(o).promote(ruleset, req, _now(o))}
    except RegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/registry/{ruleset}/export.xlsx")
def registry_export(ruleset: str) -> Response:
    o = orch()
    try:
        data = registry_of(o).export_xlsx(ruleset, o.cfg.settings.site.id)
    except RegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="screening_log_{ruleset.upper()}.xlsx"'},
    )
