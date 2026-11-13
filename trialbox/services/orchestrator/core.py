"""Orchestrator core (SPEC §4.8, §5, §8): job lifecycle, worker pool, output publishing and mail routing.

* Every state change is written to the job store and appended to the audit chain (``job.state``).
* Every output file is stored under ``outputs/<job_id>/``, hashed and audited (``output``) before it can be mailed.
* ``phi`` outputs may only be delivered to the ruleset's ``list_to`` / ``referral_to`` recipients inside
  ``settings.internal_domains``; a violation fails the job (SPEC §5 routing enforcement).
* Replies: ``[<study>] <CMD> received · job <id>`` on creation, then ``... done: <headline> · job <id>`` or
  ``... failed: at <step> · job <id>`` (D-88).
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
from typing import TYPE_CHECKING, Any, Literal, cast

from lake.client import LakeAPI
from tb_common.audit import AuditLog, mask_detail
from tb_common.authz import allowed, daily_limit, norm, role_allowed
from tb_common.config import Config
from tb_common.crypto import sha256_bytes
from tb_common.fhir import FhirEvaluator
from tb_common.flowledger import level_of_tag, record_export
from tb_common.http import ServiceError
from tb_common.llm import LlmClient
from tb_common.objstore import ObjectStore
from tb_common.routing import RoutingViolation, check, is_internal
from tb_common.ruleset import RulesetNotApproved
from tb_common.subject import job_subject
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

from orchestrator import i18n
from orchestrator.clients import AdapterAPI, CompilerAPI, MailAPI, ParserAPI, StepFailed
from orchestrator.db import TERMINAL, JobDB, JobLeased
from orchestrator.jobs import guarded_services, max_restarts, pinned_services, release_hold

if TYPE_CHECKING:
    from orchestrator.decision_context import DecisionContext

log = logging.getLogger("orchestrator")
SYSTEM_SENDERS = ("scheduler", "system")
FAST_LANE = ("STATUS", "CANCEL")


def send_key(job_id: str, kind: str, to: list[str], subject: str, filenames: list[str]) -> str:
    """The idempotency key of one mail (D-127, review F-02): the same job, kind, recipients, subject and attachment
    names give the same key, so a step re-run after a restart never mails the PI or the password twice."""
    import hashlib

    parts = [job_id, kind, ",".join(sorted(to)), subject, ",".join(sorted(filenames))]
    return "tbmail-" + hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class Cancelled(RuntimeError):
    pass


class Rejected(RuntimeError):
    """Job creation refused (permission / rate limit)."""


class NotRetryable(RuntimeError):
    """A retry refused for the job's own state (D-474): not failed, not a scheduler job, or one already unfinished."""


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
    headline: str = ""  # the answer in a few words, for the subject line ("1–7 in 12 mo", "<5 high, 6 review")


@dataclass
class Services:
    lake: LakeAPI
    parser: ParserAPI
    compiler: CompilerAPI
    mail: MailAPI
    adapter: AdapterAPI | None = None
    fhir: FhirEvaluator | None = None
    llm: LlmClient | None = None
    verifier: LlmClient | None = None  # second model (the V build), used where a step wants an independent check


Scenario = Callable[["Ctx"], Outcome]


