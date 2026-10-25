"""What the console reads and calls. No side doors: every request the console starts is a ``JobCreate`` on the
orchestrator's ``POST /jobs``, the same call the mail gateway makes for an e-mail, so permissions
(``settings.permissions``), the per-sender rate limit, the job audit events and the delivery routing rule all apply
unchanged. The console adds its own audit events (``console.*``) to the same hash chain.

:class:`HttpBackend` is the compose wiring; the unit tests use an in-memory implementation of :class:`Backend`.
"""

from __future__ import annotations

import json
import smtplib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any, Protocol

import httpx
from tb_common.audit import AuditLog
from tb_common.config import Config
from tb_common.crypto import sha256_bytes
from tb_common.http import ServiceClient, ServiceError
from tb_common.objstore import ObjectStore
from tb_common.ruleset import RulesetNotApproved, list_rulesets, load_approved
from tb_contracts import Job, JobCreate, JobFile


class Refused(RuntimeError):
    """The orchestrator refused the request (permission, rate limit, invalid request)."""


class Unavailable(RuntimeError):
    """A service the console needs did not answer."""


@dataclass(frozen=True)
class MailItem:
    direction: str  # "in" | "out"
    at: str
    subject: str
    party: str  # sender (in) or recipients (out)
    tag: str  # aggregate | phi | job | reject | pending
    message_id: str
    note: str = ""


@dataclass(frozen=True)
class RulesetInfo:
    id: str
    version: str | None
    status: str
    kind: str


@dataclass(frozen=True)
class Health:
    service: str
    ok: bool
    detail: str = ""


@dataclass
class AuditRecord:
    ts: str
    event: str
    actor: str | None
    job_id: str | None
    ruleset: str | None
    hash: str
    detail: dict[str, Any] = field(default_factory=dict)


class Backend(Protocol):
    def list_jobs(self, limit: int = 100) -> list[Job]: ...
    def get_job(self, job_id: str) -> Job | None: ...
    def create_job(self, req: JobCreate) -> Job: ...
    def put_input(self, job_id: str, filename: str, data: bytes, content_type: str) -> JobFile: ...
    def get_object(self, key: str) -> bytes: ...
    def thread(self, job_id: str) -> list[MailItem]: ...
    def audit(self, job_id: str | None = None, limit: int = 200) -> list[AuditRecord]: ...
    def rulesets(self) -> list[RulesetInfo]: ...
    def health(self) -> list[Health]: ...
    def ingest(self) -> dict[str, Any]: ...
    def send_test_mail(self, sender: str, to: str, subject: str, body: str, files: list[tuple[str, bytes]]) -> str: ...


# ---------------------------------------------------------------------------------------------- audit reading
_SHOWN_DETAIL = ("from", "to", "type", "filename", "tag", "bytes", "subject", "reason", "action", "line", "role", "run")


def read_audit(directory: Path, job_id: str | None = None, limit: int = 200) -> list[AuditRecord]:
    """Newest first. Only metadata keys of ``detail`` are kept (no free text, no options payloads)."""
    out: deque[AuditRecord] = deque(maxlen=limit)
    files = sorted(directory.glob("*.jsonl")) if directory.is_dir() else []
    for path in files:
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if job_id and rec.get("job_id") != job_id:
                    continue
                det = rec.get("detail") or {}
                out.append(
                    AuditRecord(
                        ts=str(rec.get("ts", "")),
                        event=str(rec.get("event", "")),
                        actor=rec.get("actor"),
                        job_id=rec.get("job_id"),
                        ruleset=rec.get("ruleset"),
                        hash=str(rec.get("hash", ""))[:12],
                        detail={k: det[k] for k in _SHOWN_DETAIL if k in det and isinstance(det[k], str | int)},
                    )
                )
    return list(reversed(out))


def ruleset_infos(rulesets_dir: Path) -> list[RulesetInfo]:
    out = []
    for rid in list_rulesets(rulesets_dir):
        try:
            rs = load_approved(rulesets_dir, rid)
            out.append(RulesetInfo(rid, rs.version, "approved", str(rs.manifest.kind or "")))
        except (RulesetNotApproved, FileNotFoundError, ValueError):
            out.append(RulesetInfo(rid, None, "draft", ""))
    return out


