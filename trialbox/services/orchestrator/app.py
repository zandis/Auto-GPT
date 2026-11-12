"""orchestrator HTTP service (SPEC §4.8): ``POST /jobs``, ``GET /jobs/{id}``, ``GET /jobs``, cancel; worker pool and
scheduler start with the app."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, Response
from lake.client import LakeHttp
from pydantic import BaseModel, ConfigDict, Field
from tb_common.audit import AuditLog
from tb_common.audit_writer import open_audit
from tb_common.authz import BREAK_GLASS_ROLE, permit
from tb_common.config import get_config, tb_env
from tb_common.crypto import load_key
from tb_common.fhir import FhirEvaluator
from tb_common.http import make_app
from tb_common.llm import LlmClient
from tb_common.objstore import from_config
from tb_common.ruleset import seed_working_copy
from tb_common.service_auth import (
    ACTOR_HEADER,
    ASSERTION_HEADER,
    ROLE_HEADER,
    SCOPE_HEADER,
    Actor,
    ActorError,
    in_scope,
    verify_actor,
)
from tb_contracts import Job, JobCreate, RegistryEntry, RegistryEvent, RegistryPromote, RegistrySummary, RegistryUpdate

from orchestrator.callers import Gate
from orchestrator.callers import load as load_callers
from orchestrator.candidates import CandidateRegistry, RegistryError
from orchestrator.clients import AdapterHttp, CompilerHttp, MailHttp, ParserHttp
from orchestrator.core import NotRetryable, Orchestrator, Rejected, Services
from orchestrator.datacore_api import router as datacore_router
from orchestrator.db import JobDB
from orchestrator.edc_api import router as edc_router
from orchestrator.lifecycle_api import router as lifecycle_router
from orchestrator.scenarios import registry
from orchestrator.setup_api import router as setup_router
from orchestrator.sponsor_api import router as sponsor_router
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
        audit = open_audit(cfg.env.audit_path, cfg.env.tz)
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
        seed_working_copy(cfg.env.rulesets_path)  # D-469: a first copy of the shipped rulesets; never the checkout
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
    if sched is not None and o.cfg.env.site_publish_batch_seconds > 0:  # T-305b (D-403): the batch's own tick
        sched.add_job(lambda: _flush_main(setup_of(o)), "interval", seconds=60, id="site-publish-batch")
    # D-441: the opt-out worker ticks even when nights are on demand; in PRODUCTION also without the scheduler (and it
    # refuses to be off there)
    from datacore.optout_worker import start as optout_start
    from tb_common.config import tb_env

    production = tb_env(o.cfg.env) == "PRODUCTION"
    optout_sched: Any = None
    if production or os.environ.get("TB_SCHEDULER", "1") != "0":
        optout_sched = optout_start(o, production=production)
    try:
        yield
    finally:
        if optout_sched is not None:
            optout_sched.shutdown(wait=False)
        if sched is not None:
            sched.shutdown(wait=False)
        o.stop()


def _queue() -> dict[str, Any]:
    """Reads the job store, so a dead database is a 503 (a lost connection is reopened, D-142, review A-02)."""
    o = orch()
    return {"queued_or_running": len(o.db.find(state="running")) + len(o.db.find(state="received"))}


# D-114: every changing call carries the box's service token; D-130 (plan v4 F4): every read too (jobs and their
# outputs, the registry, studies, the data core), since they are patient level. /healthz stays open.
# T-713 (D-464): which verified service reaches which route is one table (route_callers.yaml), enforced right after the
# token check; a refusal is 403 with a named reason and audited with the verified service.
CALLER_GATE = Gate(load_callers(), lambda: orch().audit)
app = make_app("orchestrator", checks=[_queue], lifespan=lifespan, protect_reads=True, route_gate=CALLER_GATE)


def _claim(request: Request, fallback: str | None = None) -> Actor:
    """The signed-in user behind a call (S-09, D-143): ``X-TB-Actor`` with the console's signed, short-lived
    assertion, verified here; a token holder that cannot sign (the mail gateway, anyone with a stolen token) cannot
    name a user. No user named: 400; a user named without a valid assertion: 403, audited."""
    try:
        return verify_actor(
            request.headers.get(ACTOR_HEADER),
            request.headers.get(ASSERTION_HEADER),
            fallback,
            role=request.headers.get(ROLE_HEADER),
            scope=request.headers.get(SCOPE_HEADER),
        )
    except ActorError as exc:
        if "no signed-in user" in str(exc):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        caller = getattr(request.state, "tb_caller", None) or "-"
        orch().audit.append("actor.refused", actor=f"service:{caller}",
                            detail={"path": request.url.path[:80], "reason": str(exc)[:120]})  # fmt: skip
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _limit_key(request: Request, who: Actor) -> str:
    """The rate limit is per calling service and verified person (S-09): renaming no longer resets it."""
    return f"{getattr(request.state, 'tb_caller', None) or '-'}|{who.name}"


def _service_key(request: Request) -> str:
    """T-103 (D-438): the calling service as a whole, so a token holder who signs a new name per call is capped too."""
    return f"{getattr(request.state, 'tb_caller', None) or '-'}|*"


def _over_cap(o: Any, request: Request, claim: Actor, person: Any, service: Any) -> str:
    """Take one use of the calling service's total cap, then of the person's; the reason of a refusal, or ""."""
    now = o._now()
    if not service.allow(_service_key(request), o.db, now):
        return "service rate limit"
    if not person.allow(_limit_key(request, claim), o.db, now):
        return "rate limit"
    return ""


def id_authority(role: str) -> bool:
    """T-103 (D-438): may a signed role receive identifiers? The ``id.reveal`` row of the permission matrix (the same
    row as ``console.auth.User.can_reveal``, D-143, D-280: never the administrator), or the break-glass rule: the
    console signs a reveal under an open grant with ``BREAK_GLASS_ROLE`` and holds the grant, its reason and its
    60-minute end (D-280, D-430). No role list of its own."""
    return role == BREAK_GLASS_ROLE or permit(role, "id.reveal").allowed


def _id_authority(o: Any, claim: Actor, rid: str | None, event: str, job_id: str | None = None,
                  pid: str | None = None, whole_list: bool = False) -> None:  # fmt: skip
    """D-273 (PV-5, PV-15): a chart number goes out only to a person whose signed role has identifier authority and
    whose signed study scope covers the study. A verified assertion must carry both; on a DEV/TEST box without a
    token, a role or scope that is sent is checked all the same. A refusal is one audit event. T-103 (D-438): a whole
    list (``whole_list``, the registry export) never goes to ``BREAK_GLASS_ROLE``: a grant covers one patient or one
    job."""
    why = ""
    if (claim.verified or claim.role) and not id_authority(claim.role):
        why = "role"
    elif whole_list and claim.role == BREAK_GLASS_ROLE:
        why = "break-glass covers one patient or one job"
    elif (claim.verified or claim.scope) and not in_scope(claim.scope, rid):
        why = "study scope"
    if why:
        detail: dict[str, Any] = {"reason": why, "role": claim.role}
        if pid:
            detail["pid"] = pid
        o.audit.append(event, job_id=job_id, ruleset=rid, actor=claim.name, detail=detail)
        raise HTTPException(status_code=403, detail=f"chart numbers are refused: {why}")


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
    from datacore.optout_worker import status as optout_status

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
        "optout_worker": optout_status(),  # D-441: the health line turns red on a stale or failed tick
    }


@app.get("/metrics")
def metrics_route() -> Response:
    """T-209a (D-379): the canary half of the box's health in the Prometheus text format, behind the service token
    (reads are protected here, D-130); the console's ``/metrics`` has the whole health. Aggregate only."""
    from datetime import UTC, datetime

    from tb_common import metrics

    from orchestrator import canary_gate

    canary_gate.GATE.configure(orch().data_dir)
    now = datetime.now(UTC)
    health = metrics.Health(now, (metrics.check_canary(canary_gate.status()),))
    return Response(metrics.prometheus(health, "orchestrator"), media_type="text/plain; version=0.0.4; charset=utf-8")


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
def create_job(req: JobCreate, request: Request) -> Job:
    """A new job. From the console (D-146, review J-01) the call names the signed-in person and their role in a signed
    assertion, and the role decides; from the mail gateway (no person named) the sender's mailbox decides. T-713
    (D-464): an internal principal (``scheduler``, ``system``) is never accepted from HTTP, and the mail gateway starts
    only the mail commands."""
    from tb_common.authz import norm

    caller = getattr(request.state, "tb_caller", None)
    why = CALLER_GATE.job_start(caller, str(req.type), norm(req.requested_by), req.message_id)
    if why is not None:
        raise CALLER_GATE.refuse(caller, "POST /jobs", why)
    role, by = "", ""
    if request.headers.get(ACTOR_HEADER) and request.headers.get(ROLE_HEADER):
        who = _claim(request)
        role, by = who.role, who.name
    try:
        job = orch().create(req, role=role, by=by)
    except Rejected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    # a known job_id answers with the existing job before any check of the request (idempotency): the caller must be
    # allowed to read it, or a POST would read what GET refuses
    why = CALLER_GATE.job_read(caller, job.message_id)
    if why is not None:
        raise CALLER_GATE.refuse(caller, "POST /jobs", why)
    return job


