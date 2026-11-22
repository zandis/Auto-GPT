"""mail-gateway: IMAP intake loop + ``send`` (SPEC §4.1)."""

from __future__ import annotations

import contextlib
import imaplib
import logging
import smtplib
import socket
import threading
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from tb_common import patient_files
from tb_common.audit import AuditLog, mask_ids
from tb_common.config import Config
from tb_common.crypto import sha256_bytes
from tb_common.http import ServiceClient, ServiceError, trace_of
from tb_common.objstore import ObjectStore
from tb_common.timeutil import now
from tb_contracts import Job, JobCreate, SendRequest, SendResult

from mail_gateway import intake
from mail_gateway.outbound import NotSent, Transport, mail_statement, prepare
from mail_gateway.store import MailDB, SendUncertain

log = logging.getLogger("mail-gateway")
GENERIC = "This mailbox accepts requests only from authorised hospital addresses. Your message was not processed."
JobSink = Callable[[JobCreate], Job]
#: NEW-MAIL-1 (D-863): ``(job_id, the object keys a mail carries) -> current`` against the opt-out register; raises
#: :class:`NoSuchJob` for a job the orchestrator does not have
OutputsCurrent = Callable[[str, list[str]], bool]


class OptedOutSince(RuntimeError):
    """A job's outputs name a patient opted out since they were made: the mail is held, never sent (D-863)."""


def _orchestrator(base_url: str) -> ServiceClient:
    """The mail gateway's client of the orchestrator: one request is a job started, or one mail's files asked about."""
    return ServiceClient(base_url, "orchestrator", timeout=60, retries=1)


class NoSuchJob(LookupError):
    """D-863: the orchestrator has no such job (removed by retention, or never there): nothing can vouch for it."""


def http_outputs_current(base_url: str) -> OutputsCurrent:
    """D-863: the orchestrator's answer (``GET /jobs/{job_id}/outputs-current``), asked just before a send."""
    client = _orchestrator(base_url)

    def ask(job_id: str, keys: list[str]) -> bool:
        try:
            query = urlencode([("key", k) for k in keys])
            got = client._request("GET", f"/jobs/{job_id}/outputs-current?{query}").json()
        except ServiceError as exc:
            if exc.status == 404:
                raise NoSuchJob(job_id) from exc
            raise
        current = got.get("current") if isinstance(got, dict) else None
        if not isinstance(current, bool):
            raise RuntimeError("the orchestrator gave no yes or no")
        return current

    return ask


class OrchestratorDown(RuntimeError):
    pass


class JobRefused(RuntimeError):
    pass


def http_job_sink(base_url: str) -> JobSink:
    client = _orchestrator(base_url)

    def create(req: JobCreate) -> Job:
        try:
            return client.post("/jobs", req, Job)
        except ServiceError as exc:
            if exc.status in (400, 403, 422):
                raise JobRefused(exc.detail) from exc
            raise OrchestratorDown(str(exc)) from exc

    return create


#: D-863: the typed reasons of a mail held for the opt-out register
OPTED_OUT = patient_files.HELD  # the opt-out worker finds the held mail by it (its held_mail clear)
NO_ANSWER = "opt-out not checked: the orchestrator did not answer; not sent"
#: D-863: nothing can vouch for the files: no job named, no such job, or a file outside the job's own outputs
NO_JOB = "opt-out not checked: the files are not of a job the orchestrator has; not sent"

# the transport refused before the server accepted the message (D-127, F-02): safe to try again later
REFUSED_BEFORE_SENDING = (
    ConnectionRefusedError,
    socket.gaierror,
    smtplib.SMTPConnectError,
    smtplib.SMTPHeloError,
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPNotSupportedError,
)

# T-108c (D-401): the outbox. Back-off 1, 2, 4 ... minutes up to an hour between tries; after MAX_ATTEMPTS tries
# (about seven hours) the key is "failed" and waits for a person. A key in "sending" longer than SENDING_STALE_S belongs
# to a process that died (a send still running then is marked by its own end). A recipient over the daily limit waits
# LIMIT_WAIT_S.
RETRY_BASE_S = 60
RETRY_MAX_S = 3600
MAX_ATTEMPTS = 12
SENDING_STALE_S = 900
LIMIT_WAIT_S = 3600
PER_RECIPIENT_PER_DAY = 200  # TB_MAIL_PER_RECIPIENT_PER_DAY; 0: no limit
REPLIES_PER_SENDER_PER_DAY = 10  # refusal replies to one address in 24 hours (a mail loop gets no more)
HELD = ("queued", "uncertain", "failed", "dropped")


