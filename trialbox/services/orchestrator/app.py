"""orchestrator HTTP service (SPEC §4.8): ``POST /jobs``, ``GET /jobs/{id}``, ``GET /jobs``, cancel; worker pool and
scheduler start with the app."""

from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Header, HTTPException, Response
from lake.client import LakeHttp
from pydantic import BaseModel, Field
from tb_common.audit import AuditLog
from tb_common.config import get_config, tb_env
from tb_common.fhir import FhirEvaluator
from tb_common.http import make_app
from tb_common.llm import LlmClient
from tb_common.objstore import from_config
from tb_common.service_auth import actor_of
from tb_contracts import Job, JobCreate, RegistryEntry, RegistryEvent, RegistryPromote, RegistrySummary, RegistryUpdate

from orchestrator.candidates import CandidateRegistry, RegistryError
from orchestrator.clients import AdapterHttp, CompilerHttp, MailHttp, ParserHttp
from orchestrator.core import Orchestrator, Rejected, Services
from orchestrator.datacore_api import router as datacore_router
from orchestrator.db import JobDB
from orchestrator.scenarios import registry
from orchestrator.study_api import StudyService
from orchestrator.study_api import router as study_router
from orchestrator.studystore import StudyStore

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
            JobDB(),  # TB_DB_URL, schema orch
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
    from orchestrator import canary_gate

    canary_gate.startup(o)  # D-117: the pair canary at start, in the background; it gates note exclusions
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


# D-114: every changing call carries the box's service token; D-130 (plan v4 F4): every read too (jobs and their
# outputs, the registry, studies, the data core), since they are patient level. /healthz stays open.
app = make_app("orchestrator", checks=[_queue], lifespan=lifespan, protect_reads=True)


def _actor(header: str | None, fallback: str | None) -> str:
    who = actor_of(header, fallback)
    if who is None:
        raise HTTPException(status_code=400, detail="no signed-in user (X-TB-Actor) on this call")
    return who


@app.get("/models")
def models() -> dict[str, Any]:
    """What judges notes on this box and whether a note answer may exclude a patient (D-95, D-97). Aggregate
    configuration only; the console shows it on the Overview so a site sees single-model mode before a run."""
    from orchestrator.scenarios.evaluate import NoteJudge
    from orchestrator.scenarios.screen import judging_info

    o = orch()
    s = o.services
    mode = os.environ.get("TB_SCREEN_JUDGE", "agreement").strip().lower()
    verifier = s.verifier if mode != "single" else None
    judge = NoteJudge(s.lake, s.llm, "judge", job_id="", verifier=verifier) if s.llm is not None else None
    from orchestrator import canary_gate
    from orchestrator.scenarios.screen_cascade import pipeline

    canary_gate.GATE.configure(o.data_dir)
    return {
        "engine": "sql",  # the only runtime engine (owner decision 3)
        "pipeline": pipeline(),
        "screen_judge": mode,
        "gateway": bool(os.environ.get("TB_GATEWAY_URL", "").strip()),
        **judging_info(judge),
        "canary": canary_gate.status(),
    }


@app.post("/models/canary")
def models_canary() -> dict[str, Any]:
    """Run the 54-case pair canary now (the admin Models tile's "Run now"); it takes a few minutes on the card and
    runs in the background. Changing call: needs the service token (D-114)."""
    import threading

    from orchestrator import canary_gate

    o = orch()
    if o.services.llm is None:
        raise HTTPException(status_code=409, detail="no model configured on this box")
    if canary_gate.GATE.running:
        return {"started": False, "running": True}
    threading.Thread(target=canary_gate.run_canary, args=(o,), name="canary-run-now", daemon=True).start()
    return {"started": True, "running": True}