class Ctx:
    """What a scenario sees: its job, configuration, services and the publish/state primitives."""

    def __init__(self, orch: Orchestrator, job: Job) -> None:
        self.orch = orch
        self._job = job
        self._services: Services | None = None
        self._decision: DecisionContext | None = None

    @property
    def decision(self) -> DecisionContext:
        """What this job reads to decide (T-708, D-477): the pinned snapshot, the opt-out register, consent, the
        ruleset and its pins, the note-block decision and the run date. One per job, beside the pinned lake."""
        if self._decision is None:
            from orchestrator.decision_context import DecisionContext

            self._decision = DecisionContext(self)
        return self._decision

    @property
    def job(self) -> Job:
        return self._job

    @property
    def cfg(self) -> Config:
        return self.orch.cfg

    @property
    def services(self) -> Services:
        """The orchestrator's services for this job: the lake pinned to the job's snapshot (T-305a, D-383) and the model
        clients guarded by the cancel check and the SCREEN breaker (T-108d, D-389). One per job, so the judge and the
        verifier keep their identity."""
        if self._services is None:
            self._services = guarded_services(self, pinned_services(self))
        return self._services

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
        """The job's run date: fixed when the job starts, so a run across midnight and any re-run use one date."""
        return self._job.run_date or self.orch.today()

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
        job = self._job
        record_export(  # the export ledger (dataflow P0-8, D-149): what leaves, how identifiable, under what approval
            self.orch.audit,
            channel="job_output",
            filename=safe,
            sha256=out.sha256,
            nbytes=len(data),
            identifier_level=level_of_tag(tag),
            approval=(
                f"ruleset {job.ruleset}@{job.ruleset_version}; job {job.type} requested by {job.requested_by}"
                if job.ruleset
                else f"job {job.type} requested by {job.requested_by}"
            ),
            recipients=out.recipients,
            actor="orchestrator",
            ruleset=job.ruleset,
            ruleset_version=job.ruleset_version,
            job_id=job.job_id,
            snapshot=job.snapshot_date.isoformat() if job.snapshot_date else None,
        )
        outputs = [o for o in (self._job.outputs or []) if o.filename != safe] + [out]
        self.update(outputs=outputs)
        return out

    def copy_object(self, key: str, filename: str, tag: str, recipients: list[str]) -> JobOutput:
        return self.publish(filename, self.store.get(key), tag, recipients)


