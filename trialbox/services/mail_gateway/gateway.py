"""mail-gateway: IMAP intake loop + ``send`` (SPEC §4.1)."""

from __future__ import annotations

import contextlib
import imaplib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

from tb_common.audit import AuditLog
from tb_common.config import Config
from tb_common.crypto import sha256_bytes
from tb_common.http import ServiceClient, ServiceError
from tb_common.objstore import ObjectStore
from tb_common.timeutil import now
from tb_contracts import Job, JobCreate, SendRequest, SendResult

from mail_gateway import intake
from mail_gateway.outbound import Transport, prepare
from mail_gateway.store import MailDB

log = logging.getLogger("mail-gateway")
GENERIC = "This mailbox accepts requests only from authorised hospital addresses. Your message was not processed."
JobSink = Callable[[JobCreate], Job]


class OrchestratorDown(RuntimeError):
    pass


class JobRefused(RuntimeError):
    pass


def http_job_sink(base_url: str) -> JobSink:
    client = ServiceClient(base_url, "orchestrator", timeout=60, retries=1)

    def create(req: JobCreate) -> Job:
        try:
            return client.post("/jobs", req, Job)
        except ServiceError as exc:
            if exc.status in (400, 403, 422):
                raise JobRefused(exc.detail) from exc
            raise OrchestratorDown(str(exc)) from exc

    return create


@dataclass
class Gateway:
    cfg: Config
    store: ObjectStore
    db: MailDB
    audit: AuditLog
    transport: Transport
    jobs: JobSink
    secrets_dir: Path
    authserv_id: str = ""

    @property
    def sender(self) -> str:
        return self.cfg.env.mail_from_addr

    @property
    def mode(self) -> str:
        return self.cfg.settings.attachment_encryption or self.cfg.env.attach_password_mode

    # ------------------------------------------------------------------ outbound
    def send(self, req: SendRequest) -> SendResult:
        p = prepare(
            req,
            store=self.store,
            sender=self.sender,
            internal_domains=list(self.cfg.settings.internal_domains),
            mode=self.mode,
            smime_certs=dict(self.cfg.settings.smime_certs or {}),
            smime_dir=self.secrets_dir / "smime",
            tz=self.cfg.env.tz,
        )
        self.transport(self.sender, p.recipients, p.data)
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
                "subject": req.subject,
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
        msg["Subject"] = f"Re: {m.subject}"[:200] if m.subject else "TrialBox"
        msg["Date"] = format_datetime(now(self.cfg.env.tz))
        msg["Message-ID"] = make_msgid(domain=self.sender.rsplit("@", 1)[-1])
        msg["In-Reply-To"] = m.message_id
        msg["Auto-Submitted"] = "auto-replied"
        msg.set_content(text)
        try:
            self.transport(self.sender, [m.sender], bytes(msg))
        except OSError as exc:
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
            self.db.record_intake(m.message_id, m.sender, ts.isoformat(), "job", job_id)
            self.audit.append(
                "mail.received",
                ts=ts,
                job_id=job_id,
                actor=m.sender,
                input_sha=sha256_bytes(m.raw),
                detail={"subject": m.subject, "auth": m.auth_detail, "attachments": [f.filename for f in inputs]},
            )
            return "Processed"
        return self._reject(m, ts.isoformat(), d.reason, d.reply, d.detailed_reply)

    def _reject(self, m: intake.Inbound, ts: str, reason: str, reply: bool, detailed: bool) -> str:
        self.db.record_intake(m.message_id, m.sender or "-", ts, "reject", None, reason)
        self.audit.append(
            "mail.rejected",
            actor=m.sender or None,
            input_sha=sha256_bytes(m.raw),
            detail={"reason": reason, "auth": m.auth_detail},
        )
        if reply:
            self._reply(m, f"TrialBox could not process your message: {reason}." if detailed else GENERIC)
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
                folder = self.handle(bytes(got[0][1]))
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
