"""Identity assertions (spec v4 §9.4; HER-15): compact JWS, ES256, minted by channel-relay, verified here.

The relay signs one assertion per message with its P-256 key (held in the key service). Claims: ``sub`` (directory
principal), ``channel``, ``conv``, ``msg`` (message hash), ``aud`` = ``frontdoor-mcp``, ``iat``, ``exp`` (at most 5
minutes after ``iat``). The server checks the signature, the audience, the expiry and that ``conv`` matches the
calling session. Hermes never holds the signing key, so it cannot mint assertions.

Implemented with ``cryptography`` only (RFC 7515/7518: the ES256 signature is the 64-byte ``r || s``).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from pydantic import ValidationError
from tb_contracts.frontdoor import ASSERTION_MAX_TTL_S, AUDIENCE, IdentityAssertion

Clock = Callable[[], float]  # epoch seconds
_HEADER = {"alg": "ES256", "typ": "JWT", "kid": "relay-1"}


class AssertionRefused(PermissionError):
    """The assertion is missing, malformed, mis-signed, expired, for another audience or another conversation."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _json(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def generate_relay_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


class AssertionSigner:
    """The relay side. In production the private key never leaves the key service; tests hold it in memory."""

    def __init__(self, key: ec.EllipticCurvePrivateKey, clock: Clock, kid: str = "relay-1") -> None:
        self.key = key
        self.clock = clock
        self.kid = kid

    def mint(self, *, sub: str, channel: str, conv: str, msg: str, ttl_s: int = ASSERTION_MAX_TTL_S) -> str:
        now = int(self.clock())
        claims = IdentityAssertion.model_validate(
            {"sub": sub, "channel": channel, "conv": conv, "msg": msg, "aud": AUDIENCE, "iat": now, "exp": now + ttl_s}
        )
        header = {**_HEADER, "kid": self.kid}
        signing_input = f"{_b64(_json(header))}.{_b64(_json(claims.model_dump()))}".encode("ascii")
        der = self.key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return f"{signing_input.decode('ascii')}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


class AssertionVerifier:
    def __init__(self, public_key: ec.EllipticCurvePublicKey, clock: Clock, leeway_s: int = 5) -> None:
        self.public_key = public_key
        self.clock = clock
        self.leeway_s = leeway_s

    def verify(self, token: str | None, *, conv: str | None) -> IdentityAssertion:
        if not token:
            raise AssertionRefused("assertion_missing", "no identity assertion on the call")
        parts = token.split(".")
        if len(parts) != 3:
            raise AssertionRefused("assertion_malformed", "assertion is not a compact JWS")
        try:
            header = json.loads(_unb64(parts[0]))
            payload = json.loads(_unb64(parts[1]))
            sig = _unb64(parts[2])
        except (ValueError, UnicodeDecodeError) as e:
            raise AssertionRefused("assertion_malformed", "assertion does not decode") from e
        if not isinstance(header, dict) or header.get("alg") != "ES256":
            raise AssertionRefused("assertion_alg", "only ES256 assertions are accepted")
        if len(sig) != 64:
            raise AssertionRefused("assertion_signature", "bad signature length")
        der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
        try:
            self.public_key.verify(der, f"{parts[0]}.{parts[1]}".encode("ascii"), ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as e:
            raise AssertionRefused("assertion_signature", "assertion signature does not verify") from e
        try:
            claims = IdentityAssertion.model_validate(payload)
        except ValidationError as e:
            raise AssertionRefused("assertion_claims", "assertion claims are invalid") from e
        now = int(self.clock())
        if claims.aud != AUDIENCE:
            raise AssertionRefused("assertion_audience", f"assertion audience {claims.aud!r} is not {AUDIENCE}")
        if claims.exp - claims.iat > ASSERTION_MAX_TTL_S:
            raise AssertionRefused("assertion_ttl", "assertion lifetime exceeds 5 minutes")
        if now > claims.exp + self.leeway_s or claims.iat > now + self.leeway_s:
            raise AssertionRefused("assertion_expired", "assertion expired or not yet valid")
        if conv is None or claims.conv != conv:
            raise AssertionRefused("assertion_conv", "assertion is bound to another conversation")
        return claims
