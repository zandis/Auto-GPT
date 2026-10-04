"""Orchestrator core (SPEC §4.8, §5, §8): job lifecycle, worker pool, output publishing and mail routing.

* Every state change is written to the job store and appended to the audit chain (``job.state``).
* Every output file is stored under ``outputs/<job_id>/``, hashed and audited (``output``) before it can be mailed.
* ``phi`` outputs may only be delivered to the ruleset's ``list_to`` / ``referral_to`` recipients inside
  ``settings.internal_domains``; a violation fails the job (SPEC §5 routing enforcement).
* Replies: ``Received <job_id>`` on creation, then ``Done <job_id>`` or ``Failed <job_id>`` with the failed step.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from lake.client import LakeAPI
from tb_common.audit import AuditLog
from tb_common.authz import allowed, norm
from tb_common.config import Config
from tb_common.crypto import sha256_bytes
from tb_common.fhir import FhirEvaluator
from tb_common.http import ServiceError
from tb_common.llm import LlmClient
from tb_common.objstore import ObjectStore
from tb_common.routing import RoutingViolation, check, is_internal
from tb_common.ruleset import RulesetNotApproved
from tb_common.timeutil import now
from tb_common.ulid import new_ulid
from tb_contracts import (
    Job,
    JobCreate,
    JobError,
    JobFile,
    JobMetrics,
    JobOutput,
    Routing,
    SendAttachment,
    SendRequest,
    SendResult,
)

from orchestrator.clients import AdapterAPI, CompilerAPI, MailAPI, ParserAPI, StepFailed
from orchestrator.db import TERMINAL, JobDB

log = logging.getLogger("orchestrator")
SYSTEM_SENDERS = ("scheduler", "system")
FAST_LANE = ("STATUS", "CANCEL")


class Cancelled(RuntimeError):
    pass


class Rejected(RuntimeError):
    """Job creation refused (permission / rate limit)."""


@dataclass
class Delivery:
    to: list[str]
    outputs: list[JobOutput] = field(default_factory=list)
    subject: str | None = None
    body_md: str | None = None
    kind: str = "done"
    routing: Routing | None = None


@dataclass
class Outcome:
    state: str = "done"  # done | awaiting_approval
    summary_md: str = ""
    deliveries: list[Delivery] = field(default_factory=list)


@dataclass
class Services:
    lake: LakeAPI
    parser: ParserAPI
    compiler: CompilerAPI
    mail: MailAPI
    adapter: AdapterAPI | None = None
    fhir: FhirEvaluator | None = None
    llm: LlmClient | None = None


Scenario = Callable[["Ctx"], Outcome]


class Ctx:
    """What a scenario sees: its job, configuration, services and the publish/state primitives."""

    def __init__(self, orch: Orchestrator, job: Job) -> None:
        self.orch = orch
        self._job = job

    @property
    def job(self) -> Job:
        return self._job

    @property
    def cfg(self) -> Config:
        return self.orch.cfg

    @property
    def services(self) -> Services:
        return self.orch.services

    @property
    def store(self) -> ObjectStore:
        return self.orch.store

    @property
    def rulesets_dir(self) -> Path:
        return self.orch.rulesets_dir

    @property
    def data_dir(self) -> Path:
        return self.orch.data_dir

    def today(self) -> date:
        return self.orch.today()

    def state(self, state: str) -> None:
        if self.orch.db.cancel_requested(self._job.job_id):
            raise Cancelled("cancelled")
        self._job = self.orch.set_state(self._job, state)

    def update(self, **fields: Any) -> Job:
        self._job = self._job.model_copy(update=fields)
        self.orch.db.put(self._job)
        return self._job

    def metrics(self, **values: Any) -> None:
        cur = (self._job.metrics or JobMetrics()).model_dump()
        cur.update(values)
        self.update(metrics=JobMetrics.model_validate(cur))

    def input_bytes(self, f: JobFile) -> bytes:
        return self.store.get(f.minio_key)

    def publish(self, filename: str, data: bytes, tag: str, recipients: list[str]) -> JobOutput:
        """Store, hash and audit one output file (SPEC §10.2: every output file is hashed into the audit chain)."""
        if tag not in ("aggregate", "phi"):
            raise ValueError(f"bad output tag {tag!r}")
        safe = re.sub(r"[^\w.\-㐀-鿿]+", "_", filename)
        key = f"outputs/{self._job.job_id}/{safe}"
        ctype = mimetypes.guess_type(safe)[0] or "application/octet-stream"
        self.store.put(key, data, ctype)
        out = JobOutput(
            filename=safe,
            sha256=sha256_bytes(data),
            minio_key=key,
            recipients=sorted({norm(r) for r in recipients}),
            tag=cast(Literal["aggregate", "phi"], tag),
        )
        self.orch.audit.append(
            "output",
            job_id=self._job.job_id,
            ruleset=self._job.ruleset,
            ruleset_version=self._job.ruleset_version,
            snapshot=self._job.snapshot_date.isoformat() if self._job.snapshot_date else None,
            output_sha=out.sha256,
            recipients=out.recipients,
            detail={"filename": safe, "tag": tag, "bytes": len(data)},
        )
        outputs = [o for o in (self._job.outputs or []) if o.filename != safe] + [out]
        self.update(outputs=outputs)
        return out

    def copy_object(self, key: str, filename: str, tag: str, recipients: list[str]) -> JobOutput:
        return self.publish(filename, self.store.get(key), tag, recipients)


class Orchestrator:
    def __init__(
        self,
        cfg: Config,
        db: JobDB,
        store: ObjectStore,
        audit: AuditLog,
        services: Services,
        scenarios: dict[str, Scenario],
        rulesets_dir: Path,
        data_dir: Path,
        today: Callable[[], date] | None = None,
        workers: int = 4,
        async_notify: bool = True,
    ) -> None:
        self.cfg = cfg
        self.db = db
        self.store = store
        self.audit = audit
        self.services = services
        self.scenarios = scenarios
        self.rulesets_dir = rulesets_dir
        self.data_dir = data_dir
        self._today = today
        self.n_workers = workers
        self._stop = threading.Event()
        self._wake = threading.Condition()
        self._threads: list[threading.Thread] = []
        self._notify = ThreadPoolExecutor(max_workers=2, thread_name_prefix="notify") if async_notify else None

    # ------------------------------------------------------------------ time
    def today(self) -> date:
        return self._today() if self._today else now(self.cfg.env.tz).date()

    def _now(self) -> datetime:
        return now(self.cfg.env.tz)

    # ------------------------------------------------------------------ job lifecycle
    def create(self, req: JobCreate, notify: bool = True) -> Job:
        if req.job_id:
            existing = self.db.get(req.job_id)
            if existing is not None:  # idempotent on the pre-allocated id
                return existing
        sender = norm(req.requested_by)
        jtype = req.type
        if sender not in SYSTEM_SENDERS:
            if not allowed(self.cfg.settings, jtype, sender):
                raise Rejected(f"{sender} is not permitted to run {jtype}")
            limit = self.cfg.settings.rate_limit_per_sender_per_day or 20
            since = (self._now() - timedelta(days=1)).isoformat()
            if self.db.count_since(sender, since) >= limit:
                raise Rejected(f"rate limit reached ({limit} jobs per sender per day)")
        ts = self._now()
        job = Job(
            job_id=req.job_id or new_ulid(),
            type=req.type,
            ruleset=req.ruleset,
            requested_by=sender,
            received_at=ts,
            updated_at=ts,
            state="received",
            options=dict(req.options or {}),
            comment=req.comment,
            message_id=req.message_id,
            in_reply_to=req.in_reply_to,
            inputs=list(req.inputs or []),
            outputs=[],
            metrics=JobMetrics(),
        )
        self.db.put(job, queued=jtype not in FAST_LANE)
        self.audit.append(
            "job.state",
            ts=ts,
            job_id=job.job_id,
            ruleset=job.ruleset,
            actor=sender,
            input_sha=",".join(f.sha256 for f in job.inputs or []) or None,
            detail={"from": None, "to": "received", "type": jtype, "options": job.options},
        )
        if jtype in FAST_LANE:  # answered at once, never queued behind long jobs
            return self._fast(job)
        if notify and sender not in SYSTEM_SENDERS:
            if self._notify is not None:
                self._notify.submit(self._received_mail, job)
            else:
                self._received_mail(job)
        with self._wake:
            self._wake.notify()
        return job

    def _fast(self, job: Job) -> Job:
        return self.run(job.job_id)

    def set_state(self, job: Job, state: str, **fields: Any) -> Job:
        prev = job.state
        ts = self._now()
        job = job.model_copy(update={"state": state, "updated_at": ts, **fields})
        self.db.put(job)
        self.audit.append(
            "job.state",
            ts=ts,
            job_id=job.job_id,
            ruleset=job.ruleset,
            ruleset_version=job.ruleset_version,
            snapshot=job.snapshot_date.isoformat() if job.snapshot_date else None,
            actor=job.requested_by,
            detail={"from": prev, "to": state, **({"error": job.error.model_dump()} if job.error else {})},
        )
        return job

    def cancel(self, job_id: str, by: str) -> Job:
        job = self.db.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.state in TERMINAL:
            return job
        self.db.request_cancel(job_id)
        if job.state in ("received", "awaiting_approval"):  # not in a worker: fail now
            job = self.set_state(job, "failed", error=JobError(step="cancelled", message=f"Cancelled by {norm(by)}."))
        return job

    def requeue(self, job_id: str) -> None:
        self.db.enqueue(job_id)
        with self._wake:
            self._wake.notify()

    def resume_awaiting(self, ruleset: str, version: str) -> list[str]:
        """APPROVE completed: put jobs waiting for this ruleset version back on the queue (SPEC §8.1)."""
        ids = [j.job_id for j in self.db.find(state="awaiting_approval", ruleset=ruleset, version=version)]
        for jid in ids:
            job = self.db.get(jid)
            if job is not None:
                self.set_state(job, "received")
                self.requeue(jid)
        return ids

    def fail_awaiting(self, ruleset: str, version: str, step: str, message: str) -> list[str]:
        ids = []
        for job in self.db.find(state="awaiting_approval", ruleset=ruleset, version=version):
            job = self.set_state(job, "failed", error=JobError(step=step, message=message))
            self._failed_mail(job)
            ids.append(job.job_id)
        return ids

    # ------------------------------------------------------------------ running
    def run(self, job_id: str) -> Job:
        job = self.db.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.state in TERMINAL:
            return job
        t0 = time.perf_counter()
        ctx = Ctx(self, job)
        scenario = self.scenarios.get(job.type)
        try:
            if scenario is None:
                raise StepFailed("received", f"{job.type} jobs are not available on this box yet.")
            outcome = scenario(ctx)
            job = ctx.job
            self._deliver(job, outcome)
            job = self.db.get(job_id) or job
            wall = round((job.metrics.wall_seconds if job.metrics else 0) + time.perf_counter() - t0, 3)
            metrics = (job.metrics or JobMetrics()).model_copy(update={"wall_seconds": wall})
            job = self.set_state(job, outcome.state, metrics=metrics)
        except Cancelled:
            job = self.db.get(job_id) or ctx.job
            if job.state not in TERMINAL:
                job = self.set_state(job, "failed", error=JobError(step="cancelled", message="Cancelled on request."))
        except Exception as exc:  # every failure becomes a Failed reply with the step
            job = self.db.get(job_id) or ctx.job
            err = _error(exc, job.state)
            if not isinstance(exc, (StepFailed, RulesetNotApproved, RoutingViolation)):
                log.exception("job %s failed in %s", job_id, job.state)
            job = self.set_state(job, "failed", error=err)
            self._failed_mail(job)
        return job

    def _deliver(self, job: Job, outcome: Outcome) -> None:
        requester_served = False
        domains = self.cfg.settings.internal_domains
        for d in outcome.deliveries:  # check every route before anything is sent
            for o in d.outputs:
                check(o.tag, sorted({norm(r) for r in d.to if r}) or ["-"], d.routing, domains)
        for d in outcome.deliveries:
            recipients = sorted({norm(r) for r in d.to if r})
            if not recipients:
                continue
            self.send(
                job,
                recipients,
                d.subject or f"Done {job.job_id} — {_title(job)}",
                d.body_md or outcome.summary_md,
                d.outputs,
                kind=d.kind,
            )
            requester_served = requester_served or job.requested_by in recipients
        if outcome.state == "done" and not requester_served and job.requested_by not in SYSTEM_SENDERS:
            self.send(
                job, [job.requested_by], f"Done {job.job_id} — {_title(job)}", outcome.summary_md, [], kind="done"
            )

    def send(
        self, job: Job, to: list[str], subject: str, body_md: str, outputs: list[JobOutput], kind: str
    ) -> SendResult:
        tag: Literal["aggregate", "phi"] = "phi" if any(o.tag == "phi" for o in outputs) else "aggregate"
        if tag == "aggregate":
            external = [r for r in to if not is_internal(r, self.cfg.settings.internal_domains)]
            if external and kind in ("received", "failed", "status"):
                to = [r for r in to if r not in external]  # system details never leave the hospital
        req = SendRequest(
            job_id=job.job_id,
            to=to,
            subject=subject,
            body_md=body_md,
            attachments=[SendAttachment(minio_key=o.minio_key, filename=o.filename, tag=o.tag) for o in outputs],
            encrypt=tag == "phi",
            tag=tag,
            in_reply_to=job.message_id,
        )
        res = self.services.mail.send(req)
        self.db.add_mail(res.message_id, job.job_id, kind, subject, self._now().isoformat())
        return res

    def _received_mail(self, job: Job) -> None:
        body = (
            f"Your request **{_title(job)}** was received at {job.received_at.isoformat(timespec='seconds')} and "
            f"queued as job `{job.job_id}`.\n\nResults follow by email. Reply `STATUS {job.job_id}` for progress or "
            f"`CANCEL {job.job_id}` to cancel."
        )
        try:
            self.send(job, [job.requested_by], f"Received {job.job_id} — {_title(job)}", body, [], kind="received")
        except (StepFailed, ServiceError, RuntimeError) as exc:
            log.warning("could not send Received mail for %s: %s", job.job_id, exc)

    def _failed_mail(self, job: Job) -> None:
        to = job.requested_by
        if to in SYSTEM_SENDERS:
            to = self.cfg.settings.site.contact or ""
        if not to:
            return
        err = job.error or JobError(step="unknown", message="unknown error")
        body = (
            f"Job `{job.job_id}` (**{_title(job)}**) failed.\n\n- Step: **{err.step}**\n- Reason: {err.message}\n\n"
            f"Nothing was sent to other recipients. Fix the request and send it again, or reply "
            f"`STATUS {job.job_id}` for the job record."
        )
        try:
            self.send(job, [to], f"Failed {job.job_id} — {_title(job)}", body, [], kind="failed")
        except (StepFailed, ServiceError, RuntimeError) as exc:
            log.warning("could not send Failed mail for %s: %s", job.job_id, exc)

    # ------------------------------------------------------------------ worker pool
    def start(self) -> None:
        for jid in self.db.interrupted():  # restart recovery: re-run from the beginning (scenarios are idempotent)
            job = self.db.get(jid)
            if job is not None:
                self.audit.append("job.requeued", job_id=jid, detail={"state": job.state})
                self.set_state(job, "received")
                self.db.enqueue(jid)
        for i in range(self.n_workers):
            t = threading.Thread(target=self._worker, name=f"worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        with self._wake:
            self._wake.notify_all()
        for t in self._threads:
            t.join(timeout=5)
        if self._notify is not None:
            self._notify.shutdown(wait=True)

    def _worker(self) -> None:
        while not self._stop.is_set():
            jid = self.db.claim()
            if jid is None:
                with self._wake:
                    self._wake.wait(timeout=2.0)
                continue
            try:
                self.run(jid)
            except Exception:  # never let a worker die
                log.exception("worker error on %s", jid)

    def drain(self, timeout: float = 600) -> None:
        """Run queued jobs synchronously until the queue is empty (tests / CLI)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            jid = self.db.claim()
            if jid is None:
                return
            self.run(jid)
        raise TimeoutError("queue not drained")


def _title(job: Job) -> str:
    target = job.ruleset or (job.options or {}).get("target") or ""
    return f"{job.type} {target}".strip()


def _error(exc: Exception, state: str) -> JobError:
    if isinstance(exc, StepFailed):
        return JobError(step=exc.step, message=exc.message, detail=exc.detail or None)
    if isinstance(exc, RulesetNotApproved):
        return JobError(step="ruleset", message=f"{exc}. Runs need an approved ruleset (SPEC §5).")
    if isinstance(exc, RoutingViolation):
        return JobError(step="routing", message=f"Output routing refused: {exc}.")
    if isinstance(exc, ServiceError):
        return JobError(step=state, message=f"The {exc.service} service failed.", detail=f"HTTP {exc.status}")
    return JobError(
        step=state, message="Internal error while processing the job.", detail=f"{type(exc).__name__}: {str(exc)[:300]}"
    )


def job_markdown(job: Job) -> str:
    body = json.dumps(job.model_dump(mode="json", by_alias=True, exclude_none=True), ensure_ascii=False, indent=1)
    return f"```json\n{body}\n```"