# ---------------------------------------------------------------------------------------------- compose wiring
class HttpBackend:
    def __init__(
        self,
        cfg: Config,
        store: ObjectStore,
        audit: AuditLog,
        *,
        gateway_url: str = "",
        test_smtp: str = "",
    ) -> None:
        env = cfg.env
        self.cfg = cfg
        self.store = store
        self.audit_log = audit
        self.orch = ServiceClient(env.orchestrator_url, "orchestrator", timeout=60, retries=1)
        self.mail = ServiceClient(env.mail_gateway_url, "mail-gateway", timeout=15, retries=0)
        self.adapter = ServiceClient(env.adapter_url, "adapter", timeout=1800, retries=0, idempotent=False)
        self.gateway_url = gateway_url
        self.test_smtp = test_smtp
        self.services = {
            "orchestrator": env.orchestrator_url,
            "mail-gateway": env.mail_gateway_url,
            "doc-parser": env.doc_parser_url,
            "criteria-compiler": env.compiler_url,
            "lake": env.lake_url,
            "adapter": env.adapter_url,
        }
        if gateway_url:
            self.services["gateway"] = gateway_url.removesuffix("/v1")

    def list_jobs(self, limit: int = 100) -> list[Job]:
        try:
            data = self.orch.get_json(f"/jobs?limit={limit}")
        except ServiceError as exc:
            raise Unavailable(str(exc)) from exc
        return [Job.model_validate(j) for j in data]

    def get_job(self, job_id: str) -> Job | None:
        try:
            return self.orch.get(f"/jobs/{job_id}", Job)
        except ServiceError as exc:
            if exc.status == 404:
                return None
            raise Unavailable(str(exc)) from exc

    def create_job(self, req: JobCreate) -> Job:
        try:
            return self.orch.post("/jobs", req, Job)
        except ServiceError as exc:
            if exc.status in (400, 403, 422):
                try:
                    detail = str(json.loads(exc.detail).get("detail"))
                except (ValueError, AttributeError):
                    detail = exc.detail
                raise Refused(detail) from exc
            raise Unavailable(str(exc)) from exc

    def put_input(self, job_id: str, filename: str, data: bytes, content_type: str) -> JobFile:
        key = f"attachments/{job_id}/{filename}"
        self.store.put(key, data, content_type)
        return JobFile(filename=filename, sha256=sha256_bytes(data), minio_key=key, content_type=content_type)

    def get_object(self, key: str) -> bytes:
        return self.store.get(key)

    def thread(self, job_id: str) -> list[MailItem]:
        try:
            data = self.mail.get_json(f"/threads/{job_id}")
        except ServiceError:
            return []
        return [MailItem(**item) for item in data.get("items", [])]

    def audit(self, job_id: str | None = None, limit: int = 200) -> list[AuditRecord]:
        return read_audit(self.audit_log.directory, job_id, limit)

    def rulesets(self) -> list[RulesetInfo]:
        return ruleset_infos(self.cfg.env.rulesets_path)

    def health(self) -> list[Health]:
        def probe(item: tuple[str, str]) -> Health:
            name, base = item
            try:
                resp = httpx.get(f"{base.rstrip('/')}/healthz", timeout=4)
            except httpx.HTTPError as exc:
                return Health(name, False, type(exc).__name__)
            detail = ""
            try:
                checks = resp.json().get("checks", {})
                if name == "lake":
                    detail = f"snapshot {checks.get('snapshot', '?')}"
                elif name == "orchestrator":
                    detail = f"{checks.get('queued_or_running', 0)} queued or running"
            except ValueError:
                pass
            return Health(name, resp.status_code == 200, detail)

        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(probe, self.services.items()))

    def ingest(self) -> dict[str, Any]:
        from tb_common.timeutil import now

        snapshot = self.cfg.env.extra.get("TB_CONSOLE_SNAPSHOT") or (now(self.cfg.env.tz).date().isoformat())
        try:
            resp = self.adapter.post_raw("/run", {"source": "csv", "snapshot": snapshot})
        except ServiceError as exc:
            raise Unavailable(str(exc)) from exc
        report: dict[str, Any] = resp.json()
        return report

    def send_test_mail(self, sender: str, to: str, subject: str, body: str, files: list[tuple[str, bytes]]) -> str:
        """Test profile only (GreenMail): what a staff mail client would send. The ``Authentication-Results`` header
        stands in for the hospital MTA, exactly as ``tools/send_test_mail.py`` does."""
        if not self.test_smtp:
            raise Unavailable("no test mail server configured (TB_CONSOLE_TEST_SMTP)")
        host, _, port = self.test_smtp.partition(":")
        m = EmailMessage()
        domain = sender.rsplit("@", 1)[-1]
        m["From"] = sender
        m["To"] = to
        m["Subject"] = subject
        m["Message-ID"] = mid = make_msgid(domain=domain)
        authserv = self.cfg.env.extra.get("TB_MAIL_AUTHSERV_ID") or "mx." + to.rsplit("@", 1)[-1]
        m["Authentication-Results"] = f"{authserv}; spf=pass smtp.mailfrom={domain}; dkim=pass header.d={domain}"
        m.set_content(body or "Sent from the TrialBox console test mailbox.")
        for name, data in files:
            m.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
        try:
            with smtplib.SMTP(host, int(port or 25), timeout=30) as s:
                s.send_message(m)
        except OSError as exc:
            raise Unavailable(f"test mail server: {exc}") from exc
        return mid
