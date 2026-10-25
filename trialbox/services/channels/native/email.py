"""Native email channel (spec v4 §3.4.1; S1-10): wraps the v1 mail gateway's inbound rules.

Inbound uses ``mail_gateway.intake.read`` unchanged: the top-most ``Authentication-Results`` header with the pinned
``authserv-id`` decides DMARC alignment, and attachments keep their safe names. The sender becomes a directory
principal only if it authenticated and is on the directory allowlist (generated from directory groups, HER-16).
Outbound uses the v1 transport signature ``(sender, recipients, bytes)``: ``mail_gateway.outbound.smtp_transport``
in a deployment (MailHog in the test stack), an in-memory list in unit tests.
"""

from __future__ import annotations

from collections.abc import Callable
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import make_msgid

from mail_gateway.intake import read
from mail_gateway.outbound import Transport
from tb_common.crypto import sha256_bytes

from channels.base import Attachment, Channel, InboundMessage, OutboundMessage

Lookup = Callable[[str], str | None]  # mail address -> directory principal (None: not on the allowlist)


def _body_text(raw: bytes) -> str:
    msg = message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    part = msg.get_body(preferencelist=("plain",))
    if part is None:
        return ""
    content = part.get_content()
    return content if isinstance(content, str) else ""


class EmailChannel(Channel):
    name = "email"
    phi_tolerant = True
    accepts_approvals = True  # Level A approvals are email-only (FR-SIG-8)

    def __init__(
        self,
        transport: Transport,
        *,
        sender_address: str,
        lookup: Lookup,
        authserv_id: str = "",
        domain: str = "trialbox.invalid",
    ) -> None:
        self.transport = transport
        self.sender_address = sender_address
        self.lookup = lookup
        self.authserv_id = authserv_id
        self.domain = domain

    def parse(self, raw: bytes) -> InboundMessage:
        m = read(raw, self.authserv_id)
        principal = self.lookup(m.sender) if m.auth_ok and m.sender else None
        atts = tuple(
            Attachment(name, ctype, sha256_bytes(data), len(data), data) for name, data, ctype in m.attachments
        )
        return InboundMessage(
            channel="email",
            message_id=m.message_id,
            sender=m.sender,
            principal=principal,
            auth_ok=m.auth_ok,
            auth_detail=m.auth_detail,
            subject=m.subject,
            text=_body_text(raw),
            thread_ref=m.in_reply_to,
            attachments=atts,
            raw_sha256=sha256_bytes(raw),
        )

    def send(self, out: OutboundMessage) -> str:
        msg = EmailMessage()
        mid = make_msgid(domain=self.domain)
        msg["From"] = self.sender_address
        msg["To"] = out.to
        msg["Subject"] = out.subject
        msg["Message-ID"] = mid
        if out.in_reply_to:
            msg["In-Reply-To"] = out.in_reply_to
            msg["References"] = out.in_reply_to
        msg.set_content(out.text)
        self.transport(self.sender_address, [out.to], msg.as_bytes())
        return mid
