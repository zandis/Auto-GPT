"""Identity and TLS for the console (D-192, D-193): the second sign-in step, the OIDC sign-in, the administrator's
recovery actions and the TLS settings check.

* **Local accounts sign in with a password and a TOTP code** (RFC 6238, ``console.totp``). It is the default:
  ``TB_CONSOLE_MFA`` is ``totp`` unless ``TB_ENV`` is DEV or TEST, and ``off`` is refused outside them, as is an OIDC
  sign-in without a second factor (``TB_OIDC_REQUIRE_MFA=0``; D-447; ``trialbox doctor`` check ``console_mfa``).
  An account without an authenticator enrols one at its first sign-in (after its password). A wrong or replayed code
  counts as a failed sign-in; five in 15 minutes from one address lock the account from that address
  (``console.auth``, D-279).
  ``POST /api/v1/session`` asks for the same two factors in one call (password and ``code``, checked by
  :meth:`Identity.step_up`); an account enrols its authenticator on the page only. A token from that route is a
  bearer token and never a cookie, and a page's cookie is never a bearer token (T-505a, D-320, ROLE-001).
* **A password someone else set** (an administrator's new account or reset) is replaced by its owner before anything
  else: the sign-in lands on ``/account`` and every other page and API call is refused (D-279, SEC-1).
* **Step-up at signing** (D-279, SEC-1 P-2): with TOTP on, an electronic signature needs the password *and* a fresh
  code (:meth:`Identity.step_up`); a wrong code counts as a failed sign-in.
* **Re-authentication at the directory for a signature** (T-205, D-391, REG-025): an OIDC account has no console
  password, so its signature sends the person back to the provider with ``prompt=login`` and ``max_age=0``
  (:meth:`Identity.start_reauth`). The callback accepts the answer only for the same account and subject, with an
  ``auth_time`` after the round trip began and a second factor in ``amr``; it never opens a session. The page that
  asked gets a single-use proof (:meth:`Identity.take_reauth`, two minutes) bound to the person.
* **Recovery**: an administrator resets another account's authenticator (lost phone) or lifts a lock on
  ``/ops/identity`` or with ``console.cli reset-totp|unlock``; both are audited and sign the account out.
* **OIDC** through the hospital's Authelia (``console.oidc``), off by default (``TB_OIDC_ENABLED``). Roles come only
  from the configured group map. Sign-out goes on to the provider's logout address.
* **Sessions**: idle timeout ``TB_CONSOLE_IDLE_MINUTES`` (default 10, at most 60), absolute
  ``TB_CONSOLE_SESSION_HOURS`` (default 8, at most 12); Secure (on by default in PRODUCTION), HttpOnly and
  SameSite=Strict cookies (the OIDC round-trip cookie is Lax: it must come back from the provider's redirect).
* **TLS** is Caddy's (``deploy/identity/Caddyfile``): its internal CA, or the hospital's certificate when
  ``TB_TLS_MODE=hospital``. :func:`check_tls` checks the hospital certificate before Caddy is started with it.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from cryptography.exceptions import InvalidTag
from fastapi import FastAPI, Form, Query, Request, Response
from fastapi.responses import RedirectResponse
from tb_common.audit import AuditLog

from console import totp
from console.auth import MAX_FAILURES, AuthError, Session, User, UserStore, source_of
from console.i18n import EN, JA, ZH
from console.oidc import Identity as Found
from console.oidc import OidcClient, OidcConfigError, OidcError, OidcSettings

MFA_COOKIE = "tb_console_mfa"
OIDC_COOKIE = "tb_console_oidc"
REAUTH_TTL = 600.0  # seconds a re-authentication at the provider may take (as the OIDC state, ten minutes)
PROOF_TTL = 120.0  # seconds the page that asked has to use the proof (as an actor assertion)
MFA_MODES = ("totp", "off")
TLS_MODES = ("internal", "hospital")


def client_source(request: Request) -> str:
    """The address a sign-in try is counted under (D-279). Behind Caddy this is the browser's address only when
    uvicorn trusts the proxy (``TB_CONSOLE_FORWARDED_ALLOW_IPS``); otherwise every try shares the proxy's address."""
    return source_of(request.client.host if request.client else None)


