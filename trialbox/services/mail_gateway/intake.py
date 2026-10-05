"""Inbound mail (SPEC §4.1): sender allowlist, SPF/DKIM (``Authentication-Results``), subject grammar (§5),
permissions, rate limit, attachments -> object store, job creation request."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from typing import Any, cast

from tb_common.authz import allowed, known_senders, norm
from tb_common.crypto import sha256_bytes
from tb_common.objstore import ObjectStore
from tb_common.subject import Subject, SubjectError, parse_subject
from tb_common.ulid import new_ulid
from tb_contracts import JobCreate, JobFile, Settings

from mail_gateway.store import MailDB

MAX_ATTACHMENTS = 20
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
_RESULT = re.compile(r"^\s*(spf|dkim|dmarc)\s*=\s*([a-z]+)\b(.*)$", re.I | re.S)
_PROP = re.compile(r"\b(smtp\.mailfrom|header\.d|header\.i|header\.from)\s*=\s*([^\s;()]+)", re.I)


@dataclass
class Inbound:
    raw: bytes
    message_id: str
    sender: str
    subject: str
    in_reply_to: str | None
    auth_ok: bool
    auth_detail: str
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)


@dataclass
class Decision:
    action: str  # job | reject
    reason: str = ""
    detailed_reply: bool = True  # False for unknown senders (no system details)
    reply: bool = True
    job: JobCreate | None = None
    subject: Subject | None = None


def _domain(value: str) -> str:
    return value.rsplit("@", 1)[-1].strip().strip(".<>").lower()


def aligned(auth_domain: str, from_domain: str) -> bool:
    """DMARC relaxed alignment, approximated without the public-suffix list: the same domain, or one a subdomain of
    the other (mail.hospa.test ~ hospa.test)."""
    a, f = _domain(auth_domain), _domain(from_domain)
    return bool(a and f) and (a == f or a.endswith("." + f) or f.endswith("." + a))


def authentication(msg: EmailMessage, authserv_id: str = "", sender: str = "") -> tuple[bool, str]:
    """The top-most ``Authentication-Results`` header (added by our MTA, RFC 8601) decides. It passes on
    ``dmarc=pass``, or on an ``spf=pass`` / ``dkim=pass`` whose domain (``smtp.mailfrom`` / ``header.d``) is aligned
    with the From: domain of ``sender`` — a pass for some other domain proves nothing about the From: address — and
    never with ``dmarc=fail``. With ``authserv_id`` set, a header from any other server is ignored (forged headers
    the sender put further down)."""
    headers = msg.get_all("Authentication-Results") or []
    for h in headers:
        text = str(h)
        server, _, rest = text.partition(";")
        if authserv_id and server.strip().lower() != authserv_id.lower():
            continue
        results: list[tuple[str, str, dict[str, str]]] = []
        for clause in rest.split(";"):
            m = _RESULT.match(clause)
            if m:
                props = {k.lower(): v for k, v in _PROP.findall(m.group(3))}
                results.append((m.group(1).lower(), m.group(2).lower(), props))
        if not results:
            return False, "no results"
        dmarc = {r for meth, r, _ in results if meth == "dmarc"}
        passes = []
        for meth, res, props in results:
            if res != "pass" or meth == "dmarc":
                continue
            dom = (
                props.get("smtp.mailfrom", "") if meth == "spf" else props.get("header.d") or props.get("header.i", "")
            )
            if aligned(dom, sender):
                passes.append(meth)
        ok = "fail" not in dmarc and ("pass" in dmarc or bool(passes))
        detail = ", ".join(sorted(f"{meth}={res}" for meth, res, _ in results))
        if not ok and not dmarc and any(r == "pass" for _, r, _ in results):
            detail += f" (no pass aligned with {_domain(sender) or 'the From: domain'})"
        return ok, detail
    return False, "no Authentication-Results header"


def _safe_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[^\w.\-㐀-鿿]+", "_", name).strip("._") or "attachment"
    base = base[-120:]
    out, n = base, 1
    while out.lower() in used or out.lower() == "message.eml":
        n += 1
        stem, dot, ext = base.rpartition(".")
        out = f"{stem}_{n}.{ext}" if dot else f"{base}_{n}"
    used.add(out.lower())
    return out


def read(raw: bytes, authserv_id: str = "") -> Inbound:
    msg = message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    sender = norm(parseaddr(str(msg.get("From", "")))[1])
    mid = str(msg.get("Message-ID", "")).strip() or f"<no-id-{sha256_bytes(raw)[:24]}@trialbox>"
    irt = str(msg.get("In-Reply-To", "")).strip() or None
    ok, detail = authentication(msg, authserv_id, sender)
    atts: list[tuple[str, bytes, str]] = []
    used: set[str] = set()
    for part in msg.iter_attachments():
        fname = part.get_filename()
        if not fname:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        atts.append((_safe_name(fname, used), payload, part.get_content_type()))
    return Inbound(raw, mid, sender, str(msg.get("Subject", "")).strip(), irt, ok, detail, atts)


def decide(m: Inbound, settings: Settings, db: MailDB, now: datetime, intake_addr: str = "") -> Decision:
    if m.sender == norm(intake_addr) or not m.sender:
        return Decision("reject", "loop or empty sender", reply=False)
    if m.sender not in known_senders(settings):
        # unknown senders get a generic reply, and only when the domain authenticated (no backscatter)
        return Decision("reject", "sender not on the allowlist", detailed_reply=False, reply=m.auth_ok)
    if settings.require_spf_dkim is not False and not m.auth_ok:
        return Decision("reject", f"sender authentication failed ({m.auth_detail})")
    try:
        subj = parse_subject(m.subject)
    except SubjectError as exc:
        subj = None
        if m.in_reply_to:  # reply-to-thread on a review mail: the original subject carries the APPROVE command
            hit = db.sent(m.in_reply_to)
            if hit is not None:
                try:
                    subj = parse_subject(hit[1])
                except SubjectError:
                    subj = None
        if subj is None:
            return Decision(
                "reject",
                f"{exc}. Use e.g. 'FEAS GZQO lookback=36', 'SCREEN GZQO version=1.0.0', 'NAV RA-BIO dept=RHEU', "
                f"'APPROVE GZQO version=1.0.0', 'STATUS <job id>'.",
            )
    assert subj is not None
    if not allowed(settings, subj.cmd, m.sender):
        return Decision("reject", f"{m.sender} is not permitted to send {subj.cmd}", subject=subj)
    limit = settings.rate_limit_per_sender_per_day or 20
    if db.jobs_since(m.sender, (now - timedelta(days=1)).isoformat()) >= limit:
        return Decision("reject", f"daily limit of {limit} requests reached; try again tomorrow", subject=subj)
    if len(m.attachments) > MAX_ATTACHMENTS or any(len(b) > MAX_ATTACHMENT_BYTES for _, b, _ in m.attachments):
        return Decision(
            "reject", f"too many or too large attachments (max {MAX_ATTACHMENTS}, 50 MB each)", subject=subj
        )
    options = dict(subj.options)
    ruleset: str | None = subj.ruleset
    if subj.job_id:
        options["target"] = subj.job_id
        ruleset = None
    job = JobCreate(
        type=cast(Any, subj.cmd),
        ruleset=ruleset,
        options=options,
        comment=subj.comment,
        requested_by=m.sender,
        message_id=m.message_id,
        in_reply_to=m.in_reply_to,
    )
    return Decision("job", job=job, subject=subj)


def store_inputs(store: ObjectStore, job_id: str, m: Inbound) -> list[JobFile]:
    """Raw .eml + every attachment under ``attachments/<job_id>/`` with sha256 (SPEC §4.1)."""
    store.put(f"attachments/{job_id}/message.eml", m.raw, "message/rfc822")
    files = []
    for name, data, ctype in m.attachments:
        key = f"attachments/{job_id}/{name}"
        store.put(key, data, ctype)
        files.append(JobFile(filename=name, sha256=sha256_bytes(data), minio_key=key, content_type=ctype))
    return files


def new_job_id(db: MailDB, message_id: str) -> str:
    """Reuse the id allocated for this Message-ID (retry after an orchestrator outage), else a new ULID."""
    prev = db.intake(message_id)
    return prev[1] if prev and prev[1] else new_ulid()


def recipients(msg: EmailMessage) -> list[str]:
    return [norm(a) for _, a in getaddresses([str(v) for v in msg.get_all("To", []) + msg.get_all("Cc", [])])]