@app.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> Job:
    job = orch().db.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    caller = getattr(request.state, "tb_caller", None)
    why = CALLER_GATE.job_read(
        caller, job.message_id
    )  # T-713 (D-464): the mail gateway reads the jobs that came by mail
    if why is not None:
        raise CALLER_GATE.refuse(caller, "GET /jobs/{job_id}", why)
    return job


@app.get("/jobs")
def list_jobs(
    state: str | None = None, ruleset: str | None = None, type: str | None = None, limit: int = 50
) -> list[Job]:
    return orch().db.find(state=state, ruleset=ruleset, type_=type, limit=min(limit, 500))


class RevealRequest(BaseModel):
    pid: str = Field(min_length=8, max_length=64)
    # T-103 (D-438): what the console's one reveal path was asked for, kept in this side's audit record
    purpose: str = Field(default="", max_length=32, pattern=r"^([a-z][a-z0-9_]{1,31})?$")
    reason: str = Field(default="", max_length=20, pattern=r"^[a-z ]*$")
    by: str | None = Field(default=None, max_length=200)  # DEV/TEST without a token only; else X-TB-Actor


class RevealLimit:
    """At most ``TB_REVEAL_MAX_PER_HOUR`` (default 60) chart numbers per person per rolling hour; the same with another
    variable and default for exports (S-09). T-103 (D-438): counted in the store (``orch.id_limits``), not in process
    memory, so a restart or a second worker does not reset it."""

    def __init__(self, env: str = "TB_REVEAL_MAX_PER_HOUR", default: int = 60, kind: str = "") -> None:
        self.env, self.default = env, default
        self.kind = kind or env.removeprefix("TB_").removesuffix("_MAX_PER_HOUR").lower()  # ``reveal``, ``export``

    def allow(self, who: str, db: Any, at: datetime) -> bool:
        cap = int(os.environ.get(self.env, str(self.default)))
        return bool(db.take_limit(self.kind, who, int(at.timestamp() * 1000), 3_600_000, cap))