@app.get("/rulesets/{ruleset}")
def ruleset_detail(ruleset: str) -> dict[str, Any]:
    """The approved manifest's provenance (version, approval record, population, kind): what the console prints in
    a sponsor pack README (D-101). Aggregate: no criteria text, no patients."""
    from tb_common.ruleset import RulesetNotApproved, load_approved

    rid = ruleset.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,31}", rid):
        raise HTTPException(status_code=404, detail="no such ruleset")
    try:
        rs = load_approved(orch().rulesets_dir, rid)
    except (RulesetNotApproved, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    m = rs.manifest
    return {
        "ruleset": rs.id,
        "version": rs.version,
        "kind": str(m.kind or ""),
        "title": m.title or "",
        "nct_id": m.nct_id or "",
        "population": m.population.model_dump(exclude_none=True) if m.population else None,
        "review": m.review.model_dump(exclude_none=True) if m.review else None,
        "criteria": len([c for c in rs.criteria if c.kind in ("inclusion", "exclusion")]),
    }


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


class RevealRequest(BaseModel):
    pid: str = Field(min_length=8, max_length=64)
    by: str | None = Field(default=None, max_length=200)  # DEV/TEST without a token only; else X-TB-Actor


class RevealLimit:
    """At most ``TB_REVEAL_MAX_PER_HOUR`` (default 60) chart numbers per person per rolling hour, per process."""

    def __init__(self) -> None:
        self._seen: dict[str, list[float]] = {}

    def allow(self, who: str) -> bool:
        import time

        cap = int(os.environ.get("TB_REVEAL_MAX_PER_HOUR", "60"))
        t = time.monotonic()
        recent = [x for x in self._seen.get(who, []) if t - x < 3600]
        if len(recent) >= cap:
            self._seen[who] = recent
            return False
        self._seen[who] = [*recent, t]
        return True


REVEALS = RevealLimit()


def listed_pids(o: Any, job: Any) -> set[str]:
    """The pseudonyms a finished screening job listed (its ``candidate_list_*.json`` or other ``*.json`` lists)."""
    out: set[str] = set()
    for f in job.outputs or []:
        if not f.filename.endswith(".json"):
            continue
        try:
            doc = json.loads(o.store.get(f.minio_key))
        except (KeyError, OSError, ValueError):
            continue
        rows = doc.get("rows") if isinstance(doc, dict) else None
        for r in rows or []:
            if isinstance(r, dict) and r.get("pid"):
                out.add(str(r["pid"]))
    return out


@app.post("/jobs/{job_id}/reveal")
def reveal(
    job_id: str, req: RevealRequest, x_tb_actor: str | None = Header(default=None, alias="X-TB-Actor")
) -> dict[str, Any]:
    """Chart number of one listed pseudonym for a coordinator on the console (D-99). On-prem only: the pid map
    never leaves the box, every reveal is one audit event with the actor, and nothing is stored."""
    from orchestrator.scenarios.screen import resolve_mrns

    who = _actor(x_tb_actor, req.by)
    o = orch()
    job = o.db.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    if job.type not in ("SCREEN", "MICROBATCH", "NAV") or job.state != "done":
        raise HTTPException(status_code=409, detail="chart numbers are revealed for finished screening jobs only")
    # security review 2026-11-08 (F-03): only a patient this job listed, and at a bounded rate per person
    listed = listed_pids(o, job)
    if req.pid not in listed:
        o.audit.append("screen.reveal_refused", job_id=job_id, ruleset=job.ruleset, actor=who,
                       detail={"pid": req.pid, "reason": "not on this job's list"})  # fmt: skip
        raise HTTPException(status_code=403, detail="this patient is not on this job's list")
    if not REVEALS.allow(who):
        o.audit.append("screen.reveal_refused", job_id=job_id, ruleset=job.ruleset, actor=who,
                       detail={"pid": req.pid, "reason": "rate limit"})  # fmt: skip
        raise HTTPException(status_code=429, detail="too many chart numbers revealed in the last hour")
    found = resolve_mrns(Path(o.cfg.env.secrets_dir), [req.pid], o.db.url)
    o.audit.append(
        "screen.reveal",
        job_id=job_id,
        ruleset=job.ruleset,
        actor=who,
        detail={"pid": req.pid, "found": req.pid in found},
    )
    if req.pid not in found:
        raise HTTPException(status_code=404, detail="this pseudonym is not in the box's pid map")
    return {"pid": req.pid, "mrn": found[req.pid]}


class NoticeRequest(BaseModel):
    """A console notice (D-108): N1 the investigator's pre-clinic list, N2 the coordinator's digest. Pseudonyms and
    counts only (FR-NOTIF-01/02), so the mail is ``aggregate`` and goes to internal addresses only."""

    kind: Literal["N1", "N2"]
    to: list[str] = Field(min_length=1, max_length=5)
    subject: str = Field(min_length=1, max_length=200)
    body_md: str = Field(min_length=1, max_length=20_000)
    by: str | None = Field(default=None, max_length=200)  # DEV/TEST without a token only; else X-TB-Actor


@app.post("/notices")
def notice(req: NoticeRequest, x_tb_actor: str | None = Header(default=None, alias="X-TB-Actor")) -> dict[str, Any]:
    from tb_common.routing import is_internal
    from tb_contracts import SendRequest

    who = _actor(x_tb_actor, req.by)
    o = orch()
    external = [r for r in req.to if not is_internal(r, o.cfg.settings.internal_domains)]
    if external:
        raise HTTPException(status_code=400, detail=f"notices go to hospital addresses only, not {external[0]}")
    from orchestrator.core import send_key

    day = o._now().date().isoformat()
    # D-127 (F-02): one notice of a kind per recipients, subject and day, even when the console's timer retries
    key = send_key(f"notice:{day}", req.kind, list(req.to), req.subject, [])
    res = o.services.mail.send(
        SendRequest(
            job_id=None, to=req.to, subject=req.subject, body_md=req.body_md, tag="aggregate", idempotency_key=key
        )
    )
    o.audit.append(
        "notice.sent",
        actor=who,
        detail={"kind": req.kind, "to": req.to, "subject": req.subject, "message_id": res.message_id},
    )
    return {"message_id": res.message_id}


@app.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str, by: str | None = None, x_tb_actor: str | None = Header(default=None, alias="X-TB-Actor")
) -> Job:
    who = _actor(x_tb_actor, by)
    try:
        return orch().cancel(job_id, who)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such job") from exc