INGEST_ONLY = ("INGEST",)  # the job types the first worker takes when there are two or more (T-704, D-458)


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
        self._watched: set[str] = set()  # D-532: jobs left to another worker; looked at again when idle
        self._notify = ThreadPoolExecutor(max_workers=2, thread_name_prefix="notify") if async_notify else None
        # T-305b (D-403): called after a job ends and its lake hold is released (the site's batched publish waits
        # for the jobs that read the snapshot it would rebuild)
        self.after_job: list[Callable[[], None]] = []
        # T-726 (D-492): called with every job that reaches a final state, whatever ended it (the night's chain
        # starts its next step then)
        self.on_terminal: list[Callable[[Job], None]] = []

    # ------------------------------------------------------------------ time
    def today(self) -> date:
        return self._today() if self._today else now(self.cfg.env.tz).date()

    @property
    def clock_pinned(self) -> bool:
        """True when ``TB_TODAY`` pins the clock (test stack); reports print it in their footer (D-101)."""
        return self._today is not None

    def _now(self) -> datetime:
        return now(self.cfg.env.tz)

    # ------------------------------------------------------------------ job lifecycle
    def create(self, req: JobCreate, notify: bool = True, role: str = "", by: str = "") -> Job:
        """A new job. ``role`` and ``by``: the console account behind the request, from the console's signed actor
        assertion (D-146, review J-01); the request is then authorised by that role, not by the mailbox, which stays
        the reply address. A mailed request (no role) is authorised by the mailbox rules of settings.yaml."""
        if req.job_id:
            existing = self.db.get(req.job_id)
            if existing is not None:  # idempotent on the pre-allocated id
                return existing
        sender = norm(req.requested_by)
        jtype = req.type
        if sender not in SYSTEM_SENDERS:
            if role:
                if not role_allowed(role, jtype):
                    raise Rejected(f"the {role} role may not run {jtype}")
            elif not allowed(self.cfg.settings, jtype, sender):
                raise Rejected(f"{sender} is not permitted to run {jtype}")
            limit = daily_limit(self.cfg.settings, jtype)  # D-146 (J-02): heavy job types only, each on its own
            since = (self._now() - timedelta(days=1)).isoformat()
            if limit is not None and self.db.count_since(sender, since, jtype) >= limit:
                raise Rejected(f"rate limit reached ({limit} {jtype} jobs per sender per day)")
        who = {"by": by, "role": role} if role else {}  # D-146: the console account behind the request, when known
        return self._admit(req, sender, who, notify)

    def _admit(
        self, req: JobCreate, sender: str, who: dict[str, str], notify: bool, parent_job_id: str | None = None
    ) -> Job:
        """Store, audit and queue (or run, for the fast lane) a job already authorised by the caller."""
        jtype = req.type
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
            parent_job_id=parent_job_id,
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
            # D-272 (CR-016): the options are audited masked; the job keeps them for the run
            detail={"from": None, "to": "received", "type": jtype, "options": mask_detail(job.options), **who},
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

    # ------------------------------------------------------------------ the administrator's retry (T-746, D-474)
    def scheduled_root(self, job: Job) -> Job | None:
        """The scheduler job ``job`` runs again: ``job`` itself when the box's scheduler started it (a type of
        ``scheduler.plan``, ``requested_by: scheduler``), the start of its ``parent_job_id`` chain when it is a retry
        of one (every link of the same type and study); None otherwise."""
        from orchestrator.scheduler import scheduled_types

        if job.type not in scheduled_types():
            return None
        seen: set[str] = set()
        cur: Job | None = job
        while cur is not None and cur.job_id not in seen:
            seen.add(cur.job_id)
            if (cur.type, cur.ruleset) != (job.type, job.ruleset):
                return None
            if norm(cur.requested_by) == "scheduler" and not cur.parent_job_id:
                return cur
            cur = self.db.get(cur.parent_job_id) if cur.parent_job_id else None
        return None

    def retry_scheduled(self, job_id: str, *, by: str, role: str, reply_to: str) -> Job:
        """Run a failed scheduler job again (``job.retry_scheduled``, D-474): the new job copies the failed job's type,
        study, options, comment and inputs (nothing chosen by the caller), names ``reply_to`` (the administrator's
        mailbox) and the failed job (``parent_job_id``). KeyError: no such job; Rejected: the role may not;
        :class:`NotRetryable`: not failed, not a scheduler job, or one of its type and study is not finished."""
        from tb_common.authz import permit

        if not permit(role, "job.retry_scheduled").allowed:
            raise Rejected(f"the {role or 'unnamed'} role may not retry a scheduled job")
        failed = self.db.get(job_id)
        if failed is None:
            raise KeyError(job_id)
        if failed.state != "failed":
            raise NotRetryable(f"job {job_id} has not failed")
        if self.scheduled_root(failed) is None:
            raise NotRetryable(f"job {job_id} was not started by the box's scheduler")
        sender = norm(reply_to)
        if not sender or sender in SYSTEM_SENDERS or "@" not in sender:
            raise Rejected("a retry names the administrator's mailbox (console.cli set-mailbox)")
        busy = self.db.unfinished(failed.type, failed.ruleset)
        if busy:
            raise NotRetryable(f"a {failed.type} job of the same study is already queued or running ({busy[0]})")
        req = JobCreate(
            type=failed.type,
            ruleset=failed.ruleset,
            options=dict(failed.options or {}) or None,
            comment=failed.comment,
            requested_by=sender,
            inputs=list(failed.inputs or []) or None,
        )
        job = self._admit(req, sender, {"by": by, "role": role, "retry_of": failed.job_id}, notify=True,
                          parent_job_id=failed.job_id)  # fmt: skip
        self.audit.append(
            "job.retried",
            job_id=job.job_id,
            ruleset=job.ruleset,
            actor=by or sender,
            detail={"from": failed.job_id, "type": job.type, "by": by, "role": role},
        )
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
            detail={"from": prev, "to": state, **({"error": mask_detail(job.error.model_dump())} if job.error else {})},
        )
        if state in TERMINAL and prev not in TERMINAL:
            for hook in list(self.on_terminal):
                try:
                    hook(job)
                except Exception:  # a hook's failure is its own; the job is finished
                    log.exception("on-terminal hook failed")
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
            self._release_waiting(job)
            self.db.answers_drop(job_id)
        return job

    def _release_waiting(self, job: Job) -> None:
        """A job that ends outside a worker (cancelled or failed while it waited) releases its lake hold (D-403)."""
        if job.snapshot_date is not None:
            release_hold(self.services, job.job_id)

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
            self._release_waiting(job)
            ids.append(job.job_id)
        return ids

    # ------------------------------------------------------------------ running
    def run(self, job_id: str) -> Job:
        job = self.db.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.state in TERMINAL:
            return job
        # NEW-B-11 (D-532): one worker runs a job at a time, in every process on this database. The lease is the
        # run's; it ends with the run, or with the worker's connection when the worker dies
        try:
            lease = self.db.lease(job_id)
        except JobLeased:
            # the job was claimed (it is not queued any more) and is not run here: it is watched, and queued again
            # when its holder is gone and it has not ended (review HIGH-1, MED-3)
            log.warning("job %s is being run by another worker: not run a second time", job_id)
            self._watch(job_id)
            return job
        except Exception:
            # the lease could not be asked for (the database refused the connection): the claimed job goes back on
            # the queue, or nothing would ever run it (review HIGH-2)
            self.db.enqueue(job_id)
            raise
        try:
            return self._run(job)
        finally:
            lease.release()

    def _run(self, job: Job) -> Job:
        job_id = job.job_id
        t0 = time.perf_counter()
        if job.run_date is None:  # not a state change: no audit event; the "running" transition follows
            job = job.model_copy(update={"run_date": self.today()})
            self.db.put(job)
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
        if job.state in TERMINAL:
            self.db.answers_drop(job_id)  # T-689 (D-456): the kept answers go with the job's end, in any state
            self._end_hold(ctx, job)
        return job

    def _end_hold(self, ctx: Ctx, job: Job) -> None:
        """T-305b (D-403): the ended job's lake hold is released, then the hooks waiting for it run."""
        if ctx._services is None and job.snapshot_date is None:
            return  # the job never read the lake
        release_hold(ctx._services, job.job_id)
        for hook in list(self.after_job):
            try:
                hook()
            except Exception:  # a hook's failure is its own; the job is already finished
                log.exception("after-job hook failed")

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
                d.subject or _subject(job, "done", outcome.headline),
                d.body_md or outcome.summary_md,
                d.outputs,
                kind=d.kind,
            )
            requester_served = requester_served or job.requested_by in recipients
        if outcome.state == "done" and not requester_served and job.requested_by not in SYSTEM_SENDERS:
            self.send(
                job, [job.requested_by], _subject(job, "done", outcome.headline), outcome.summary_md, [], kind="done"
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
            idempotency_key=send_key(job.job_id, kind, to, subject, [o.filename for o in outputs]),
        )
        res = self.services.mail.send(req)
        self.db.add_mail(res.message_id, job.job_id, kind, subject, self._now().isoformat())
        return res

    def lang(self, job: Job) -> str:
        """The job's language for mail and reports (D-100): ``lang=`` option, else the site locale."""
        return i18n.job_lang(job.options, self.cfg.settings.site.locale if self.cfg.settings.site else None)

    def _received_mail(self, job: Job) -> None:
        body = i18n.t(
            self.lang(job),
            "mail.received",
            title=_title(job),
            at=job.received_at.isoformat(timespec="seconds"),
            job=job.job_id,
        )
        try:
            self.send(job, [job.requested_by], _subject(job, "received"), body, [], kind="received")
        except (StepFailed, ServiceError, RuntimeError) as exc:
            log.warning("could not send Received mail for %s: %s", job.job_id, exc)

    def _failed_mail(self, job: Job) -> None:
        to = job.requested_by
        if to in SYSTEM_SENDERS:
            to = self.cfg.settings.site.contact or ""
        if not to:
            return
        err = job.error or JobError(step="unknown", message="unknown error")
        body = i18n.t(
            self.lang(job), "mail.failed", job=job.job_id, title=_title(job), step=err.step, reason=err.message
        )
        try:
            self.send(job, [to], _subject(job, "failed", f"at {err.step}"), body, [], kind="failed")
        except (StepFailed, ServiceError, RuntimeError) as exc:
            log.warning("could not send Failed mail for %s: %s", job.job_id, exc)

    # ------------------------------------------------------------------ restart recovery (T-689; D-532)
    def _watch(self, job_id: str) -> None:
        with self._wake:
            self._watched.add(job_id)

    def _recover_or_watch(self, jid: str, limit: int) -> bool:
        """Queue an interrupted job again, under the job's own lease so that no worker starts it meanwhile. A job
        whose lease another worker holds is not interrupted: it is watched (:meth:`_rewatch`). True: recovered."""
        try:
            lease = self.db.lease(jid)
        except JobLeased:
            # D-532: another orchestrator process on this database is running it now (an update that starts the
            # new container before the old one stopped). It is left to its worker, and looked at again
            log.warning("job %s is being run by another orchestrator: not queued again", jid)
            self._watch(jid)
            return False
        try:
            if jid in self.db.interrupted():  # read again under the lease: its run may just have ended it
                self._recover(jid, limit)
        finally:
            lease.release()
        return True

    def _rewatch(self) -> bool:
        """Look again at the jobs that were left to another worker: one that is still neither queued nor ended
        when nobody holds its lease any more was interrupted after all (its holder died, or stopped without
        finishing it) and is recovered as at a start. Called by an idle worker. True: something was queued."""
        with self._wake:
            watched = sorted(self._watched)
        if not watched:
            return False
        open_ids = set(self.db.interrupted())
        limit, queued = max_restarts(), False
        for jid in watched:
            if jid in open_ids and not self._recover_or_watch(jid, limit):
                continue  # still its holder's
            with self._wake:
                self._watched.discard(jid)
            queued = queued or jid in open_ids
        return queued

    def _recover(self, jid: str, limit: int) -> None:
        job = self.db.get(jid)
        if job is None:
            return
        # T-689 (D-456, review F-28): the restart is counted; the answers the job's models already gave are
        # kept and replayed (orchestrator.jobs.KeptAnswers), so the run does not start its model work at zero
        n = self.db.count_restart(jid)
        kept = self.db.answer_count(jid)
        if n > limit:
            self.audit.append("job.requeued", job_id=jid, detail={"state": job.state, "restarts": n, "gave_up": 1})
            job = self.set_state(
                job,
                "failed",
                error=JobError(
                    step=job.state,
                    message=f"This job was interrupted by a restart of the box {n} times and was not started "
                    f"again (the limit is TB_JOB_MAX_RESTARTS = {limit}): the job itself may be what stops the "
                    f"box. Nothing was sent. Check the box's memory and logs (RUNBOOK §4), then send the "
                    f"request again.",
                ),
            )
            self._failed_mail(job)
            self._release_waiting(job)
            self.db.answers_drop(jid)
            return
        self.audit.append("job.requeued", job_id=jid, detail={"state": job.state, "restarts": n, "kept_answers": kept})
        self.set_state(job, "received")
        self.db.enqueue(jid)

    # ------------------------------------------------------------------ worker pool
    def start(self) -> None:
        self.db.answers_sweep()  # T-689 (D-456): kept answers live only as long as their job is unfinished
        limit = max_restarts()
        for jid in self.db.interrupted():  # restart recovery: run again from the start (scenarios are idempotent)
            self._recover_or_watch(jid, limit)
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
        # T-704 (D-458; scale review F-33): with two or more workers the first is the ingest's: long jobs on every
        # other worker never make the night's ingest wait
        only = INGEST_ONLY if self.n_workers > 1 and threading.current_thread().name == "worker-0" else ()
        while not self._stop.is_set():
            jid = self.db.claim(only)
            if jid is None:
                try:
                    if self._rewatch():  # D-532: a job its holder left unfinished is queued again
                        continue
                except Exception:
                    log.exception("worker error while looking at watched jobs")
                with self._wake:
                    self._wake.wait(timeout=2.0)
                continue
            try:
                self.run(jid)
            except Exception:  # never let a worker die
                log.exception("worker error on %s", jid)
                with self._wake:  # the same pause as an empty queue: a job put back is not taken in a tight loop
                    self._wake.wait(timeout=2.0)

    def drain(self, total: float | None = None) -> None:
        """Run queued jobs synchronously until the queue is empty (tests / CLI).

        A job that finishes is progress, however long it took: one screening job over 50,000 patients on the real
        model pair runs for hours (G1 of 2026-11-11 failed its first hospital part after 2.6 h because a finished
        job was measured against a 600 s window). A synchronous drain cannot see a job hang while it runs, so there
        is no stall window here; a hung job is stopped by the caller's own limit (the cloud run's watchdog and
        hard cap). ``total`` optionally caps the whole drain, checked after each finished job."""
        start = time.monotonic()
        while True:
            jid = self.db.claim()
            if jid is None:
                if self._rewatch():
                    continue
                return
            self.run(jid)
            if total is not None and time.monotonic() - start > total:
                raise TimeoutError("queue not drained")


def job_language(ctx: Ctx) -> str:
    """The job's language (D-100), see :meth:`Orchestrator.lang`."""
    return ctx.orch.lang(ctx.job)


def job_stamp(ctx: Ctx) -> str:
    """The timestamp written into evaluation outputs: the job's receipt in the site zone (not the wall clock), so a
    re-run of the same job on the same snapshot is byte-identical (SPEC §11.2 reproducibility)."""
    from zoneinfo import ZoneInfo

    return ctx.job.received_at.astimezone(ZoneInfo(ctx.cfg.env.tz)).isoformat(timespec="seconds")


def _subject(job: Job, kind: str, headline: str = "") -> str:
    return job_subject(kind, job.type, job.ruleset, job.job_id, headline)


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
