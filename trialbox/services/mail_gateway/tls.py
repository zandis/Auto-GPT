"""TLS for the hospital's mail servers (H-137; the owner's decision on #639, 7156806411 item 6).

The SMTP relay's and the IMAP server's certificates are verified by default, against the system's public CAs plus the
hospital's own CA when one is mounted (``TB_EXTRA_CA``: :mod:`tb_common.extra_ca` points ``SSL_CERT_FILE`` at the
combined bundle at interpreter start, and :func:`ssl.create_default_context` reads it). Without a context, smtplib and
imaplib verify nothing (CERT_NONE, no host check), which is what this module ends.

One switch per server turns the check off: ``SMTP_TLS_VERIFY=false`` or ``IMAP_TLS_VERIFY=false``. Each start of the
mail gateway that runs with a switch off writes ``mail.tls_unverified``, and each start that talks to a server with no
TLS at all (``SMTP_STARTTLS=false`` on a port other than 465, ``IMAP_SSL=false``) writes ``mail.plaintext``.
"""

from __future__ import annotations

import ssl
from typing import Any, Protocol

SMTPS_PORT = 465  # implicit TLS; every other port uses STARTTLS when SMTP_STARTTLS is on


class _Audit(Protocol):
    def append(self, event: str, **fields: Any) -> Any: ...


def context(verify: bool) -> ssl.SSLContext:
    """The TLS context for one mail server: the certificate and the host name checked, unless the switch is off."""
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def smtp_mode(port: int, starttls: bool, verify: bool) -> str:
    """``verified``, ``unverified`` or ``plaintext``: how the relay is spoken to."""
    if port != SMTPS_PORT and not starttls:
        return "plaintext"
    return "verified" if verify else "unverified"


def imap_mode(use_ssl: bool, verify: bool) -> str:
    if not use_ssl:
        return "plaintext"
    return "verified" if verify else "unverified"


#: the setting that leaves a server unverified or without TLS (the integrator's ruling 7165038321, item 4)
SETTING = {
    ("smtp", "unverified"): "SMTP_TLS_VERIFY=false",
    ("smtp", "plaintext"): "SMTP_STARTTLS=false",
    ("imap", "unverified"): "IMAP_TLS_VERIFY=false",
    ("imap", "plaintext"): "IMAP_SSL=false",
}


def unverified(env: Any, *, imap_used: bool) -> list[tuple[str, str, str, str]]:
    """(server, host, mode, setting) for each server spoken to without a verified certificate."""
    servers = [("smtp", env.smtp_host, smtp_mode(env.smtp_port, env.smtp_starttls, env.smtp_tls_verify))]
    if imap_used:
        servers.append(("imap", env.imap_host, imap_mode(env.imap_ssl, env.imap_tls_verify)))
    return [(s, h, m, SETTING[(s, m)]) for s, h, m in servers if m != "verified"]


def audit_modes(audit: _Audit, env: Any, *, imap_used: bool) -> list[str]:
    """One audit event per server the gateway speaks to without a verified certificate, naming the server, its host
    and the setting that caused it; returns the events written. Called once at each start of the gateway (the switch
    is read then, and holds until the next start)."""
    written = []
    for server, host, mode, setting in unverified(env, imap_used=imap_used):
        event = "mail.tls_unverified" if mode == "unverified" else "mail.plaintext"
        audit.append(event, detail={"server": server, "host": host, "setting": setting})
        written.append(event)
    return written
