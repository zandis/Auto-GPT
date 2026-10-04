"""Outbound mail (SPEC §4.1): Markdown body -> text + HTML, attachments from the object store, routing enforcement,
encryption of PHI attachments (7z AES-256 with a separately mailed password, or S/MIME sign + encrypt)."""

from __future__ import annotations

import io
import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage, Message
from email.utils import format_datetime, make_msgid
from pathlib import Path

import markdown
from tb_common.authz import norm
from tb_common.crypto import random_password
from tb_common.objstore import ObjectStore
from tb_common.routing import is_internal
from tb_common.timeutil import now
from tb_contracts import SendRequest

Transport = Callable[[str, list[str], bytes], None]
HTML_WRAP = (
    '<!doctype html><html><head><meta charset="utf-8"></head><body style="font-family:\'Noto Sans TC\',Arial,'
    'sans-serif;font-size:14px">{body}<hr><p style="color:#777;font-size:11px">TrialBox · automated message · '
    "do not forward outside the hospital unless the content is aggregate.</p></body></html>"
)


class RoutingRefused(RuntimeError):
    pass


class EncryptionError(RuntimeError):
    pass


@dataclass
class Prepared:
    message_id: str
    recipients: list[str]
    data: bytes
    encrypted: bool
    password_mails: list[tuple[str, bytes]]  # (recipient, message bytes)


def smtp_transport(host: str, port: int, user: str = "", password: str = "", starttls: bool = True) -> Transport:
    def send(sender: str, to: list[str], data: bytes) -> None:
        cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with cls(host, port, timeout=60) as s:
            if starttls and cls is smtplib.SMTP:
                s.starttls()
            if user:
                s.login(user, password)
            s.sendmail(sender, to, data)

    return send


def render_body(body_md: str) -> tuple[str, str]:
    html = markdown.markdown(body_md, extensions=["tables", "fenced_code", "sane_lists"])
    return body_md, HTML_WRAP.format(body=html)


def seven_zip(files: list[tuple[str, bytes]], password: str) -> bytes:
    import py7zr

    buf = io.BytesIO()
    with py7zr.SevenZipFile(buf, "w", password=password, header_encryption=True) as z:
        for name, data in files:
            z.writestr(data, name)
    return buf.getvalue()


def smime_wrap(inner: Message, recipients: list[str], certs: dict[str, str], signer_dir: Path) -> bytes:
    """CMS sign (site certificate) then encrypt (AES-256-CBC) for every recipient certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.ciphers import algorithms
    from cryptography.hazmat.primitives.serialization import pkcs7

    crt, key = signer_dir / "site.crt", signer_dir / "site.key"
    if not crt.exists() or not key.exists():
        raise EncryptionError(f"S/MIME signing certificate missing ({crt}, {key})")
    signer = x509.load_pem_x509_certificate(crt.read_bytes())
    pkey = serialization.load_pem_private_key(key.read_bytes(), password=None)
    signed = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(inner.as_bytes(policy=policy.SMTP))
        .add_signer(signer, pkey, hashes.SHA256())  # type: ignore[arg-type]
        .sign(serialization.Encoding.SMIME, [pkcs7.PKCS7Options.DetachedSignature])
    )
    env = pkcs7.PKCS7EnvelopeBuilder().set_data(signed).set_content_encryption_algorithm(algorithms.AES256)
    for r in recipients:
        path = certs.get(r)
        if not path or not Path(path).exists():
            raise EncryptionError(f"no S/MIME certificate configured for {r}")
        env = env.add_recipient(x509.load_pem_x509_certificate(Path(path).read_bytes()))
    return env.encrypt(serialization.Encoding.SMIME, [])


def prepare(
    req: SendRequest,
    *,
    store: ObjectStore,
    sender: str,
    internal_domains: list[str],
    mode: str = "zip",
    smime_certs: dict[str, str] | None = None,
    smime_dir: Path | None = None,
    tz: str = "Asia/Taipei",
) -> Prepared:
    to = sorted({norm(r) for r in req.to if r})
    if not to:
        raise RoutingRefused("no recipients")
    atts = req.attachments or []
    phi = req.tag == "phi" or any(a.tag == "phi" for a in atts)
    external = [r for r in to if not is_internal(r, internal_domains)]
    if phi and external:  # SPEC §4.1: outside internal domains only aggregate outputs
        raise RoutingRefused(
            f"phi content may not be sent outside {', '.join(internal_domains)}: {', '.join(external)}"
        )
    encrypt = bool(atts) and (req.encrypt or phi)
    domain = sender.rsplit("@", 1)[-1] or "trialbox.local"
    mid = make_msgid(idstring=(req.job_id or "trialbox")[:26], domain=domain)
    text, html = render_body(req.body_md)
    files = [(a.filename, store.get(a.minio_key)) for a in atts]

    def headers(m: Message, subject: str, rcpt: list[str], msg_id: str) -> None:
        m["From"] = sender
        m["To"] = ", ".join(rcpt)
        m["Subject"] = subject
        m["Date"] = format_datetime(now(tz))
        m["Message-ID"] = msg_id
        m["Auto-Submitted"] = "auto-replied" if req.in_reply_to else "auto-generated"
        if req.job_id:
            m["X-TrialBox-Job"] = req.job_id
        if req.in_reply_to:
            m["In-Reply-To"] = req.in_reply_to
            m["References"] = req.in_reply_to

    body = EmailMessage()
    body.set_content(text)
    body.add_alternative(html, subtype="html")
    password_mails: list[tuple[str, bytes]] = []
    if encrypt and mode == "zip":
        password = random_password(20)
        archive = seven_zip(files, password)
        body.add_attachment(
            archive, maintype="application", subtype="x-7z-compressed", filename=f"{req.job_id or 'trialbox'}.7z"
        )
        for r in to:
            pm = EmailMessage()
            pm.set_content(
                f"Password for the encrypted attachment of '{req.subject}' (message {mid}):\n\n    {password}\n\n"
                "Sent separately; do not forward."
            )
            headers(pm, f"Password — {req.subject}", [r], make_msgid(idstring="pw", domain=domain))
            password_mails.append((r, pm.as_bytes(policy=policy.SMTP)))
    else:
        for name, data in files:
            maintype, _, subtype = _ctype(name).partition("/")
            body.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    if encrypt and mode == "smime":
        wrapped = message_from_bytes(
            smime_wrap(body, to, smime_certs or {}, smime_dir or Path("/run/secrets/trialbox/smime")),
            policy=policy.SMTP,
        )
        headers(wrapped, req.subject, to, mid)
        data = wrapped.as_bytes(policy=policy.SMTP)
    else:
        headers(body, req.subject, to, mid)
        data = body.as_bytes(policy=policy.SMTP)
    return Prepared(mid, to, data, encrypt, password_mails)


def _ctype(name: str) -> str:
    import mimetypes

    return mimetypes.guess_type(name)[0] or "application/octet-stream"