REVEALS = RevealLimit()


EXPORTS = RevealLimit("TB_EXPORT_MAX_PER_HOUR", 10)  # screening-log exports with chart numbers (S-09)
# T-103 (D-438): the calling service's total across every name it signs
REVEALS_SERVICE = RevealLimit("TB_REVEAL_MAX_PER_HOUR_PER_SERVICE", 600, "reveal_service")
EXPORTS_SERVICE = RevealLimit("TB_EXPORT_MAX_PER_HOUR_PER_SERVICE", 60, "export_service")


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
def reveal(job_id: str, req: RevealRequest, request: Request) -> dict[str, Any]:
    """Chart number of one listed pseudonym for a person with identifier authority on the console (D-99, D-143).
    On-prem only: the pid map never leaves the box, every reveal is one audit event with the verified actor and
    the console session, and nothing is stored."""
    from orchestrator.scenarios.screen import resolve_mrns

    claim = _claim(request, req.by)
    who = claim.name
    o = orch()
    job = o.db.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no such job")
    # D-273 (PV-15): screening lists only; a NAV job's list is not a candidate list and reveals nothing
    if job.type not in ("SCREEN", "MICROBATCH") or job.state != "done":
        raise HTTPException(status_code=409, detail="chart numbers are revealed for finished screening jobs only")
    _id_authority(o, claim, job.ruleset, "screen.reveal_refused", job_id=job_id, pid=req.pid)
    # security review 2026-11-08 (F-03): only a patient this job listed, and at a bounded rate per person
    listed = listed_pids(o, job)
    if req.pid not in listed:
        o.audit.append("screen.reveal_refused", job_id=job_id, ruleset=job.ruleset, actor=who,
                       detail={"pid": req.pid, "reason": "not on this job's list"})  # fmt: skip
        raise HTTPException(status_code=403, detail="this patient is not on this job's list")
    # D-273 (PV-4): never the chart number of a patient on the opt-out register now, whatever the job's age
    from tb_common.optout import opted_out

    if req.pid in opted_out():
        o.audit.append("screen.reveal_refused", job_id=job_id, ruleset=job.ruleset, actor=who,
                       detail={"pid": req.pid, "reason": "opted out"})  # fmt: skip
        raise HTTPException(status_code=403, detail="this patient opted out")
    if over := _over_cap(o, request, claim, REVEALS, REVEALS_SERVICE):
        o.audit.append("screen.reveal_refused", job_id=job_id, ruleset=job.ruleset, actor=who,
                       detail={"pid": req.pid, "reason": over})  # fmt: skip
        raise HTTPException(status_code=429, detail="too many chart numbers revealed in the last hour")
    found = resolve_mrns(Path(o.cfg.env.secrets_dir), [req.pid], o.db.url)
    o.audit.append(
        "screen.reveal",
        job_id=job_id,
        ruleset=job.ruleset,
        actor=who,
        detail={
            "pid": req.pid,
            "found": req.pid in found,
            "session": claim.session,
            "verified": claim.verified,
            "role": claim.role,
            **({"purpose": req.purpose} if req.purpose else {}),
            **({"reason": req.reason} if req.reason else {}),
        },
    )
    if req.pid not in found:
        raise HTTPException(status_code=404, detail="this pseudonym is not in the box's pid map")
    return {"pid": req.pid, "mrn": found[req.pid]}