def permanent(exc: BaseException) -> bool:
    """A refusal that a later try will meet again (an SMTP 5xx): the key fails at once and waits for a person."""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [c for c, _ in exc.recipients.values()]
        return bool(codes) and all(int(c) >= 500 for c in codes)
    if isinstance(exc, smtplib.SMTPResponseException):
        return int(exc.smtp_code) >= 500
    return isinstance(exc, smtplib.SMTPNotSupportedError)


@dataclass(frozen=True)
class Outcome:
    """What one send did: ``sent``, ``duplicate`` (sent before), or held: ``queued``, ``failed``, ``uncertain``,
    ``dropped``. A held send is not an error for the caller: the job stays done and the mail waits (T-108c)."""

    result: SendResult
    state: str


@dataclass
class Gateway:
    cfg: Config
    store: ObjectStore
    db: MailDB
    audit: AuditLog
    transport: Transport
    jobs: JobSink
    secrets_dir: Path
    authserv_id: str = ""  # D-369 (SEC-11): empty means no Authentication-Results header is trusted (fails closed)
    allow_phi_zip: bool = False  # D-369 (OD-1): a patient file as a password zip only on a synthetic box (DEV, TEST)
    per_recipient_per_day: int = PER_RECIPIENT_PER_DAY  # T-108c: mails to one address in 24 hours; 0 = no limit
    #: D-863: asked before a job's patient-level files are sent; None (not wired) holds every such mail (fail closed)
    outputs_current: OutputsCurrent | None = None

    @property
    def sender(self) -> str:
        return self.cfg.env.mail_from_addr

    @property
    def mode(self) -> str:
        return self.cfg.settings.attachment_encryption or self.cfg.env.attach_password_mode

    # ------------------------------------------------------------------ outbound
    def send(self, req: SendRequest) -> SendResult:
        return self.deliver(req).result

    def _ts(self, delta_s: float = 0) -> str:
        return (now(self.cfg.env.tz) + timedelta(seconds=delta_s)).isoformat()

    def deliver(self, req: SendRequest) -> Outcome:
        """Send once per idempotency key (D-127). A send that fails is held, never left in ``sending`` (T-108c):
        ``queued`` when nothing can have left, ``uncertain`` when it may have, ``failed`` when refused for good."""
        key = req.idempotency_key or f"auto-{uuid.uuid4().hex}"  # a key-less send is tracked as well
        try:
            done = self.db.claim_send(key, req.job_id, self._ts())
        except SendUncertain:
            row = self.db.get(key)
            if row is not None and row.state == "sending" and row.at < self._ts(-SENDING_STALE_S):
                self._mark_stale()
                row = self.db.get(key)
            if row is None or row.state not in HELD or not row.result:
                raise  # in flight in another request right now (D-127): 409, never a second send
            self.audit.append("mail.duplicate_suppressed", job_id=req.job_id, detail={"key": key, "state": row.state})
            return Outcome(SendResult.model_validate_json(row.result), row.state)
        if done is not None:
            self.audit.append("mail.duplicate_suppressed", job_id=req.job_id, detail={"key": key})
            return Outcome(SendResult.model_validate_json(done), "duplicate")
        return self._attempt(req, key, None, 0, from_outbox=False)

    def _still_current(self, req: SendRequest) -> str:
        """NEW-MAIL-1 (D-863, the integrator's ruling): the one door of every send of a job's patient-level files (at
        publish, a queued try, a person's resend): the orchestrator is asked whether the files this mail carries are
        still current against the opt-out register. "" to send; else why not: the mail is held, never sent. A mail
        is patient-level as ``outbound.prepare`` judges it (its tag, or any file's). A mail of counts is not asked."""
        atts = req.attachments or []
        if not atts or (req.tag != "phi" and not any(a.tag == "phi" for a in atts)):
            return ""
        from tb_common import rc1_refusals

        try:  # R22-34 (D-1072): rc1 sends no mail with patient files on a PRODUCTION box; held, never sent
            rc1_refusals.check("patient_mail_and_downloads")
        except rc1_refusals.Rc1Refused as exc:
            return f"{exc}; not sent"  # names the key, which _attempt holds at once
        if not req.job_id or not all(a.minio_key.startswith(f"outputs/{req.job_id}/") for a in atts):
            return NO_JOB  # the review of D-863: the job asked about is the job whose files are sent
        if self.outputs_current is None:
            return f"{NO_ANSWER}: no way to ask"
        try:
            return "" if self.outputs_current(req.job_id, [a.minio_key for a in atts]) else OPTED_OUT
        except (NoSuchJob, KeyError):
            return NO_JOB
        except Exception as exc:
            return f"{NO_ANSWER}: {type(exc).__name__}"

    def _attempt(self, req: SendRequest, key: str, message_id: str | None, attempts: int, from_outbox: bool) -> Outcome:
        why = self._still_current(req)
        if why in (OPTED_OUT, NO_JOB) or "(rc1.patient_mail_and_downloads)" in why:  # a person decides (drop, resend)
            return self._hold(req, key, message_id or "", False, [], "failed", attempts, why)
        if why:  # not known now: tried again with back-off, counted, and failed for a person at the limit
            n = attempts + 1
            state = "failed" if n >= MAX_ATTEMPTS else "queued"
            return self._hold(req, key, message_id or "", False, [], state, n, why,
                              wait_s=min(RETRY_BASE_S * 2 ** (n - 1), RETRY_MAX_S))  # fmt: skip
        try:
            p = self._prepare(req, message_id)  # routing, encryption, attachments: nothing has left yet
        except Exception as exc:
            if not from_outbox:
                self.db.release_send(key)  # the request itself is wrong: the caller hears it (422)
                raise
            # the settings or the files changed while it waited: a person decides
            # D-704: the reason a person reads holds the error's type; the log has where it was raised
            log.error("mail held: prepare failed", extra={"key": key, **trace_of(exc)})
            return self._hold(req, key, message_id or "", False, [], "failed", attempts,
                              f"prepare: {type(exc).__name__}")  # fmt: skip
        over = self._over_limit(p.recipients)
        if over:  # T-108c: a recipient over the daily limit waits; the try is not counted
            return self._hold(req, key, p.message_id, p.encrypted, p.recipients, "queued", attempts,
                              f"recipient limit reached: {', '.join(over)}", wait_s=LIMIT_WAIT_S)  # fmt: skip
        try:
            self.transport(self.sender, p.recipients, p.data)
        except NotSent as exc:  # the transport says nothing can have left (DNS, connect, TLS, a refusal)
            return self._not_sent(req, key, p, attempts, exc.cause)
        except REFUSED_BEFORE_SENDING as exc:
            return self._not_sent(req, key, p, attempts, exc)
        except Exception as exc:  # the answer was lost: the message may have arrived; never resent automatically
            log.error("mail held: the answer was lost", extra={"key": key, **trace_of(exc)})
            return self._hold(req, key, p.message_id, p.encrypted, p.recipients, "uncertain", attempts + 1,
                              type(exc).__name__)  # fmt: skip
        # from here on the message has left: a failure makes the key "uncertain", never a second send
        try:
            res = self._after_main(req, p)
            self.db.finish_send(key, res.message_id, res.model_dump_json(), self._ts())
        except Exception as exc:
            log.error("mail held: failed after the message left", extra={"key": key, **trace_of(exc)})
            return self._hold(req, key, p.message_id, p.encrypted, p.recipients, "uncertain", attempts + 1,
                              f"after the message left: {type(exc).__name__}")  # fmt: skip
        return Outcome(res, "sent")

    def _not_sent(self, req: SendRequest, key: str, p: Any, attempts: int, exc: BaseException) -> Outcome:
        n = attempts + 1
        state = "failed" if permanent(exc) or n >= MAX_ATTEMPTS else "queued"
        wait = min(RETRY_BASE_S * 2 ** (n - 1), RETRY_MAX_S)
        return self._hold(req, key, p.message_id, p.encrypted, p.recipients, state, n, f"{type(exc).__name__}: {exc}",
                          wait_s=wait)  # fmt: skip

    def _hold(
        self,
        req: SendRequest,
        key: str,
        message_id: str,
        encrypted: bool,
        recipients: list[str],
        state: str,
        attempts: int,
        error: str,
        wait_s: float = 0,
    ) -> Outcome:
        res = SendResult(message_id=message_id, sent_to=[], encrypted=encrypted, password_sent=False, rejected=[])
        next_at = self._ts(wait_s) if state == "queued" else None
        error = " ".join(error.split())[:500]
        self.db.hold(key, state, request_json=req.model_dump_json(), message_id=message_id,
                     result_json=res.model_dump_json(), recipients=recipients, attempts=attempts, next_at=next_at,
                     error=error, at=self._ts())  # fmt: skip
        event = {"queued": "mail.deferred", "failed": "mail.failed", "uncertain": "mail.uncertain"}[state]
        self.audit.append(
            event,
            job_id=req.job_id,
            recipients=recipients,
            detail={"key": key, "message_id": message_id, "attempts": attempts, "next_at": next_at,
                    "error": mask_ids(error), "subject": mask_ids(req.subject)},
        )  # fmt: skip
        log.warning("mail %s %s (try %d): %s", key[:16], state, attempts, error)
        return Outcome(res, state)

    def _over_limit(self, recipients: list[str]) -> list[str]:
        if self.per_recipient_per_day <= 0:
            return []
        sent = self.db.sent_to_since(self._ts(-86400))
        return [r for r in recipients if sent.get(r, 0) >= self.per_recipient_per_day]

    def _mark_stale(self) -> list[str]:
        stale = self.db.stale_sending(self._ts(-SENDING_STALE_S))
        for k in stale:
            self.audit.append("mail.uncertain", detail={"key": k, "error": "the send never finished"})
        return stale

    def drain(self, force: bool = False, limit: int = 50) -> dict[str, int]:
        """One dispatcher pass (T-108c): stale ``sending`` keys become ``uncertain``; queued keys that are due (all of
        them with ``force``, ``trialbox mail resolve``) are tried again. Returns the outcome counts."""
        out: Counter[str] = Counter()
        out["stale"] = len(self._mark_stale())
        for key in self.db.due(None if force else self._ts(), limit):
            taken = self.db.take(key, self._ts())
            if taken is None:
                continue
            request, message_id, attempts = taken
            req = SendRequest.model_validate_json(request)
            out[self._attempt(req, key, message_id, attempts, from_outbox=True).state] += 1
        return {k: v for k, v in out.items() if v}

    def resolve(self, key: str, decision: str, actor: str) -> str:
        """A person's decision on a held key (``trialbox mail resolve KEY --sent|--resend|--drop``); audited."""
        before = self.db.resolve(key, decision, actor, self._ts())
        if before is None:
            row = self.db.get(key)
            raise KeyError(f"{key}: " + (f"is {row.state}, nothing to resolve" if row else "no such send key"))
        self.audit.append("mail.resolved", actor=actor, detail={"key": key, "from": before, "decision": decision})
        return before

    def _prepare(self, req: SendRequest, message_id: str | None = None) -> Any:
        return prepare(
            req,
            store=self.store,
            sender=self.sender,
            internal_domains=list(self.cfg.settings.internal_domains),
            mode=self.mode,
            smime_certs=dict(self.cfg.settings.smime_certs or {}),
            smime_dir=self.secrets_dir / "smime",
            tz=self.cfg.env.tz,
            link_base=self.cfg.env.extra.get("TB_CONSOLE_URL", ""),
            allow_phi_zip=self.allow_phi_zip,
            message_id=message_id,
        )

    def _after_main(self, req: SendRequest, p: Any) -> SendResult:
        for rcpt, pw in p.password_mails:  # separately, to the same recipient only
            self.transport(self.sender, [rcpt], pw)
        ts = now(self.cfg.env.tz).isoformat()
        self.db.record_sent(p.message_id, req.job_id, req.subject, p.recipients, req.tag, ts)
        self.audit.append(
            "mail.sent",
            job_id=req.job_id,
            recipients=p.recipients,
            output_sha=sha256_bytes(p.data),
            detail={
                "subject": mask_ids(req.subject),  # a reply quotes the request line (D-272, CR-016)
                "message_id": p.message_id,
                "tag": req.tag,
                "attachments": [a.filename for a in req.attachments or []],
                "encrypted": p.encrypted,
                "mode": self.mode if p.encrypted else None,
            },
        )
        return SendResult(
            message_id=p.message_id,
            sent_to=p.recipients,
            encrypted=p.encrypted,
            password_sent=bool(p.password_mails),
            rejected=[],
        )

    def _reply(self, m: intake.Inbound, text: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = m.sender
        subject = " ".join(m.subject.split())  # an encoded-word may decode to CR/LF, which no header may carry
        msg["Subject"] = f"Re: {subject}"[:200] if subject else "TrialBox"
        msg["Date"] = format_datetime(now(self.cfg.env.tz))
        msg["Message-ID"] = make_msgid(domain=self.sender.rsplit("@", 1)[-1])
        msg["In-Reply-To"] = m.message_id
        msg["Auto-Submitted"] = "auto-replied"
        msg.set_content(text.rstrip("\n") + "\n\n-- \n" + mail_statement(text) + "\n")  # TB-IU-01 C1 (T-116)
        try:
            self.transport(self.sender, [m.sender], bytes(msg))
        except (OSError, ValueError, NotSent) as exc:
            log.warning("reply to %s failed: %s", m.sender, exc)

    # ------------------------------------------------------------------ inbound
    def handle(self, raw: bytes) -> str | None:
        """Process one message; returns the IMAP folder to move it to, or None to retry later."""
        m = intake.read(raw, self.authserv_id)
        ts = now(self.cfg.env.tz)
        prev = self.db.intake(m.message_id)
        if prev is not None and prev[0] in ("job", "reject"):
            return "Processed" if prev[0] == "job" else "Rejected"  # already handled (duplicate delivery)
        d = intake.decide(m, self.cfg.settings, self.db, ts, self.cfg.env.mail_intake_addr)
        if d.action == "job" and d.job is not None:
            job_id = intake.new_job_id(self.db, m.message_id)
            self.db.record_intake(m.message_id, m.sender, ts.isoformat(), "pending", job_id)
            inputs = intake.store_inputs(self.store, job_id, m)
            req = d.job.model_copy(update={"job_id": job_id, "inputs": inputs})
            try:
                self.jobs(req)
            except OrchestratorDown as exc:
                log.warning("orchestrator unavailable, will retry %s: %s", m.message_id, exc)
                return None
            except JobRefused as exc:
                return self._reject(m, ts.isoformat(), f"request refused: {exc}", True, True)
            self.db.record_intake(m.message_id, m.sender, ts.isoformat(), "job", job_id, cmd=req.type)
            self.audit.append(
                "mail.received",
                ts=ts,
                job_id=job_id,
                actor=m.sender,
                input_sha=sha256_bytes(m.raw),
                # D-272 (CR-016): the request line in the subject is audited with its chart number masked
                detail={
                    "subject": mask_ids(m.subject),
                    "auth": m.auth_detail,
                    "attachments": [f.filename for f in inputs],
                },
            )
            return "Processed"
        return self._reject(m, ts.isoformat(), d.reason, d.reply, d.detailed_reply)

    def _reject(self, m: intake.Inbound, ts: str, reason: str, reply: bool, detailed: bool) -> str:
        self.db.record_intake(m.message_id, m.sender or "-", ts, "reject", None, reason)
        self.audit.append(
            "mail.rejected",
            actor=m.sender or None,
            input_sha=sha256_bytes(m.raw),
            detail={"reason": mask_ids(reason), "auth": m.auth_detail},
        )
        since = (datetime.fromisoformat(ts) - timedelta(days=1)).isoformat()
        if reply and self.db.rejects_since(m.sender, since) > REPLIES_PER_SENDER_PER_DAY:
            # T-108c: a mail loop or a flood gets no more refusal replies today; the refusal is still audited
            log.warning("no refusal reply to %s: over %d refusals today", m.sender, REPLIES_PER_SENDER_PER_DAY)
        elif reply:
            self._reply(m, f"TrialBox could not process your message: {reason.rstrip('.')}." if detailed else GENERIC)
        return "Rejected"

    # ------------------------------------------------------------------ IMAP
    def poll_once(self) -> int:
        env = self.cfg.env
        cls = imaplib.IMAP4_SSL if env.imap_ssl else imaplib.IMAP4
        conn = cls(env.imap_host, env.imap_port)
        n = 0
        try:
            conn.login(env.imap_user, env.imap_pass)
            conn.select("INBOX")
            typ, data = conn.uid("SEARCH", None, "UNSEEN")  # type: ignore[arg-type]
            if typ != "OK" or not data or not data[0]:
                return 0
            for uid in data[0].split():
                typ, got = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                if typ != "OK" or not got or not isinstance(got[0], tuple):
                    continue
                try:
                    folder = self.handle(bytes(got[0][1]))
                except Exception:  # one bad message must not stop the rest of the batch; retried next poll
                    log.exception("could not process message uid %s", uid.decode(errors="replace"))
                    continue
                if folder is None:
                    continue
                conn.create(folder)  # NO when it exists; harmless
                conn.uid("COPY", uid, folder)
                conn.uid("STORE", uid, "+FLAGS", "(\\Deleted \\Seen)")
                n += 1
            conn.expunge()
        finally:
            with contextlib.suppress(imaplib.IMAP4.error, OSError):
                conn.logout()
        return n

    def loop(self, stop: threading.Event, interval: float) -> None:
        while not stop.is_set():
            try:
                self.poll_once()
            except (imaplib.IMAP4.error, OSError) as exc:
                log.warning("IMAP poll failed: %s", exc)
            except Exception:
                log.exception("IMAP poll error")
            stop.wait(interval)
