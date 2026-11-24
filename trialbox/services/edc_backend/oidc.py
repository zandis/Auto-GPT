"""Optional OIDC issuer for the EDC (contract version 1). Off unless ``TB_EDC_OIDC`` is 1.

The EDC stores the issuer, the client id and the client secret, and maps ``sub`` to its own user. TrialBox's
console session is not the EDC's cookie. A code is single use, in any process: codes are kept in the trial database
(``edc_backend.store``, D-1044), each with the client and the redirect it was issued for.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.parse import urlencode

from edc_backend import store as door


def enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return (env.get("TB_EDC_OIDC") or "0").strip() in {"1", "true", "yes", "on"}


def issuer(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return (env.get("TB_EDC_OIDC_ISSUER") or "").strip().rstrip("/")


def client_id(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return (env.get("TB_EDC_OIDC_CLIENT_ID") or "").strip()


def client_secret(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return (env.get("TB_EDC_OIDC_CLIENT_SECRET") or "").strip()


def redirects(environ: dict[str, str] | None = None) -> set[str]:
    env = os.environ if environ is None else environ
    return {part.strip() for part in (env.get("TB_EDC_OIDC_REDIRECT") or "").split(",") if part.strip()}


def discovery(environ: dict[str, str] | None = None) -> dict[str, Any]:
    base = issuer(environ)
    root = base + "/api/edc/oidc"
    return {
        "issuer": base,
        "authorization_endpoint": root + "/authorize",
        "token_endpoint": root + "/token",
        "userinfo_endpoint": root + "/userinfo",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["HS256"],
    }


def issue_code(username: str, *, client_id: str = "", redirect_uri: str = "") -> str:
    """A code for ``username``, good once for :data:`edc_backend.store.CODE_S` seconds, in any process."""
    return door.default_store().issue_code(username, client_id=client_id, redirect_uri=redirect_uri)


def take_code(code: str) -> str | None:
    """The code's account, once; None for a code that is unknown, used or expired."""
    got = door.default_store().take_code(code)
    return got.username if got is not None else None


def redeem(code: str, client: str, redirect_uri: str) -> str | None:
    """D-1045: the code's account when ``client`` and ``redirect_uri`` are the ones it was issued for; None otherwise.
    The code is spent either way: a code is good for one attempt."""
    got = door.default_store().take_code(code)
    if got is None or not redirect_uri or not hmac.compare_digest(got.redirect_uri, redirect_uri):
        return None
    if not hmac.compare_digest(got.client_id, client):
        return None
    return got.username


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def sign_id_token(username: str, environ: dict[str, str] | None = None) -> str:
    if not client_secret(environ):  # an empty HMAC key would let anyone mint a token (Qwen4 review F-EDC-1)
        raise ValueError("TB_EDC_OIDC_CLIENT_SECRET is not set")
    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64(
        json.dumps(
            {"iss": issuer(environ), "sub": username, "aud": client_id(environ), "exp": int(time.time()) + 600},
            separators=(",", ":"),
        ).encode()
    )
    signing = f"{header}.{payload}".encode()
    sig = hmac.new(client_secret(environ).encode(), signing, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(sig)}"


def subject_of(token: str, environ: dict[str, str] | None = None) -> str | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    secret = client_secret(environ)
    if not secret:  # never verify under an empty key: a forged token would pass
        return None
    signing = f"{parts[0]}.{parts[1]}".encode()
    sig = hmac.new(secret.encode(), signing, hashlib.sha256).digest()
    pad = "=" * (-len(parts[2]) % 4)
    try:
        given = base64.urlsafe_b64decode(parts[2] + pad)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, given):
        return None
    try:
        body = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError:
        return None
    if str(body.get("aud") or "") != client_id(environ):
        return None
    if int(body.get("exp") or 0) < time.time():
        return None
    return str(body.get("sub") or "") or None


def secret_ok(given: str, environ: dict[str, str] | None = None) -> bool:
    secret = client_secret(environ)
    return bool(secret) and hmac.compare_digest(secret, given)


def authorize_redirect(username: str, redirect_uri: str, state: str, environ: dict[str, str] | None = None) -> str:
    if redirect_uri not in redirects(environ):
        raise ValueError("the redirect URI is not allowed")
    code = issue_code(username, client_id=client_id(environ), redirect_uri=redirect_uri)
    query = urlencode({"code": code, "state": state})
    sep = "&" if "?" in redirect_uri else "?"
    return f"{redirect_uri}{sep}{query}"
