"""Service-to-service tokens (D-114; one token per service since D-128 / D-138).

Fable review 2026-11-08, finding 3: anything on the compose ``trialbox-net`` could ``POST /jobs/{id}/reveal`` and get
a chart number under any name. Every call between TrialBox services carries ``X-TB-Service-Token``; the caller's
signed-in user travels in ``X-TB-Actor``, and the callee takes the audit actor from it, not from a body field,
because only a token holder can set it.

**One token per service** (D-128, review F-02; step 8, D-138). Each service holds only its own token
(``TB_SERVICE_TOKEN_FILE``, a compose secret written by ``trialbox secrets init``, mode 0600) and sends it on every
call. A callee reads the token registry (``TB_SERVICE_TOKENS``: ``tokens.json`` with the sha256 of every service's
token, never a token itself), finds which service is calling, and accepts only the callers of :data:`CALLERS`
(403 otherwise). So a compromised doc-parser holds a token that the orchestrator refuses, and cannot reveal a chart
number. ``operator`` is the administrator's own token on the host (scripts and ``curl``); it is never mounted into a
container. The registry is re-read when it changes, so a rotation needs only the rotated service restarted.

**The old shared token** (one ``TB_SERVICE_TOKEN`` for the whole box) keeps working until the box's tokens are
rotated: with a registry, ``tokens.json`` may carry its hash as ``legacy`` (accepted from any caller, with a warning
in the log); without a registry (tests, ``make demo``, a box installed before step 8) the shared token is the only
rule, as before, and the service warns once that it should be migrated (``trialbox secrets init``).

Without any token: DEV and TEST boxes (tests, ``make demo``) accept unauthenticated calls; any other ``TB_ENV``, and
an unset one, refuses every changing call with 503 until a token is configured (fail closed).

Reads (D-130, plan v4 F4): a service whose reads carry patient-level data (the orchestrator: jobs, outputs, registry,
studies; the lake; the mail gateway's threads; the trace store) turns on ``protect_reads`` in ``make_app``, and then
``GET`` / ``HEAD`` follow the same rule. ``/healthz`` stays open for the compose health checks.

**The actor is signed** (review 2026-11-09 S-09, D-143). ``X-TB-Actor`` alone was whatever a token holder wrote: the
mail gateway's token could reveal chart numbers as "dr_tanaka" and step round the per-person reveal cap by changing
names. The console now sends ``X-TB-Actor-Assertion`` beside it: ``v2.<expiry>.<session>.<nonce>.<hmac>``, an
HMAC-SHA256 over the actor, the console session (the first 16 characters of the session token's hash), an expiry two
minutes ahead and a random nonce, keyed with ``HMAC(console token, "tb-actor-assertion/1")``. The orchestrator verifies
it before it takes the actor for a reveal, an export, a notice or a cancel:

* with one shared token (tests, ``make demo``, a box before step 8) both sides derive the key from that token;
* with per-service tokens the orchestrator cannot know the console's token, so ``trialbox secrets init`` writes the
  derived key (``actor-keys``, 0600, the console's current and, during a rotation, previous key) and the secrets
  overlay mounts it into the orchestrator only (``TB_ACTOR_KEYS_FILE``). No other service holds it, so the mail
  gateway, which parses hostile mail, cannot name a user;
* with no token at all (DEV/TEST) nothing is verified, as before.

**An assertion is used once** (D-447, SEC-17). Each assertion carries its own nonce under the MAC and the verifier
remembers every assertion it accepted until it expires (:class:`ReplayGuard`, at most ``ACTOR_TTL`` + 5 seconds), so a
copied assertion sent again within its two minutes is refused ("already used"). The guard is in the memory of the
verifying process: the orchestrator runs one uvicorn process, and a restart forgets it, which reopens the window for
assertions issued in the two minutes before the restart only. The two-minute life itself stays (it covers a slow
call); the old ``v1`` form, which had no nonce, is refused.
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

TOKEN_HEADER = "X-TB-Service-Token"
ACTOR_HEADER = "X-TB-Actor"
ASSERTION_HEADER = "X-TB-Actor-Assertion"
ROLE_HEADER = "X-TB-Actor-Role"  # the signed-in person's console role, covered by the assertion (D-146, review J-01)
# D-273 (PV-5, PV-15): the studies the signed-in person may see, "*" for every study, covered by the assertion. Sent on
# the chart-number calls (reveal, registry export) so that the orchestrator checks the study, not only the name.
SCOPE_HEADER = "X-TB-Actor-Scope"
ACTOR_KEYS_ENV = "TB_ACTOR_KEYS_FILE"
ACTOR_LABEL = b"tb-actor-assertion/1"
ACTOR_TTL = 120  # seconds an assertion is valid
ACTOR_VERSION = "v2"  # D-447 (SEC-17): v2 carries a nonce and is accepted once; v1 (no nonce) is refused
OPEN_ENVS = ("DEV", "TEST")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
REGISTRY_ENV = "TB_SERVICE_TOKENS"
REGISTRY_SCHEMA = "tb-service-tokens/1"
OPERATOR = "operator"
LEGACY = "legacy"

# Who may call whom (callee -> callers), from the service clients in the code (tests/unit/test_service_secrets.py
# scans them, so a new call between services cannot be forgotten here). A callee that is not listed accepts any
# service of the registry. ``operator`` and, until rotation, ``legacy`` are accepted everywhere.
CALLERS: dict[str, frozenset[str]] = {
    "orchestrator": frozenset({"console", "mail-gateway"}),
    "mail-gateway": frozenset({"orchestrator", "console"}),
    "adapter": frozenset({"orchestrator", "console"}),
    "lake": frozenset({"orchestrator", "criteria-compiler", "adapter"}),
    "doc-parser": frozenset({"orchestrator"}),
    "criteria-compiler": frozenset({"orchestrator"}),
    "embed-service": frozenset({"lake"}),
    "gateway": frozenset({"orchestrator", "criteria-compiler", "doc-parser", "console"}),
}
EVERYWHERE = frozenset({OPERATOR, LEGACY})

log = logging.getLogger("tb.service_auth")
_warned: set[str] = set()
_lock = threading.Lock()


def _warn_once(key: str, msg: str) -> None:
    with _lock:
        if key in _warned:
            return
        _warned.add(key)
    log.warning(msg)


def service_token() -> str:
    """This service's own token, or "" when none is configured (a ``change-me`` placeholder counts as none).

    The per-service file (``TB_SERVICE_TOKEN_FILE``) comes first; the old shared ``TB_SERVICE_TOKEN`` second."""
    tok = ""
    path = (os.environ.get("TB_SERVICE_TOKEN_FILE") or "").strip()
    if path:
        try:
            tok = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            tok = ""
    if not tok:
        tok = (os.environ.get("TB_SERVICE_TOKEN") or "").strip()
    return "" if tok.startswith("change-me") else tok


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RegistryError(RuntimeError):
    """``TB_SERVICE_TOKENS`` names a registry that cannot be read: every call is refused (fail closed)."""


@dataclass(frozen=True)
class Registry:
    """The token registry: service -> sha256 of its token(s) (two during a rotation), and the old shared token."""

    hashes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    legacy: str | None = None

    def identify(self, presented: str) -> str | None:
        """The service whose token this is, ``legacy`` for the old shared token, else None. Every hash is compared
        (constant time) so the time taken does not tell which service matched."""
        h = token_hash(presented)
        found: str | None = None
        for name in sorted(self.hashes):
            for want in self.hashes[name]:
                if hmac.compare_digest(h, want) and found is None:
                    found = name
        if self.legacy is not None and hmac.compare_digest(h, self.legacy) and found is None:
            found = LEGACY
        return found


_cache: dict[str, tuple[tuple[int, int], Registry]] = {}


def parse_registry(data: dict[str, object]) -> Registry:
    if data.get("schema") != REGISTRY_SCHEMA:
        raise RegistryError(f"not a {REGISTRY_SCHEMA} file")
    raw = data.get("services")
    if not isinstance(raw, dict) or not raw:
        raise RegistryError("no services in the token registry")
    hashes: dict[str, tuple[str, ...]] = {}
    for name, val in raw.items():
        vals = [val] if isinstance(val, str) else list(val) if isinstance(val, list) else []
        if not vals or not all(isinstance(v, str) and len(v) == 64 for v in vals):
            raise RegistryError(f"bad hash for {name}")
        hashes[str(name)] = tuple(str(v) for v in vals)
    legacy = data.get("legacy")
    if legacy is not None and not (isinstance(legacy, str) and len(legacy) == 64):
        raise RegistryError("bad legacy hash")
    return Registry(hashes, legacy if isinstance(legacy, str) else None)


def registry() -> Registry | None:
    """The token registry of this box, or None when the box has none (the old shared-token rule). Re-read when the
    file changes (rotation). Raises :class:`RegistryError` when one is configured and cannot be read."""
    path = (os.environ.get(REGISTRY_ENV) or "").strip()
    if not path:
        return None
    try:
        st = Path(path).stat()
        key = (st.st_mtime_ns, st.st_size)
        hit = _cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
        reg = parse_registry(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise RegistryError(f"service token registry {path} unreadable: {type(exc).__name__}") from exc
    _cache[path] = (key, reg)
    return reg


def allowed(callee: str | None, caller: str) -> bool:
    if caller in EVERYWHERE or not callee or callee not in CALLERS:
        return True
    return caller in CALLERS[callee]


def auth_headers(actor: str | None = None) -> dict[str, str]:
    """Headers for a call to another TrialBox service: this service's token when configured, the signed-in user
    when given."""
    h: dict[str, str] = {}
    tok = service_token()
    if tok:
        h[TOKEN_HEADER] = tok
    if actor:
        h.update(actor_header(actor))
    return h


_SESSION: contextvars.ContextVar[str] = contextvars.ContextVar("tb_actor_session", default="")
_SID = re.compile(r"[^A-Za-z0-9_-]")


def bind_session(session: str) -> None:
    """The console session the current request runs under (set by the console's sign-in check); the assertions this
    request sends carry it."""
    _SESSION.set(_SID.sub("", session)[:32])


def bound_session() -> str:
    """The console session of the current request ("" outside one)."""
    return _SESSION.get()


def actor_key(token: str) -> bytes:
    """The key that signs actor assertions, derived from the signing service's own token (never the token itself)."""
    return hmac.new(token.encode("utf-8"), ACTOR_LABEL, hashlib.sha256).digest()


_ROLE = re.compile(r"^[a-z]{1,20}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,32}$")
_SCOPE = re.compile(r"^(\*|[A-Z0-9][A-Z0-9_-]{0,31}(,[A-Z0-9][A-Z0-9_-]{0,31}){0,63})$")


def scope_of(studies: tuple[str, ...] | list[str]) -> str:
    """The ``X-TB-Actor-Scope`` value for an account's studies: ``*`` when the account sees every study (D-104)."""
    return ",".join(sorted({s.strip().upper() for s in studies if s.strip()})) or "*"


def in_scope(scope: str, study: str | None) -> bool:
    """May an assertion with ``scope`` act on ``study``? ``*`` covers every study; a job without a study only ``*``."""
    if scope == "*":
        return True
    return bool(study) and str(study).strip().upper() in scope.split(",")


def _actor_mac(key: bytes, actor: str, session: str, exp: int, nonce: str, role: str = "", scope: str = "") -> str:
    msg = f"{ACTOR_VERSION}\n{actor}\n{session}\n{exp}\n{nonce}"
    msg += (f"\nrole={role}" if role else "") + (f"\nscope={scope}" if scope else "")
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


class ReplayGuard:
    """The assertions a verifier has accepted, kept until they expire (D-447, SEC-17): a second use is refused.

    Thread-safe; entries older than their expiry are dropped as new ones arrive, so it holds at most the assertions
    of the last ``ACTOR_TTL`` + 5 seconds."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()

    def use(self, mac: str, exp: int, now: int) -> bool:
        """Record ``mac`` (valid until ``exp``); False when it was already used."""
        with self._lock:
            if len(self._seen) > 256:
                for k in [k for k, e in self._seen.items() if e < now]:
                    del self._seen[k]
            if mac in self._seen:
                return False
            self._seen[mac] = exp
            return True

    def __len__(self) -> int:
        return len(self._seen)


#: the guard of this process (the orchestrator's); a test may pass its own to :func:`verify_actor`
REPLAY = ReplayGuard()


def sign_actor(
    actor: str, session: str | None = None, now: float | None = None, role: str = "", scope: str = ""
) -> str | None:
    """``v2.<expiry>.<session>.<nonce>.<hmac>`` for ``actor`` (and its ``role`` and study ``scope`` when given: the
    MAC covers them), or None when this service holds no token (DEV/TEST). A new nonce each time: two calls in the
    same second carry two assertions, each accepted once (D-447)."""
    tok = service_token()
    if not tok:
        return None
    sid = _SID.sub("", _SESSION.get() if session is None else session)[:32]
    exp = int(time.time() if now is None else now) + ACTOR_TTL
    nonce = secrets.token_urlsafe(16)[:22]
    return f"{ACTOR_VERSION}.{exp}.{sid}.{nonce}.{_actor_mac(actor_key(tok), actor, sid, exp, nonce, role, scope)}"


def actor_header(actor: str, session: str | None = None, role: str = "", scope: str = "") -> dict[str, str]:
    """``X-TB-Actor`` for a signed-in user (percent-encoded, as a header is ASCII and names may be 日本語) and its
    signed assertion when this service holds a token (S-09, D-143). With ``role`` (D-146, review J-01) the console
    role travels in ``X-TB-Actor-Role`` and the assertion covers it, so the orchestrator authorises a console request
    by the person's role instead of a mailbox. With ``scope`` (D-273) the person's studies travel in
    ``X-TB-Actor-Scope``, covered the same way."""
    h = {ACTOR_HEADER: quote(actor, safe="@._-+")}
    if role:
        h[ROLE_HEADER] = role
    if scope:
        h[SCOPE_HEADER] = scope
    signed = sign_actor(actor, session, role=role, scope=scope)
    if signed:
        h[ASSERTION_HEADER] = signed
    return h


def resign(headers: dict[str, str]) -> dict[str, str]:
    """``headers`` with a fresh actor assertion for the same actor, session, role and scope (D-447): a client that
    sends a call again (a retry after a 5xx or a dropped connection) needs a new one, as the first may have been
    used. Headers without an assertion, or on a service without a token, come back unchanged."""
    old = headers.get(ASSERTION_HEADER)
    if old and old.startswith("v3."):  # T-715 (D-483): the claim is the whole message; a new nonce, signed again
        from tb_common import actor_v3

        return {**headers, ASSERTION_HEADER: actor_v3.remint(old)}
    if not old or ACTOR_HEADER not in headers:
        return headers
    parts = old.split(".")
    sid = parts[2] if len(parts) == 5 else ""
    signed = sign_actor(unquote(headers[ACTOR_HEADER]), sid, role=headers.get(ROLE_HEADER, ""),
                        scope=headers.get(SCOPE_HEADER, ""))  # fmt: skip
    return {**headers, ASSERTION_HEADER: signed} if signed else headers


def actor_keys() -> list[bytes] | None:
    """The keys an actor assertion may be signed with; None when this box verifies nothing (no token at all: DEV and
    TEST without a token). Fail closed: a keys file that cannot be read, or a token registry without a keys file,
    gives no key, so every assertion is refused."""
    path = (os.environ.get(ACTOR_KEYS_ENV) or "").strip()
    if path:
        try:
            lines = Path(path).read_text(encoding="utf-8").split()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                key = bytes.fromhex(line.strip())
            except ValueError:
                continue
            if len(key) == 32:
                out.append(key)
        return out
    if (os.environ.get(REGISTRY_ENV) or "").strip():
        return []
    tok = service_token()
    return [actor_key(tok)] if tok else None


class ActorError(ValueError):
    """The actor of a call could not be verified (no user named, a missing, expired or wrong assertion)."""


@dataclass(frozen=True)
class Actor:
    name: str
    session: str = ""
    verified: bool = False
    role: str = ""  # the console role the caller sent (D-146); covered by the assertion when verified
    scope: str = ""  # the studies the caller sent ("*" is every study; D-273); covered by the assertion when verified


def verify_actor(header: str | None, assertion: str | None, fallback: str | None = None,
                 now: float | None = None, role: str | None = None, scope: str | None = None,
                 replay: ReplayGuard | None = None) -> Actor:  # fmt: skip
    """The audit actor of a call. With keys (any box with a token), ``X-TB-Actor`` counts only with a valid,
    unexpired assertion over it (and over ``role`` and ``scope``, the ``X-TB-Actor-Role`` and ``X-TB-Actor-Scope``
    headers, when sent) that this process has not accepted before (``replay``, default :data:`REPLAY`; D-447,
    SEC-17); without (DEV/TEST, no token) the old rule of :func:`actor_of` applies. A refused assertion is not
    recorded, so only a verified one is used up."""
    rl = (role or "").strip()
    if rl and not _ROLE.match(rl):
        raise ActorError("the signed-in user's role is not a role")
    sc = (scope or "").strip()
    if sc and not _SCOPE.match(sc):
        raise ActorError("the signed-in user's study scope is not a list of studies")
    keys = actor_keys()
    if keys is None:
        who = actor_of(header, fallback)
        if who is None:
            raise ActorError("no signed-in user (X-TB-Actor) on this call")
        return Actor(who, role=rl, scope=sc)
    if not header or not header.strip():
        raise ActorError("no signed-in user (X-TB-Actor) on this call")
    name = unquote(header.strip())[:200]
    parts = (assertion or "").strip().split(".")
    if len(parts) != 5 or parts[0] != ACTOR_VERSION or not parts[1].isdigit() or not _NONCE.match(parts[3]):
        raise ActorError("the signed-in user is not signed (X-TB-Actor-Assertion)")
    exp, sid, nonce, mac = int(parts[1]), parts[2], parts[3], parts[4]
    t = int(time.time() if now is None else now)
    if exp < t or exp > t + ACTOR_TTL + 5:
        raise ActorError("the signed-in user's assertion has expired")
    if not any(hmac.compare_digest(_actor_mac(k, name, sid, exp, nonce, rl, sc), mac) for k in keys):
        raise ActorError("the signed-in user's assertion does not verify")
    if not (REPLAY if replay is None else replay).use(mac, exp, t):
        raise ActorError("the signed-in user's assertion was already used")
    return Actor(name, sid, True, rl, sc)


Refusal = tuple[int, str]


def authorize(
    method: str, presented: str | None, environment: str, protect_reads: bool = False, callee: str | None = None
) -> tuple[Refusal | None, str | None]:
    """``(refusal, caller)``: refusal None when the call may proceed; caller the service that called, when known.

    Read-only methods pass unless ``protect_reads`` (D-130). ``OPTIONS`` always passes."""
    m = method.upper()
    if m == "OPTIONS" or (m in SAFE_METHODS and not protect_reads):
        return None, None
    try:
        reg = registry()
    except RegistryError as exc:
        return (503, str(exc)), None
    if reg is not None:
        if not presented:
            return (401, f"missing {TOKEN_HEADER}"), None
        caller = reg.identify(presented)
        if caller is None:
            return (403, f"wrong {TOKEN_HEADER}"), None
        if not allowed(callee, caller):
            return (403, f"{caller} may not call {callee}"), caller
        if caller == LEGACY:
            _warn_once(
                "legacy-used",
                "a caller used the old shared service token (D-128): rotate the box's tokens with "
                "`trialbox secrets rotate` so that each service has its own",
            )
        return None, caller
    tok = service_token()
    if not tok:
        if environment.upper() in OPEN_ENVS:
            return None, None
        return (503, "no service token configured (TB_SERVICE_TOKEN): calls are refused"), None
    if environment.upper() not in OPEN_ENVS and os.environ.get("TB_SERVICE_NAME"):  # a deployed service, not a test
        _warn_once(
            "legacy-mode",
            "one shared service token for the whole box (D-128): run `trialbox secrets init` and restart with "
            "deploy/docker-compose.secrets.yml so that each service has its own",
        )
    if not presented:
        return (401, f"missing {TOKEN_HEADER}"), None
    if not hmac.compare_digest(presented.encode("utf-8"), tok.encode("utf-8")):
        return (403, f"wrong {TOKEN_HEADER}"), None
    return None, LEGACY


def check(
    method: str, presented: str | None, environment: str, protect_reads: bool = False, callee: str | None = None
) -> Refusal | None:
    """None when the call may proceed; else (status, detail). See :func:`authorize`."""
    return authorize(method, presented, environment, protect_reads, callee)[0]


def actor_of(header: str | None, fallback: str | None) -> str | None:
    """The audit actor: the ``X-TB-Actor`` header of an authenticated caller; the body or query ``by`` only on a box
    without a token (DEV/TEST), where nobody is authenticated anyway."""
    if header and header.strip():
        return unquote(header.strip())[:200]
    if not service_token() and not (os.environ.get(REGISTRY_ENV) or "").strip() and fallback and fallback.strip():
        return fallback.strip()[:200]
    return None