class NoticeRequest(BaseModel):
    """A console notice (D-108): N1 the investigator's pre-clinic list, N2 the coordinator's digest. Pseudonyms and
    counts only (FR-NOTIF-01/02), so the mail is ``aggregate`` and goes to internal addresses only."""

    kind: Literal["N1", "N2", "BG", "HEALTH"]  # D-280: BG, a break-glass grant; T-209a: HEALTH, the daily health mail
    to: list[str] = Field(min_length=1, max_length=5)
    subject: str = Field(min_length=1, max_length=200)
    body_md: str = Field(min_length=1, max_length=20_000)
    by: str | None = Field(default=None, max_length=200)  # DEV/TEST without a token only; else X-TB-Actor


@app.post("/notices")
def notice(req: NoticeRequest, request: Request) -> dict[str, Any]:
    from tb_common.routing import is_internal
    from tb_contracts import SendRequest

    who = _claim(request, req.by).name
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


class RetryScheduled(BaseModel):
    """``POST /jobs/{job_id}/retry`` body (T-746, D-474): the administrator's reply mailbox, nothing else. The type,
    study, options and inputs are the failed job's own; a field that would change them is refused (422)."""

    model_config = ConfigDict(extra="forbid")
    reply_to: str


@app.post("/jobs/{job_id}/retry")
def retry_scheduled_job(job_id: str, body: RetryScheduled, request: Request) -> Job:
    """The administrator runs a failed job of the box's own scheduler again (``job.retry_scheduled``, D-474). The
    signed person and role decide (the console's assertion; the D-464 gate admits the console only); the orchestrator
    copies the failed job. 403: the role may not; 404: no such job; 409: not failed, not a scheduler job, or a job of
    the same type and study is queued or running."""
    if not (request.headers.get(ACTOR_HEADER) and request.headers.get(ROLE_HEADER)):
        raise HTTPException(status_code=403, detail="a retry names the signed-in administrator and role")
    who = _claim(request)
    try:
        return orch().retry_scheduled(job_id, by=who.name, role=who.role, reply_to=body.reply_to)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such job") from exc
    except Rejected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NotRetryable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request, by: str | None = None) -> Job:
    who = _claim(request, by).name
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
    return StudyService(_studies[key], registry_of(o), o.audit, lambda: _now(o), core_of(o))


app.include_router(study_router(lambda: study_service_of(orch())))

# ---------------------------------------------------------------------------- TrialBox's own data core (D-123)
_cores: dict[str, Any] = {}


def core_of(o: Orchestrator) -> Any:
    from datacore.store import DataCore

    key = o.db.url or str(o.data_dir)  # D-126: one data core per box, in the trial database
    if key not in _cores:
        _cores[key] = DataCore(o.db.url)
    return _cores[key]