#: the pages an account with a password someone else set may still open (D-279): its own password page and sign-out
MUST_CHANGE_OPEN = frozenset({"/account", "/account/password", "/logout", "/lang"})


class IdentityConfigError(RuntimeError):
    """The identity settings are incomplete or unsafe; the console refuses to start."""


def _int_in(env: Mapping[str, str], key: str, default: int, lo: int, hi: int) -> int:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise IdentityConfigError(f"{key} must be a whole number") from exc
    if not lo <= value <= hi:
        raise IdentityConfigError(f"{key} must be between {lo} and {hi}")
    return value


@dataclass(frozen=True)
class IdentitySettings:
    mfa: str = "totp"
    idle: timedelta = timedelta(minutes=10)
    absolute: timedelta = timedelta(hours=8)
    oidc_absolute: timedelta = timedelta(minutes=60)  # D-279 (CR-117): the directory is asked again after this
    totp_key_file: Path = Path("/data/console/totp.key")
    totp_issuer: str = "TrialBox"
    oidc: OidcSettings = field(default_factory=OidcSettings)

    @property
    def totp_required(self) -> bool:
        return self.mfa == "totp"

    @classmethod
    def from_env(cls, env: Mapping[str, str], environment: str, data_dir: Path) -> IdentitySettings:
        dev = environment.upper() in ("DEV", "TEST")
        mfa = (env.get("TB_CONSOLE_MFA") or ("off" if dev else "totp")).strip().lower()
        if mfa not in MFA_MODES:
            raise IdentityConfigError(f"TB_CONSOLE_MFA must be one of {', '.join(MFA_MODES)}")
        if mfa == "off" and not dev:  # review M2: only the build and the synthetic hospital go without TOTP
            raise IdentityConfigError(f"TB_CONSOLE_MFA=off is refused in {environment}: local accounts need TOTP")
        key = (env.get("TB_CONSOLE_TOTP_KEY_FILE") or "").strip()
        try:
            oidc = OidcSettings.from_env(env)
        except OidcConfigError as exc:
            raise IdentityConfigError(str(exc)) from exc
        if oidc.enabled and not oidc.require_mfa and not dev:  # D-447: every way in asks for a second factor
            raise IdentityConfigError(f"TB_OIDC_REQUIRE_MFA=0 is refused in {environment}: directory sign-ins need MFA")
        return cls(
            mfa=mfa,
            idle=timedelta(minutes=_int_in(env, "TB_CONSOLE_IDLE_MINUTES", 10, 1, 60)),
            absolute=timedelta(hours=_int_in(env, "TB_CONSOLE_SESSION_HOURS", 8, 1, 12)),
            oidc_absolute=timedelta(minutes=_int_in(env, "TB_OIDC_SESSION_MINUTES", 60, 5, 480)),
            totp_key_file=Path(key) if key else data_dir / "totp.key",
            totp_issuer=(env.get("TB_CONSOLE_TOTP_ISSUER") or "TrialBox").strip()[:40] or "TrialBox",
            oidc=oidc,
        )


def secure_cookie_default(env: Mapping[str, str], environment: str) -> bool:
    """``TB_CONSOLE_SECURE_COOKIE`` when set (1/true or 0/false), else on in PRODUCTION (D-192). An explicit off is
    refused in PRODUCTION (review M1): there the console is reached only by https (or on the box's own loopback,
    which browsers treat as a secure origin)."""
    raw = (env.get("TB_CONSOLE_SECURE_COOKIE") or "").strip().lower()
    prod = environment.upper() == "PRODUCTION"
    if raw:
        on = raw in ("1", "true", "on", "yes")
        if prod and not on:
            raise IdentityConfigError("TB_CONSOLE_SECURE_COOKIE=0 is refused in PRODUCTION")
        return on
    return prod


# ---------------------------------------------------------------------------------------------- TLS (D-193)
@dataclass(frozen=True)
class TlsReport:
    mode: str
    hostname: str
    problems: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems


def check_tls(env: Mapping[str, str], now: datetime | None = None) -> TlsReport:
    """The TLS settings Caddy will use (``TB_TLS_MODE``, ``TB_TLS_HOSTNAME``, ``TB_TLS_CERT_FILE``,
    ``TB_TLS_KEY_FILE``). With the hospital's certificate: the files exist, the certificate is valid now and names the
    host, and the key is the certificate's key. Nothing is printed from the key."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.x509.oid import ExtensionOID

    now = now or datetime.now(UTC)
    mode = (env.get("TB_TLS_MODE") or "internal").strip().lower()
    host = (env.get("TB_TLS_HOSTNAME") or "").strip().lower()
    problems: list[str] = []
    notes: list[str] = []
    if mode not in TLS_MODES:
        return TlsReport(mode, host, (f"TB_TLS_MODE must be one of {', '.join(TLS_MODES)}",))
    if not host or host in ("localhost", "127.0.0.1") or "/" in host or ":" in host:
        problems.append("TB_TLS_HOSTNAME must be the console's DNS name on the hospital network")
    if mode == "internal":
        notes.append("Caddy issues the certificate from its own CA; install its root on the staff PCs (RUNBOOK §12)")
        return TlsReport(mode, host, tuple(problems), tuple(notes))
    cert_path = Path((env.get("TB_TLS_CERT_FILE") or "").strip() or "/nonexistent")
    key_path = Path((env.get("TB_TLS_KEY_FILE") or "").strip() or "/nonexistent")
    try:
        certs = x509.load_pem_x509_certificates(cert_path.read_bytes())
    except (OSError, ValueError):
        problems.append("TB_TLS_CERT_FILE is not a readable PEM certificate")
        return TlsReport(mode, host, tuple(problems))
    try:
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError):
        problems.append("TB_TLS_KEY_FILE is not a readable, unencrypted PEM private key")
        return TlsReport(mode, host, tuple(problems))
    leaf = certs[0]
    if now < leaf.not_valid_before_utc or now > leaf.not_valid_after_utc:
        problems.append(f"the certificate is not valid now (valid {leaf.not_valid_before_utc:%Y-%m-%d} to "
                        f"{leaf.not_valid_after_utc:%Y-%m-%d})")  # fmt: skip
    elif leaf.not_valid_after_utc - now < timedelta(days=30):
        notes.append(f"the certificate ends on {leaf.not_valid_after_utc:%Y-%m-%d}: ask hospital IT for the next one")
    pub = serialization.PublicFormat.SubjectPublicKeyInfo
    der = serialization.Encoding.DER
    if key.public_key().public_bytes(der, pub) != leaf.public_key().public_bytes(der, pub):
        problems.append("the key file does not belong to the certificate")
    try:
        san = leaf.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        dns = (
            [n.lower() for n in san.get_values_for_type(x509.DNSName)]
            if isinstance(san, x509.SubjectAlternativeName)
            else []
        )
    except x509.ExtensionNotFound:
        dns = []
    if host and not any(d == host or (d.startswith("*.") and host.split(".", 1)[-1] == d[2:]) for d in dns):
        problems.append(f"the certificate does not name {host} (names: {', '.join(dns) or 'none'})")
    if len(certs) == 1 and leaf.issuer != leaf.subject:
        notes.append("the file holds no intermediate certificate; add the chain if browsers report an unknown issuer")
    return TlsReport(mode, host, tuple(problems), tuple(notes))


@dataclass
class Reauth:
    """A re-authentication at the provider (T-205): whose, since when, where the browser goes back to, and once the
    provider has answered, what it said."""

    username: str
    started: float
    target: str
    found: Found | None = None
    proved: float = 0.0


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------- routes
@dataclass
class Hooks:
    """What the console app lends this module (no import of console.app: it imports us)."""

    need: Callable[[Request], Session]
    page: Callable[..., Response]
    login_page: Callable[..., Response]
    confirm: Callable[..., Response]
    lang_of: Callable[[Request, Session | None], str]
    translate: Callable[..., str]
    csrf_ok: Callable[[Session, str | None], bool]
    problem: Callable[..., Exception]
    secure: bool
    session_cookie: str
    home: str


@dataclass
class Identity:
    settings: IdentitySettings
    users: UserStore
    audit: AuditLog
    secure: bool
    oidc_client: OidcClient | None = None
    now: Callable[[], float] = time.time
    _announced: dict[str, datetime] = field(default_factory=dict)  # the lock already audited, per account
    _reauth: dict[str, Reauth] = field(default_factory=dict)  # by the state's hash, while at the provider (T-205)
    _proofs: dict[str, Reauth] = field(default_factory=dict)  # by the proof's hash, until the page uses it

    def __post_init__(self) -> None:
        self.box = totp.SecretBox(self.settings.totp_key_file)
        self.users.oidc_absolute = self.settings.oidc_absolute  # D-279 (CR-117): the directory session's lifetime
        if self.settings.oidc.enabled and self.oidc_client is None:
            self.oidc_client = OidcClient(self.settings.oidc)

    @property
    def oidc_enabled(self) -> bool:
        return self.settings.oidc.enabled

    # ------------------------------------------------------------------ password step
    def needs_code(self, user: User) -> bool:
        """A local account signs in with a TOTP code when TOTP is on; provider accounts get their factor there."""
        return self.settings.totp_required and not self.users.is_sso(user.username)

    def second_step(self, user: User) -> Response:
        token, _ = self.users.new_pending(user.username)
        resp = RedirectResponse("/login/totp", status_code=303)
        resp.set_cookie(MFA_COOKIE, token, httponly=True, samesite="strict", secure=self.secure, max_age=600)
        return resp

    def after_failure(self, username: str, source: str = "") -> None:
        """Audit the failure that locks an account from an address (the alert the IT pack asks for), once per lock:
        further tries while it is locked are audited as failed sign-ins only. Unknown names lock the same way. The
        address is in the event, so the administrator sees whether one machine or many are guessing (D-279)."""
        u = username.strip().lower()[:64]
        until = self.users.locked_until(u, source)
        key = f"{u} {source}"
        if until is None or self._announced.get(key) == until:
            return
        if len(self._announced) > 10_000:  # bounded: an address spraying names cannot grow it without end
            self._announced.clear()
        self._announced[key] = until
        self.audit.append(
            "console.lockout",
            actor=f"console:{u[:32] or '-'}",
            detail={"failures": MAX_FAILURES, "until": until.isoformat(timespec="seconds"), "source": source},
        )

    def step_up(self, username: str, code: str, source: str = "") -> str:
        """The second signature component (21 CFR 11.200(a); D-279, SEC-1 P-2): with TOTP on, a fresh code from the
        signer's authenticator, checked like the sign-in step (replay guard; a wrong code counts as a failure).
        ``""`` when it passes or TOTP is off; otherwise the reason: ``"wrong"``, ``"replay"``, ``"none"`` (no
        authenticator), ``"locked"`` or ``"key"`` (the key file does not open the secret: a refusal, never a pass)."""
        if not self.settings.totp_required:
            return ""
        if self.users.locked(username, source):
            return "locked"
        sealed, last = self.users.totp_state(username)
        if sealed is None:
            return "none"
        try:
            secret = self.box.open(username, sealed)
        except (InvalidTag, ValueError):
            return "key"
        typed = (code or "")[:32]
        step = totp.verify(secret, typed, self.now(), last)
        reason = ""
        if step is None:
            reason = "replay" if totp.verify(secret, typed, self.now(), None) is not None else "wrong"
        elif not self.users.use_step(username, step):
            reason = "replay"
        if reason:
            self.users.record_failure(username, source)
            self.after_failure(username, source)
        return reason

    # ------------------------------------------------------------------ re-authentication at the provider (T-205)
    def _prune(self) -> None:
        t = self.now()
        for k in [k for k, r in self._reauth.items() if t - r.started > REAUTH_TTL]:
            del self._reauth[k]
        for k in [k for k, r in self._proofs.items() if t - r.proved > PROOF_TTL]:
            del self._proofs[k]
        if len(self._reauth) > 1000:  # bounded: a page cannot grow it without end
            self._reauth.clear()

    def start_reauth(self, username: str, target: str) -> Response:
        """Send an OIDC account back to the provider to type its credentials and second factor again; the browser
        then returns to ``target`` (a path on this console) with ``reauth=<proof>``. OidcError and the network's
        errors reach the caller, which refuses the signature."""
        if not self.oidc_enabled or self.oidc_client is None or not self.users.is_oidc(username):
            raise OidcError("not an account of the identity provider")
        if not target.startswith("/") or target.startswith("//"):
            raise OidcError("the page to return to is not on this console")
        start = self.oidc_client.start(fresh=True)
        self.users.put_oidc_state(start.state, start.nonce, start.verifier)
        self._prune()
        self._reauth[_sha(start.state)] = Reauth(username, self.now(), target)
        resp = RedirectResponse(start.url, status_code=303)
        resp.set_cookie(
            OIDC_COOKIE, start.state, httponly=True, samesite="lax", secure=self.secure, max_age=600, path="/auth/oidc"
        )
        return resp

    def reauth_pending(self, state: str) -> Reauth | None:
        """The re-authentication a returning ``state`` belongs to, once (the callback's first question)."""
        return self._reauth.pop(_sha(state), None) if state else None

    def finish_reauth(self, r: Reauth, code: str, flow: tuple[str, str]) -> str:
        """Check the provider's answer for ``r``; ``""`` and a proof kept for the page, or the reason it failed."""
        assert self.oidc_client is not None
        found = self.oidc_client.finish(code, flow[0], flow[1], fresh_since=r.started)
        if found.username != r.username or found.subject != self.users.idp_subject(r.username):
            raise OidcError("another person signed in at the identity provider")
        r.found, r.proved = found, self.now()
        proof = secrets.token_urlsafe(32)
        self._prune()
        self._proofs[_sha(proof)] = r
        return proof

    def take_reauth(self, proof: str, username: str) -> Found | None:
        """The provider's answer behind ``proof`` for ``username``, once and within two minutes; else None."""
        self._prune()
        r = self._proofs.pop(_sha(proof), None) if proof and len(proof) <= 256 else None
        if r is None or r.found is None or r.username != username:
            return None
        return r.found

    def logout_target(self, username: str) -> str:
        if self.oidc_enabled and self.settings.oidc.logout_url and self.users.is_oidc(username):
            return self.settings.oidc.logout_url
        return "/login"


def _totp_page(h: Hooks, request: Request, status: int, **ctx: Any) -> Response:
    return h.page(request, "login_totp.html", None, status, **ctx)


def register(app: FastAPI, ident: Identity, h: Hooks) -> None:
    us, au, st = ident.users, ident.audit, ident.settings

    def _clear(resp: Response, name: str) -> None:
        resp.delete_cookie(name, httponly=True, samesite="strict", secure=h.secure)

    def _signed_in(user: User, lang: str, via: str) -> str:
        token, _ = us.new_session(user, lang, via)
        au.append("console.login", actor=f"console:{user.username}", detail={"role": user.role, "via": via})
        return token

    def _locked_page(request: Request, username: str) -> Response:
        until = us.locked_until(username, client_source(request))
        left = max(1, -(-int((until - us.clock()).total_seconds()) // 60)) if until else 0
        resp = h.login_page(
            request, 401, failed=True, uninitialised=False, until=until.isoformat() if until else "", left=left
        )
        _clear(resp, MFA_COOKIE)
        return resp

    def _open(username: str, sealed: str) -> str:
        """The TOTP secret, or a clear refusal when the key file is not the one that sealed it (a restored database
        with another console volume): an administrator resets the authenticator (L1)."""
        try:
            return ident.box.open(username, sealed)
        except (InvalidTag, ValueError) as exc:
            au.append("console.login_failed", actor=f"console:{username}", detail={"factor": "totp", "reason": "key"})
            raise h.problem(
                503, "request.refused", reason="the authenticator key file does not match; ask an administrator"
            ) from exc

    def _code_form(request: Request, username: str, csrf: str, sealed_enrol: str | None, **ctx: Any) -> Response:
        enrol = None
        if sealed_enrol is not None:
            secret = _open(username, sealed_enrol)
            enrol = {"key": totp.grouped(secret), "uri": totp.otpauth_uri(secret, username, st.totp_issuer)}
        status = int(ctx.pop("status", 200))
        return _totp_page(h, request, status, mfa_csrf=csrf, enrol=enrol, account=username, **ctx)

    @app.get("/login/totp")
    def totp_form(request: Request) -> Response:
        token = request.cookies.get(MFA_COOKIE)
        pending = us.pending(token)
        if pending is None or token is None:
            return RedirectResponse("/login", status_code=303)
        username, csrf, sealed_enrol = pending
        sealed, _ = us.totp_state(username)
        if sealed is None:
            live, _why = us.enrol_state(username)
            if not live:  # D-192 review H2: no authenticator and no administrator's enrolment code: no way in
                us.drop_pending(token)
                resp = _totp_page(h, request, 403, no_enrol_code=True, mfa_csrf="", enrol=None, account=username)
                _clear(resp, MFA_COOKIE)
                return resp
            if sealed_enrol is None:  # a new key for this attempt
                sealed_enrol = ident.box.seal(username, totp.new_secret())
                us.set_pending_secret(token, sealed_enrol)
        return _code_form(request, username, csrf, sealed_enrol if sealed is None else None)

    @app.post("/login/totp")
    def totp_submit(
        request: Request, code: str = Form(""), mfa_csrf: str = Form(""), enrol_code: str = Form("")
    ) -> Response:
        token = request.cookies.get(MFA_COOKIE)
        pending = us.pending(token)
        if pending is None or token is None:
            return RedirectResponse("/login", status_code=303)
        username, csrf, sealed_enrol = pending
        if not mfa_csrf or not secrets.compare_digest(csrf.encode(), mfa_csrf.encode()):
            raise h.problem(400, "csrf")
        src = client_source(request)
        if us.locked(username, src):
            us.drop_pending(token)
            return _locked_page(request, username)
        sealed, last = us.totp_state(username)
        enrolling = sealed is None
        if enrolling and sealed_enrol is None:
            return RedirectResponse("/login/totp", status_code=303)
        secret = _open(username, sealed_enrol if enrolling else sealed)  # type: ignore[arg-type]
        now = ident.now()
        reason = ""
        step: int | None = None
        why = "first"
        if enrolling:
            _live, why = us.enrol_state(username)
            if not us.check_enrol_code(username, enrol_code[:64]):
                reason = "enrol_code"  # the administrator's code is wrong, used or expired
        if not reason:
            step = totp.verify(secret, code[:32], now, None if enrolling else last)
            if step is None:
                replay = not enrolling and totp.verify(secret, code[:32], now, None) is not None
                reason = "replay" if replay else "wrong"
            elif enrolling:
                try:
                    us.set_totp(username, sealed_enrol, step)  # type: ignore[arg-type]
                except AuthError:
                    reason = "wrong"
                else:
                    au.append("console.totp_enrolled", actor=f"console:{username}", detail={"kind": why})
            elif not us.use_step(username, step):
                reason = "replay"  # the same code in two tabs at once: one wins
        if reason:
            us.record_failure(username, src)
            au.append("console.login_failed", actor=f"console:{username}", detail={"factor": "totp", "reason": reason})
            ident.after_failure(username, src)
            if us.locked(username, src):
                us.drop_pending(token)
                return _locked_page(request, username)
            return _code_form(request, username, csrf, sealed_enrol if enrolling else None, failed=reason, status=401)
        us.drop_pending(token)
        us.clear_failures(username, src)
        user = us.get(username)
        if user is None:  # disabled or expired between the two steps
            resp = h.login_page(request, 401, failed=True, uninitialised=False)
            _clear(resp, MFA_COOKIE)
            return resp
        session_token = _signed_in(user, h.lang_of(request, None), "password+totp")
        # D-279: a password someone else set is replaced first
        done = RedirectResponse("/account" if us.must_change(user.username) else h.home, status_code=303)
        done.set_cookie(h.session_cookie, session_token, httponly=True, samesite="strict", secure=h.secure)
        _clear(done, MFA_COOKIE)
        return done

    # ------------------------------------------------------------------ OIDC (off by default)
    @app.get("/auth/oidc/start")
    def oidc_start(request: Request) -> Response:
        if not ident.oidc_enabled or ident.oidc_client is None:
            raise h.problem(404, "notfound")
        try:
            start = ident.oidc_client.start()
        except (OidcError, OSError, ValueError, httpx.HTTPError) as exc:  # the provider is down or misconfigured
            reason = str(exc)[:80] if isinstance(exc, OidcError) else f"provider unreachable ({type(exc).__name__})"
            au.append("console.login_failed", actor="console:-", detail={"via": "oidc", "reason": reason})
            return h.login_page(request, 502, failed=True, uninitialised=False, oidc_failed=True)
        us.put_oidc_state(start.state, start.nonce, start.verifier)
        resp = RedirectResponse(start.url, status_code=303)
        # Lax, not Strict: the browser must send it on the provider's redirect back to /auth/oidc/callback
        resp.set_cookie(
            OIDC_COOKIE, start.state, httponly=True, samesite="lax", secure=h.secure, max_age=600, path="/auth/oidc"
        )
        return resp

    @app.get("/auth/oidc/callback")
    def oidc_callback(
        request: Request,
        code: str = Query("", max_length=2048),
        state: str = Query("", max_length=256),
        error: str = Query("", max_length=200),
    ) -> Response:
        if not ident.oidc_enabled or ident.oidc_client is None:
            raise h.problem(404, "notfound")
        cookie = request.cookies.get(OIDC_COOKIE, "")
        reason = ""
        flow = None
        same_browser = bool(cookie and state and secrets.compare_digest(cookie.encode(), state.encode()))
        if error:
            code_word = "".join(ch for ch in error.lower() if ch in "abcdefghijklmnopqrstuvwxyz_")[:40]
            reason = f"provider: {code_word or 'error'}"  # an RFC 6749 error code, never the provider's free text
        elif not same_browser:
            reason = "state does not match this browser"  # checked first: another browser cannot burn the state
        pending = ident.reauth_pending(state) if same_browser else None
        if pending is not None:  # T-205: a signer re-authenticated at the provider; this opens no session
            return _reauth_back(request, pending, code, state, reason)
        if not reason:
            flow = us.take_oidc_state(state)
            if flow is None:
                reason = "unknown or expired state"
        user: User | None = None
        who = "-"
        if not reason and flow is not None:
            try:
                found = ident.oidc_client.finish(code, flow[0], flow[1])
                who = found.username[:32]
                user = us.upsert_oidc(found.username, found.subject, found.role, found.mailbox)  # type: ignore[arg-type]
            except (OidcError, AuthError) as exc:
                reason = str(exc)[:80]
            except (OSError, ValueError, httpx.HTTPError) as exc:  # network or a malformed answer
                reason = f"provider unreachable or malformed ({type(exc).__name__})"
        if user is None:
            au.append("console.login_failed", actor=f"console:{who}", detail={"via": "oidc", "reason": reason})
            resp = h.login_page(request, 403, failed=True, uninitialised=False, oidc_failed=True)
            resp.delete_cookie(OIDC_COOKIE, path="/auth/oidc")
            return resp
        session_token = _signed_in(user, h.lang_of(request, None), "oidc")
        # The provider's redirect is a cross-site navigation, so a Strict cookie set here would not be sent on a 303
        # to the home page; a page on our own origin that moves on by itself makes the next request same-site.
        resp = h.page(request, "oidc_done.html", None, 200, target=h.home)
        resp.set_cookie(h.session_cookie, session_token, httponly=True, samesite="strict", secure=h.secure)
        resp.delete_cookie(OIDC_COOKIE, path="/auth/oidc")
        return resp

    def _reauth_back(request: Request, r: Reauth, code: str, state: str, reason: str) -> Response:
        """Back from the provider for a signature (T-205): check the answer, then a page on this origin moves on to
        the page that asked (as after a sign-in, the Strict session cookie is sent only on the next request)."""
        proof = ""
        flow = us.take_oidc_state(state)  # used up whatever the provider said
        if not reason and flow is None:
            reason = "unknown or expired state"
        if not reason and flow is not None:
            try:
                proof = ident.finish_reauth(r, code, flow)
            except OidcError as exc:
                reason = str(exc)[:80]
            except (OSError, ValueError, httpx.HTTPError) as exc:
                reason = f"provider unreachable or malformed ({type(exc).__name__})"
        if reason:
            au.append("console.reauth_failed", actor=f"console:{r.username[:32]}",
                      detail={"via": "oidc", "reason": reason})  # fmt: skip
        sep = "&" if "?" in r.target else "?"
        target = f"{r.target}{sep}reauth={proof}" if proof else f"{r.target}{sep}reauth_failed=1"
        resp = h.page(request, "oidc_done.html", None, 200, target=target)
        resp.delete_cookie(OIDC_COOKIE, path="/auth/oidc")
        return resp

    # ------------------------------------------------------------------ recovery (administrators)
    def _rows() -> list[dict[str, Any]]:
        rows = []
        for u in us.users():
            sealed, _ = us.totp_state(u.username)
            until = us.locked_until(u.username, None)  # from any address (D-279)
            idp = us.is_sso(u.username)
            live, _why = us.enrol_state(u.username)
            rows.append(
                {
                    "user": u,
                    "idp": idp,
                    "totp": sealed is not None,
                    "enrol_live": live,
                    "locked_until": until.isoformat() if until else "",
                }
            )
        return rows

    def _admin_page(request: Request, sess: Session, status: int = 200, **ctx: Any) -> Response:
        rows = _rows()
        return h.page(
            request,
            "identity_admin.html",
            sess,
            status,
            rows=rows,
            unenrolled=[r for r in rows if not r["idp"] and not r["totp"]],
            mfa=st.mfa,
            oidc=ident.oidc_enabled,
            idle_minutes=int(st.idle.total_seconds() // 60),
            session_hours=int(st.absolute.total_seconds() // 3600),
            **ctx,
        )

    @app.get("/ops/identity")
    def identity_view(request: Request, done: str = "") -> Response:
        sess = h.need(request)
        if not sess.user.is_admin:
            raise h.problem(403, "forbidden")
        return _admin_page(request, sess, done=done if done in ("unlock",) else "")

    @app.post("/ops/identity")
    def identity_edit(
        request: Request,
        csrf: str = Form(""),
        action: str = Form(""),
        username: str = Form(""),
        confirm: str = Form(""),
    ) -> Response:
        sess = h.need(request)
        if not h.csrf_ok(sess, csrf):
            raise h.problem(400, "csrf")
        actor = f"console:{sess.user.username}"
        if not sess.user.is_admin:
            au.append("console.denied", actor=actor, detail={"action": "/ops/identity"})
            raise h.problem(403, "forbidden")
        name = username.strip().lower()[:32]
        if us.get(name) is None:
            raise h.problem(400, "request.refused", reason="no such account")
        if action == "unlock":
            was = us.unlock(name)
            au.append("console.unlock", actor=actor, detail={"user": name, "was_locked": was})
            return RedirectResponse("/ops/identity?done=unlock", status_code=303)
        if action not in ("reset_totp", "enrol_code"):
            raise h.problem(400, "request.refused", reason="unknown action")
        if name == sess.user.username:
            raise h.problem(400, "request.refused", reason="another administrator does this for your account")
        if us.is_sso(name):
            raise h.problem(400, "request.refused", reason="this account signs in through the identity provider")
        if action == "enrol_code":
            try:
                code = us.issue_enrol_code(name)
            except AuthError as exc:
                raise h.problem(400, "request.refused", reason=str(exc)) from exc
            au.append("console.enrol_code", actor=actor, detail={"user": name})
            # shown once, on this answer only: never in a URL, a log or the audit (as the one-time password, D-133)
            return _admin_page(request, sess, done="enrol_code", code_for=name, code=code)
        if confirm != "yes":
            text = h.translate(h.lang_of(request, sess), "identity.confirm.reset", user=name)
            return h.confirm(request, sess, text, "/ops/identity", {"action": "reset_totp", "username": name},
                             "/ops/identity")  # fmt: skip
        code = us.reset_totp(name)
        au.append("console.totp_reset", actor=actor, detail={"user": name})
        return _admin_page(request, sess, done="reset_totp", code_for=name, code=code)


# D-192 strings: joined into the console catalogues once, when this module is imported
from console.i18n_identity import EN as _ID_EN  # noqa: E402
from console.i18n_identity import JA as _ID_JA  # noqa: E402
from console.i18n_identity import ZH as _ID_ZH  # noqa: E402

EN.update(_ID_EN)
JA.update(_ID_JA)
ZH.update(_ID_ZH)
