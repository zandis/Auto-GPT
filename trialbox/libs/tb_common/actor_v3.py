"""Actor assertion v3 (T-715, D-483): who acts, by which right, on which request.

The v2 assertion (``tb_common.service_auth``, D-143, D-447) signs a name, a session, a role and a study list. A
callee that verified it still had to believe everything else: that the person was allowed this action, in this
study, with this body. v3 is one signed claim per request:

==============  =====================================================================================
``sub``         the verified person (``console:<username>``), or a service principal (``service:...``)
``role``        the account's role in the matrix (``tb_common.authz``); ``service`` for a principal
``session``     the console session (the first characters of the session token's hash)
``study``       exactly one study, or "" for an action of the whole box
``standing``    the account's standing in that study from the delegation log (PI, ticked tasks, ...)
``action``      the row of ``authz_matrix.yaml`` the console permitted
``target``      the request it is for: ``METHOD path?query``
``grant``       a break-glass grant (id, kind, pid or job, end) when the right rests on one, else null
``reauth_at``   when the person typed the password again for this action (epoch seconds), else null
``body``        the sha256 of the request body's bytes
``nonce``       random; an assertion is accepted once (``service_auth.ReplayGuard``)
``iat, exp``    issued at, and two minutes later
==============  =====================================================================================

Wire form, in ``X-TB-Actor-Assertion``: ``v3.<base64url(JSON)>.<hex HMAC-SHA256>``, the MAC over ``v3.<base64url>``
with the console's actor key (the key v2 uses; T-717 gives it a file of its own). The claim is the whole message:
no second header names the person, so nothing unsigned can disagree with it.

A box with no token at all (DEV and TEST, ``actor_keys()`` is None) verifies no MAC, as v2 did there; the claim is
still parsed and its expiry, action, study, target and body are still checked, so a test of the one path runs it.

The console mints in one place (``console.identity.assert_for``); the orchestrator checks with one dependency
(``orchestrator.actor.require_actor``). This module is the format and its two functions, and holds no policy.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

from tb_common import service_auth as sa
from tb_common.authz import Standing

VERSION = "v3"
HEADER = sa.ASSERTION_HEADER
SERVICE_ROLE = "service"  # a principal with no person behind it (a console timer); never a matrix role
_SUB = re.compile(r"^(console|service):[^\s\x00-\x1f]{1,120}$")
_ROLE = re.compile(r"^[a-z]{1,20}$")
_STUDY = re.compile(r"^([A-Z0-9][A-Z0-9_-]{0,31})?$")
_ACTION = re.compile(r"^[a-z_]{1,30}\.[A-Za-z_]{1,40}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_LEN = 8192  # a header: the claim is small; anything longer is not one


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def body_hash(body: Any = None) -> str:
    """The sha256 that stands for a request body. A JSON body is hashed in one canonical form of its *value*
    (sorted keys, no spaces, ASCII), so the minting side hashes the object it is about to send and the checking
    side the object it received, whatever bytes the HTTP client wrote. No body: the hash of nothing. Bytes that
    are not JSON: the bytes."""
    if body is None or body == b"":
        return hashlib.sha256(b"").hexdigest()
    if isinstance(body, (bytes, bytearray)):
        try:
            body = json.loads(body)
        except ValueError:
            return hashlib.sha256(bytes(body)).hexdigest()
    return hashlib.sha256(_canonical(body)).hexdigest()


def target_of(method: str, path: str) -> str:
    """``METHOD path?query`` as both sides write it."""
    return f"{method.upper()} {path}"


@dataclass(frozen=True)
class Claim:
    sub: str
    role: str
    session: str = ""
    study: str = ""
    is_pi: bool = False
    tasks: tuple[str, ...] = ()
    log_names_pi: bool = True
    monitor: bool = False
    action: str = ""
    target: str = ""
    grant: dict[str, Any] | None = None
    reauth_at: int | None = None
    body: str = ""
    nonce: str = ""
    iat: int = 0
    exp: int = 0
    verified: bool = False  # a MAC was checked (False only on a DEV/TEST box without a token)

    @property
    def name(self) -> str:
        """The audit actor."""
        return self.sub

    @property
    def is_service(self) -> bool:
        return self.sub.startswith("service:")

    def standing(self) -> Standing:
        return Standing(is_pi=self.is_pi, tasks=frozenset(self.tasks), log_names_pi=self.log_names_pi,
                        monitor=self.monitor)  # fmt: skip


def _payload(c: Claim) -> dict[str, Any]:
    return {
        "sub": c.sub, "role": c.role, "session": c.session, "study": c.study,
        "standing": {"is_pi": c.is_pi, "tasks": sorted(c.tasks), "log_names_pi": c.log_names_pi,
                     "monitor": c.monitor},
        "action": c.action, "target": c.target, "grant": c.grant, "reauth_at": c.reauth_at, "body": c.body,
        "nonce": c.nonce, "iat": c.iat, "exp": c.exp,
    }  # fmt: skip


def _mac(key: bytes, head: str) -> str:
    return hmac.new(key, head.encode("ascii"), hashlib.sha256).hexdigest()


def mint(
    *,
    sub: str,
    role: str,
    action: str,
    method: str,
    path: str,
    body: Any = None,
    study: str = "",
    standing: Standing | None = None,
    session: str = "",
    grant: dict[str, Any] | None = None,
    reauth_at: int | None = None,
    now: float | None = None,
) -> str:
    """The assertion for one request. Signed with this service's actor key; on a box with no token (DEV, TEST) the
    MAC is empty and only such a box accepts it. Raises ``ValueError`` on a field that is not what it claims to be:
    the minting side fails before the wire does."""
    st = standing or Standing()
    t = int(time.time() if now is None else now)
    claim = Claim(
        sub=sub, role=role, session=re.sub(r"[^A-Za-z0-9_-]", "", session)[:32], study=study.strip().upper(),
        is_pi=st.is_pi, tasks=tuple(sorted(st.tasks)), log_names_pi=st.log_names_pi, monitor=st.monitor,
        action=action, target=target_of(method, path), grant=grant, reauth_at=reauth_at, body=body_hash(body),
        nonce=secrets.token_urlsafe(16)[:22], iat=t, exp=t + sa.ACTOR_TTL,
    )  # fmt: skip
    _check_shape(claim)
    return _sign(_payload(claim))


def _sign(payload: dict[str, Any]) -> str:
    head = VERSION + "." + base64.urlsafe_b64encode(_canonical(payload)).decode("ascii").rstrip("=")
    key = sa.signing_key()  # T-717 (D-485): the signing service's own key, never a function of its token
    return f"{head}.{_mac(key, head) if key else ''}"


def remint(assertion: str, now: float | None = None) -> str:
    """The same claim with a new nonce and a new two minutes, signed by this service: what a client sends when it
    sends a call again (an assertion is accepted once). Only the service that minted it holds the key."""
    parts = assertion.split(".")
    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    t = int(time.time() if now is None else now)
    payload.update(nonce=secrets.token_urlsafe(16)[:22], iat=t, exp=t + sa.ACTOR_TTL)
    return _sign(payload)


def _check_shape(c: Claim) -> None:
    if not _SUB.match(c.sub):
        raise ValueError("the assertion names no person")
    if not _ROLE.match(c.role) or (c.is_service != (c.role == SERVICE_ROLE)):
        raise ValueError("the assertion's role is not a role")
    if not _STUDY.match(c.study):
        raise ValueError("the assertion's study is not one study")
    if not _ACTION.match(c.action):
        raise ValueError("the assertion names no action")
    if not c.target or " " not in c.target or len(c.target) > 2048:
        raise ValueError("the assertion names no request")
    if not _SHA.match(c.body):
        raise ValueError("the assertion carries no body hash")
    if c.grant is not None and not (isinstance(c.grant, dict) and str(c.grant.get("id") or "")):
        raise ValueError("the assertion's grant has no id")


def is_v3(assertion: str | None) -> bool:
    return bool(assertion) and str(assertion).startswith(VERSION + ".")


def verify(assertion: str | None, *, now: float | None = None, replay: sa.ReplayGuard | None = None) -> Claim:
    """The claim of a verified assertion. Raises ``service_auth.ActorError`` when there is none, when it is not a
    v3 assertion, does not verify under an actor key of this box, has expired, or was used before. What the claim
    is checked *against* (the route's action, the path, the body, the matrix) is the dependency's part."""
    text = (assertion or "").strip()
    if not text:
        raise sa.ActorError("no signed-in user on this call (X-TB-Actor-Assertion)")
    parts = text.split(".")
    if len(text) > MAX_LEN or len(parts) != 3 or parts[0] != VERSION:
        raise sa.ActorError("the signed-in user's assertion is not a v3 assertion")
    head, mac = f"{parts[0]}.{parts[1]}", parts[2]
    keys = sa.actor_keys()
    if keys is not None and not any(hmac.compare_digest(_mac(k, head), mac) for k in keys):
        raise sa.ActorError("the signed-in user's assertion does not verify")
    try:
        raw = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        st = raw["standing"]
        claim = Claim(
            sub=str(raw["sub"]), role=str(raw["role"]), session=str(raw["session"]), study=str(raw["study"]),
            is_pi=st["is_pi"] is True, tasks=tuple(str(x) for x in st["tasks"]),
            log_names_pi=st["log_names_pi"] is True, monitor=st["monitor"] is True,
            action=str(raw["action"]), target=str(raw["target"]), grant=raw["grant"],
            reauth_at=None if raw["reauth_at"] is None else int(raw["reauth_at"]), body=str(raw["body"]),
            nonce=str(raw["nonce"]), iat=int(raw["iat"]), exp=int(raw["exp"]), verified=keys is not None,
        )  # fmt: skip
        _check_shape(claim)
    except (KeyError, TypeError, ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise sa.ActorError("the signed-in user's assertion cannot be read") from exc
    t = int(time.time() if now is None else now)
    if claim.exp < t or claim.exp > t + sa.ACTOR_TTL + 5 or claim.iat > t + 5:
        raise sa.ActorError("the signed-in user's assertion has expired")
    if not (sa.REPLAY if replay is None else replay).use(f"v3:{claim.nonce}:{mac}", claim.exp, t):
        raise sa.ActorError("the signed-in user's assertion was already used")
    return claim