def data_service_of(o: Orchestrator) -> Any:
    from orchestrator.datacore_api import DataService

    core = core_of(o)
    studies = study_service_of(o)

    def site_key() -> bytes:
        return load_key(Path(o.cfg.env.secrets_dir) / "site_hmac.key")  # plain or under the KEK (T-210b)

    return DataService(core, o.audit, lambda: _now(o), studies.client, site_key, registry_of(o))


app.include_router(datacore_router(lambda: data_service_of(orch())))
app.include_router(lifecycle_router(lambda: data_service_of(orch())))  # TB-PLAN-04 step 5 (D-134)
app.include_router(sponsor_router(lambda: data_service_of(orch())))  # the sponsor layout and weekly sheet (D-435)

# ---------------------------------------------------------------------------- site set-up (step 5b, D-131/132/135)
_setups: dict[str, Any] = {}
log = logging.getLogger("orchestrator")


def setup_of(o: Orchestrator) -> Any:
    """The box's site set-up: schema ``sitesetup`` of the trial database, files under the orchestrator's data folder
    (``sitesetup/``, in every backup), the box's lake for the hospital (``main``)."""
    from sitesetup.service import SiteSetup
    from sitesetup.store import SetupStore

    key = f"{o.db.url}|{o.data_dir}"
    if key not in _setups:

        def site_key() -> bytes:
            return load_key(Path(o.cfg.env.secrets_dir) / "site_hmac.key")  # plain or under the KEK (T-210b)

        svc = SiteSetup(SetupStore(o.db.url), Path(o.data_dir) / "sitesetup", o.services.lake,
                        o.services.llm, o.audit, lambda: _now(o), o.today, site_key,
                        mrn_regex=o.cfg.settings.mrn_regex,
                        publish_batch_seconds=o.cfg.env.site_publish_batch_seconds)  # fmt: skip
        _setups[key] = svc
        o.after_job.append(lambda: _flush_main(svc))  # T-305b (D-403): a batch held by the job goes after it
    return _setups[key]


def _flush_main(svc: Any) -> None:
    """Apply the hospital lake's waiting batch of site decisions, if its window closed and no job holds it."""
    try:
        svc.flush("main")
    except Exception:  # the next tick or the next job tries again; the decisions are stored
        log.exception("site publish batch not applied")


def study_info(o: Orchestrator, rid: str) -> dict[str, Any]:
    """Question 1 of the readiness page: does the study have criteria, approved, and is a draft waiting?"""
    from tb_common.ruleset import RulesetNotApproved, list_rulesets, load_approved

    exists = rid in list_rulesets(o.rulesets_dir)
    version = None
    with contextlib.suppress(RulesetNotApproved, FileNotFoundError, ValueError):
        version = load_approved(o.rulesets_dir, rid).version
    waiting = o.db.find(ruleset=rid, state="awaiting_approval", limit=20)
    exists = exists or bool(waiting) or bool(o.db.find(ruleset=rid, limit=1))
    link = f"/pilot/jobs/{waiting[0].job_id}/approval" if waiting else ""
    return {"id": rid, "exists": exists, "approved": version, "waiting": len(waiting), "approval_link": link}


def records_info(o: Orchestrator, rid: str) -> dict[str, Any]:
    core = core_of(o)
    return {"forms": len(core.forms(rid)), "redcap": any(s["name"] == "redcap" for s in core.sources(rid))}


def approved_of(o: Orchestrator, rid: str) -> Any:
    from tb_common.ruleset import RulesetNotApproved, load_approved

    try:
        return load_approved(o.rulesets_dir, rid)
    except (RulesetNotApproved, FileNotFoundError, ValueError):
        return None


def real_data(o: Orchestrator) -> bool:
    """D-132 remote help needs the hospital's approval when real data may be present: any box that is not a DEV or
    TEST box, or whose data class is not D0 (synthetic)."""
    env = (tb_env(o.cfg.env) if o.cfg.env.extra.get("TB_ENV") else os.environ.get("TB_ENV", "")).upper()
    return env not in ("DEV", "TEST") or os.environ.get("TB_DATA_CLASS", "D0").upper() not in ("D0", "")


app.include_router(
    setup_router(
        lambda: setup_of(orch()),
        lambda rid: study_info(orch(), rid),
        lambda rid: records_info(orch(), rid),
        lambda rid: approved_of(orch(), rid),
        lambda: real_data(orch()),
    )
)

# ---------------------------------------------------------------------------- EDC prefill (D-160)
_edcs: dict[str, Any] = {}


