"""Trust a hospital's TLS-inspection CA at run time (stress test #21).

Hospitals that inspect outbound TLS re-sign every certificate with their own CA, so calls to a model endpoint, the
public registry or the mail server fail with CERTIFICATE_VERIFY_FAILED. The build secret ``extra_ca`` only helps pip.
At interpreter start (``sitecustomize``) :func:`install` appends the PEM at ``TB_EXTRA_CA_FILE`` (default
``/run/tb-extra-ca.pem``, mounted by compose from ``TB_EXTRA_CA``; empty when unset) to the public CA bundle in a
temporary file and points ``SSL_CERT_FILE`` at it, which httpx, urllib, smtplib and imaplib all honour. The public
CAs stay trusted; nothing changes when no certificate is mounted.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

DEFAULT_PATH = "/run/tb-extra-ca.pem"
BUNDLE_NAME = "tb-ca-bundle.pem"


def install(environ: MutableMapping[str, str] | None = None, tmpdir: str | None = None) -> str | None:
    """Write the combined bundle and set ``SSL_CERT_FILE``; returns its path, or ``None`` when there is no CA."""
    env = os.environ if environ is None else environ
    try:
        extra = Path(env.get("TB_EXTRA_CA_FILE") or DEFAULT_PATH).read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    if "-----BEGIN CERTIFICATE-----" not in extra:
        return None
    try:
        import certifi

        base = Path(env.get("SSL_CERT_FILE") or certifi.where()).read_text(encoding="ascii", errors="replace")
    except (ImportError, OSError):
        base = ""
    tmp = tmpdir or env.get("TMPDIR") or "/tmp"  # noqa: S108 (tmpfs; the bundle holds public certificates only)
    out = Path(tmp) / BUNDLE_NAME
    try:
        out.write_text(base.rstrip() + "\n" + extra.strip() + "\n", encoding="ascii", errors="replace")
    except OSError:
        return None
    env["SSL_CERT_FILE"] = str(out)
    env["REQUESTS_CA_BUNDLE"] = str(out)
    return str(out)