# ---------------------------------------------------------------------------------------- candidate registry (D-92)
def registry_of(o: Orchestrator) -> CandidateRegistry:
    return CandidateRegistry(o.db, o.audit, Path(o.cfg.env.secrets_dir), o.cfg.settings.mrn_regex)


def _now(o: Orchestrator) -> datetime:
    return datetime.now(ZoneInfo(o.cfg.settings.site.tz))


# ---------------------------------------------------------------------------- S-28 study store, REDCap (D-109)
_studies: dict[str, StudyStore] = {}


def study_service_of(o: Orchestrator) -> StudyService:
    # one store per orchestrator, in schema "study" of the orchestrator's trial database (keyed by study inside)
    key = f"{o.db.url}|{o.data_dir}"
    if key not in _studies:
        _studies[key] = StudyStore(Path(o.cfg.env.secrets_dir), o.db.url)
        if (tb_env(o.cfg.env) if o.cfg.env.extra.get("TB_ENV") else os.environ.get("TB_ENV", "").upper()) in (
            "DEV",
            "TEST",
        ):
            from rc_sim.app import register_inproc

            register_inproc(replace=False)  # FR-RC-17a: inproc://rc-sim only in demo and test boxes
    return StudyService(_studies[key], registry_of(o), o.audit, lambda: _now(o))


app.include_router(study_router(lambda: study_service_of(orch())))

# ---------------------------------------------------------------------------- TrialBox's own data core (D-123)
_cores: dict[str, Any] = {}


def data_service_of(o: Orchestrator) -> Any:
    from datacore.store import DataCore

    from orchestrator.datacore_api import DataService

    key = o.db.url or str(o.data_dir)  # D-126: one data core per box, in the trial database
    if key not in _cores:
        _cores[key] = DataCore(o.db.url)
    studies = study_service_of(o)

    def site_key() -> bytes:
        return (Path(o.cfg.env.secrets_dir) / "site_hmac.key").read_bytes()

    return DataService(_cores[key], o.audit, lambda: _now(o), studies.client, site_key)


app.include_router(datacore_router(lambda: data_service_of(orch())))


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