def edc_of(o: Orchestrator) -> Any:
    """EDC prefill: schema ``edc`` of the trial database; reads the box's lake (the hospital record and the site's
    confirmed facts) and, for note items, the gateway; sends through the study store's REDCap tokens."""
    from edc.prefill import LakeFacts, gateway_drafter
    from edc.service import EdcService
    from edc.store import EdcStore, sign_key_of
    from tb_common.optout import opted_out

    key = o.db.url or str(o.data_dir)
    if key not in _edcs:  # the signature key lives with the orchestrator alone (D-281)
        _edcs[key] = EdcStore(o.db.url, sign_key_of(os.environ, Path(o.cfg.env.secrets_dir)))
    llm = o.services.llm
    return EdcService(_edcs[key], core_of(o), o.audit, lambda: _now(o), o.today, study_service_of(o).client,
                      lambda: LakeFacts(o.services.lake),
                      (lambda job: gateway_drafter(llm, job)) if llm is not None else (lambda _job: None),
                      opted_out)  # fmt: skip


app.include_router(edc_router(lambda: edc_of(orch()), _claim))  # the person from the signed assertion (D-162)


class DeceasedRequest(BaseModel):
    pids: list[str] = Field(default_factory=list, max_length=20000)


@app.post("/patients/deceased")
def patients_deceased(body: DeceasedRequest) -> dict[str, Any]:
    """FIT-U04 (T-629, D-415): which of the console's listed pseudonyms the lake's current snapshot records as dead.
    Pseudonyms in, pseudonyms out; no other patient data. A lake that does not answer is a 503, never an empty list."""
    from orchestrator.scenarios.screen import deceased_now

    pids = [p for p in body.pids if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", p)]
    try:
        return {"deceased": deceased_now(orch().services.lake, pids)}
    except Exception as exc:  # the lake's own error stays in the log; the console stops contacts on a 503
        raise HTTPException(status_code=503, detail="the lake could not be read") from exc


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
    from tb_common.ruleset import RulesetNotApproved, load_approved

    # D-476 (review of T-707): only pool rows evaluated on the criteria version in force are promoted; with no
    # approved version there is none ("": no row matches)
    in_force = ""
    with contextlib.suppress(RulesetNotApproved, FileNotFoundError, ValueError):
        in_force = load_approved(o.rulesets_dir, ruleset.upper(), on=o.today()).version
    try:
        return {"added": registry_of(o).promote(ruleset, req, _now(o), in_force)}
    except RegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/registry/{ruleset}/export.xlsx")
def registry_export(ruleset: str, request: Request, by: str | None = None) -> Response:
    """The screening log with every chart number of a study (review 2026-11-09 S-09): a verified signed-in user
    only, at most ``TB_EXPORT_MAX_PER_HOUR`` per person, and one audit event with the actor, the session and the
    file's sha256 here, whoever calls."""
    from tb_common.crypto import sha256_bytes

    o = orch()
    claim = _claim(request, by)  # ``by`` counts only on a DEV/TEST box without a token
    rid = ruleset.strip().upper()
    # D-273 (PV-5): the role and the study, not only a name; T-103: never to a break-glass grant (a whole list)
    _id_authority(o, claim, rid, "registry.export_refused", whole_list=True)
    if over := _over_cap(o, request, claim, EXPORTS, EXPORTS_SERVICE):
        o.audit.append("registry.export_refused", ruleset=rid, actor=claim.name,
                       detail={"reason": over})  # fmt: skip
        raise HTTPException(status_code=429, detail="too many exports with chart numbers in the last hour")
    try:
        data = registry_of(o).export_xlsx(ruleset, o.cfg.settings.site.id)
    except RegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    o.audit.append("registry.export", ruleset=rid, actor=claim.name, output_sha=sha256_bytes(data),
                   detail={"session": claim.session, "verified": claim.verified,
                           "caller": getattr(request.state, "tb_caller", None) or ""})  # fmt: skip
    from tb_common.flowledger import record_export

    record_export(o.audit, channel="registry_export", filename=f"screening_log_{rid}.xlsx", data=data,
                  identifier_level="identified", actor=claim.name, ruleset=rid,
                  approval=f"study {rid} screening log; {'verified' if claim.verified else 'unverified'} sign-in, "
                           f"rate-limited (S-09)")  # fmt: skip
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="screening_log_{ruleset.upper()}.xlsx"'},
    )


CALLER_GATE.bind(app)  # T-713 (D-464): every route is included above; the gate compiles them once, here
