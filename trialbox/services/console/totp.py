"""Time-based one-time passwords for local console accounts (D-192; RFC 6238 over RFC 4226, standard library only).

* HMAC-SHA1, 6 digits, 30-second steps: what every authenticator app (Google Authenticator, Microsoft Authenticator,
  FreeOTP, a hospital's hardware token) reads from an ``otpauth://totp/`` key without options.
* A code is accepted for the current step and one step either side (clock drift of up to 30 seconds).
* A step is used once: :func:`verify` returns the matched step and the caller stores it; a code of that step or an
  earlier one is a replay and is refused (RFC 6238 §5.2).
* The shared secret is stored encrypted (AES-256-GCM, the account name as associated data) under a key file that
  lives on the console volume, not in the database, so a copy of the database alone does not give the secrets.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from pathlib import Path
from urllib.parse import quote

from tb_common.crypto import aes_decrypt, aes_encrypt, load_or_create_key

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # steps either side of now
SECRET_BYTES = 20  # 160 bits, RFC 4226 §4 recommends at least 128
_AAD = b"tb-totp/1:"


def new_secret() -> str:
    """A random base32 secret (no padding), as authenticator apps expect it."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _key_bytes(secret_b32: str) -> bytes:
    s = secret_b32.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def hotp(secret_b32: str, counter: int, digits: int = DIGITS) -> str:
    """RFC 4226 HOTP value of ``counter``."""
    mac = hmac.new(_key_bytes(secret_b32), struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off : off + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code).zfill(digits)


def step_at(unix_seconds: float) -> int:
    return int(unix_seconds // STEP_SECONDS)


def totp(secret_b32: str, unix_seconds: float) -> str:
    return hotp(secret_b32, step_at(unix_seconds))


def clean_code(code: str) -> str:
    """The digits a person typed ("123 456", full-width digits from a Japanese IME) or "" when it is not a code."""
    raw = "".join(c for c in (code or "") if c not in " \u3000-")
    if not raw or not all(c.isdecimal() for c in raw):
        return ""
    digits = "".join(str(int(c)) for c in raw)  # int() folds full-width digits
    return digits if len(digits) == DIGITS else ""


def verify(secret_b32: str, code: str, unix_seconds: float, last_step: int | None) -> int | None:
    """The step the code matches (now, or one step either side), or None. A step at or before ``last_step`` (the last
    one accepted for this account) never matches: a code is good once."""
    got = clean_code(code)
    if not got:
        return None
    now = step_at(unix_seconds)
    found = None
    for step in range(now - WINDOW, now + WINDOW + 1):
        # compare every candidate (no early exit) so the time taken says nothing about which step matched
        if hmac.compare_digest(hotp(secret_b32, step), got) and (last_step is None or step > last_step):
            found = step if found is None else max(found, step)
    return found


def otpauth_uri(secret_b32: str, account: str, issuer: str = "TrialBox") -> str:
    """The key in the ``otpauth://`` form an authenticator app imports."""
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def grouped(secret_b32: str) -> str:
    """The secret in groups of four for typing by hand."""
    return " ".join(secret_b32[i : i + 4] for i in range(0, len(secret_b32), 4))


class SecretBox:
    """Encrypts TOTP secrets with the key in ``key_file`` (created 0600 on first use)."""

    def __init__(self, key_file: Path) -> None:
        self.key_file = key_file
        self._key: bytes | None = None

    def _k(self) -> bytes:
        if self._key is None:
            key = load_or_create_key(self.key_file, 32)
            if len(key) != 32:
                raise ValueError(f"{self.key_file}: a TOTP key file holds 32 bytes")
            self._key = key
        return self._key

    def seal(self, username: str, secret_b32: str) -> str:
        blob = aes_encrypt(self._k(), secret_b32.encode("ascii"), _AAD + username.encode("utf-8"))
        return "v1:" + base64.b64encode(blob).decode("ascii")

    def open(self, username: str, sealed: str) -> str:
        if not sealed.startswith("v1:"):
            raise ValueError("unknown TOTP secret format")
        blob = base64.b64decode(sealed[3:])
        return aes_decrypt(self._k(), blob, _AAD + username.encode("utf-8")).decode("ascii")
