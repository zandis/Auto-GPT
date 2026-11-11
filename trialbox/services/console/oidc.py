"""The console as an OpenID Connect client of the hospital's identity provider (D-192; Authelia in front of AD).

Off unless ``TB_OIDC_ENABLED=1``. Authorization-code flow with PKCE (S256), a ``state`` and a ``nonce`` per round trip,
the client secret sent by HTTP Basic to the token endpoint over TLS. The ID token is checked before anything in it is
used: the signature against the provider's published keys (RS256 or ES256 only; ``none`` and shared-key algorithms
are refused), the issuer, the audience, ``azp``, the expiry, the issue time and the nonce. When the provider says how
the person signed in (``amr``), a second factor is required by default (``TB_OIDC_REQUIRE_MFA``).

Roles come only from the configured group map (``TB_OIDC_GROUP_ROLES``, e.g. ``tb-coordinators:coordinator``).
A ``role`` claim, a group that is not in the map, or any other claim never gives a role; a person in no mapped group
is refused, and so is a person whose groups map to two different roles (hospital IT makes the groups exclusive), so
a directory change can never raise a role silently. The role table itself (``console.auth.User``,
``tb_common.authz``) is unchanged.

Standard library plus ``httpx`` and ``cryptography``, both already dependencies; no OIDC library.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from tb_common.http import EgressGuard, EgressRefused, GuardedTransport

from console.auth import ROLES

ALGS = ("RS256", "ES256")
MFA_AMR = frozenset({"mfa", "otp", "hwk", "swk", "pop", "sc", "fido"})  # RFC 8176 values that are a second factor
SKEW = 120  # seconds of clock difference tolerated for exp/iat
FRESH_SKEW = 30  # seconds a fresh authentication (T-205) may seem to precede the round trip that asked for it


class OidcError(Exception):
    """A sign-in through the identity provider was refused; the message is safe to audit (no token content)."""


class OidcConfigError(ValueError):
    """The OIDC settings are incomplete or unsafe; the console refuses to start."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _https(url: str) -> bool:
    p = urlparse(url)
    return p.scheme == "https" and bool(p.netloc)


@dataclass(frozen=True)
class OidcSettings:
    enabled: bool = False
    issuer: str = ""
    client_id: str = ""
    client_secret_file: Path | None = None
    redirect_url: str = ""
    group_roles: tuple[tuple[str, str], ...] = ()
    groups_claim: str = "groups"
    username_claim: str = "preferred_username"
    require_mfa: bool = True
    logout_url: str = ""
    ca_file: Path | None = None
    scopes: str = "openid profile email groups"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> OidcSettings:
        on = (env.get("TB_OIDC_ENABLED") or "0").strip().lower() in ("1", "true", "on", "yes")
        if not on:
            return cls()
        secret = (env.get("TB_OIDC_CLIENT_SECRET_FILE") or "").strip()
        ca = (env.get("TB_OIDC_CA_FILE") or "").strip()
        pairs: list[tuple[str, str]] = []
        for item in (env.get("TB_OIDC_GROUP_ROLES") or "").split(","):
            group, _, role = item.strip().rpartition(":")
            if item.strip():
                pairs.append((group.strip(), role.strip().lower()))
        obj = cls(
            enabled=True,
            issuer=(env.get("TB_OIDC_ISSUER") or "").strip().rstrip("/"),
            client_id=(env.get("TB_OIDC_CLIENT_ID") or "").strip(),
            client_secret_file=Path(secret) if secret else None,
            redirect_url=(env.get("TB_OIDC_REDIRECT_URL") or "").strip(),
            group_roles=tuple(pairs),
            groups_claim=(env.get("TB_OIDC_GROUPS_CLAIM") or "groups").strip(),
            username_claim=(env.get("TB_OIDC_USERNAME_CLAIM") or "preferred_username").strip(),
            require_mfa=(env.get("TB_OIDC_REQUIRE_MFA") or "1").strip().lower() not in ("0", "false", "off", "no"),
            logout_url=(env.get("TB_OIDC_LOGOUT_URL") or "").strip(),
            ca_file=Path(ca) if ca else None,
        )
        obj.check()
        return obj

    def check(self) -> None:
        if not _https(self.issuer):
            raise OidcConfigError("TB_OIDC_ISSUER must be an https:// address")
        if not self.client_id:
            raise OidcConfigError("TB_OIDC_CLIENT_ID is not set")
        if self.client_secret_file is None:
            raise OidcConfigError("TB_OIDC_CLIENT_SECRET_FILE is not set")
        if not _https(self.redirect_url) or not self.redirect_url.endswith("/auth/oidc/callback"):
            raise OidcConfigError("TB_OIDC_REDIRECT_URL must be https://<console host>/auth/oidc/callback")
        if not _https(self.logout_url):  # review M6: sign-out must end the provider session too
            raise OidcConfigError("TB_OIDC_LOGOUT_URL must be the provider's https:// logout address")
        if not self.group_roles:
            raise OidcConfigError("TB_OIDC_GROUP_ROLES maps no group to a role (group:role,group:role)")
        for group, role in self.group_roles:
            if not group:
                raise OidcConfigError("TB_OIDC_GROUP_ROLES has an empty group name")
            if role not in ROLES:
                raise OidcConfigError(f"TB_OIDC_GROUP_ROLES: {role!r} is not one of {', '.join(ROLES)}")

    def client_secret(self) -> str:
        assert self.client_secret_file is not None
        value = self.client_secret_file.read_text(encoding="utf-8").strip()
        if not value:
            raise OidcError("the OIDC client secret file is empty")
        return value

    def role_for(self, groups: object) -> str:
        """The one role the person's groups map to; OidcError when none or more than one."""
        if isinstance(groups, str):
            names = {groups}
        elif isinstance(groups, list):
            names = {g for g in groups if isinstance(g, str)}
        else:
            names = set()
        roles = {role for group, role in self.group_roles if group in names}
        if not roles:
            raise OidcError("no mapped group")
        if len(roles) > 1:
            raise OidcError("groups map to more than one role")
        return roles.pop()


@dataclass
class Start:
    url: str
    state: str
    nonce: str
    verifier: str


@dataclass(frozen=True)
class Identity:
    subject: str
    username: str
    role: str
    mailbox: str | None
    amr: tuple[str, ...] = ()
    auth_time: float | None = None  # when the person typed their credentials at the provider (``auth_time``)


@dataclass
class OidcClient:
    settings: OidcSettings
    transport: httpx.BaseTransport | None = None  # tests inject a mock transport
    now: Any = time.time
    _meta: dict[str, Any] = field(default_factory=dict)
    _jwks: dict[str, Any] = field(default_factory=dict)

    def _guard(self) -> EgressGuard:
        """T-212d (D-450): the issuer the operator set is a declared destination (on the box behind Caddy, or on the
        LAN); the endpoints the discovery document names are checked like any other address."""
        u = httpx.URL(self.settings.issuer or "https://invalid")
        return EgressGuard("console", extra=[(u.host, u.port or 443)])

    @contextmanager
    def _http(self) -> Iterator[httpx.Client]:
        verify: Any = True
        ca = self.settings.ca_file
        if ca is not None and ca.is_file() and ca.stat().st_size > 0:  # compose mounts /dev/null when unset
            import ssl

            verify = ssl.create_default_context(cafile=str(ca))
        # tests inject a mock transport; every real call goes through the SSRF guard (D-450)
        transport = self.transport or GuardedTransport(self._guard(), verify=verify)
        with httpx.Client(timeout=10.0, verify=verify, transport=transport, follow_redirects=False,
                          trust_env=self.transport is not None) as http:  # fmt: skip
            try:
                yield http
            except EgressRefused as exc:
                raise OidcError(f"the address is not allowed ({exc.reason}): {exc.host}") from exc

    def metadata(self) -> dict[str, Any]:
        if not self._meta:
            with self._http() as http:
                r = http.get(self.settings.issuer + "/.well-known/openid-configuration")
            if r.status_code != 200:
                raise OidcError(f"discovery answered {r.status_code}")
            meta = r.json()
            if str(meta.get("issuer", "")).rstrip("/") != self.settings.issuer:
                raise OidcError("discovery names another issuer")
            for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                if not _https(str(meta.get(key, ""))):
                    raise OidcError(f"discovery {key} is not https")
            self._meta = meta
        return self._meta

    def start(self, fresh: bool = False) -> Start:
        """The provider's address for one round trip. ``fresh`` (T-205, signing): the person must type their
        credentials again (``prompt=login``, ``max_age=0``), whatever session the provider already holds."""
        meta = self.metadata()
        state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        params = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_url,
            "scope": self.settings.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if fresh:
            params.update({"prompt": "login", "max_age": "0"})
        return Start(f"{meta['authorization_endpoint']}?{urlencode(params)}", state, nonce, verifier)

    def finish(self, code: str, nonce: str, verifier: str, fresh_since: float | None = None) -> Identity:
        """Exchange the code, verify the ID token and map the person to one role. With ``fresh_since`` (T-205, a
        re-authentication for a signature) the token must say the person authenticated at or after that time
        (``auth_time``) and with a second factor (``amr``), whatever ``TB_OIDC_REQUIRE_MFA`` says."""
        if not code or len(code) > 2048:
            raise OidcError("no code")
        meta = self.metadata()
        with self._http() as http:
            r = http.post(
                meta["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.settings.redirect_url,
                    "code_verifier": verifier,
                },
                auth=(self.settings.client_id, self.settings.client_secret()),
            )
        if r.status_code != 200:
            raise OidcError(f"token endpoint answered {r.status_code}")
        body = r.json()
        id_token = body.get("id_token")
        if not isinstance(id_token, str):
            raise OidcError("no id_token")
        claims = self.verify_id_token(id_token, nonce)
        groups = claims.get(self.settings.groups_claim)
        name = claims.get(self.settings.username_claim)
        mail = claims.get("email")
        if (groups is None or name is None) and meta.get("userinfo_endpoint") and body.get("access_token"):
            info = self._userinfo(str(meta["userinfo_endpoint"]), str(body["access_token"]))
            if info.get("sub") != claims["sub"]:
                raise OidcError("userinfo is about another subject")
            groups = info.get(self.settings.groups_claim) if groups is None else groups
            name = info.get(self.settings.username_claim) if name is None else name
            mail = info.get("email") if mail is None else mail
        amr = claims.get("amr")
        amr_t = tuple(a for a in amr if isinstance(a, str)) if isinstance(amr, list) else ()
        if (self.settings.require_mfa or fresh_since is not None) and not (MFA_AMR & set(amr_t)):
            raise OidcError("the identity provider did not report a second factor")
        auth_time = claims.get("auth_time")
        at = float(auth_time) if isinstance(auth_time, int | float) and not isinstance(auth_time, bool) else None
        if fresh_since is not None and (at is None or at < fresh_since - FRESH_SKEW or at > self.now() + SKEW):
            raise OidcError("the identity provider did not authenticate the person again")
        if not isinstance(name, str) or not name.strip():
            raise OidcError("no user name claim")
        role = self.settings.role_for(groups)
        return Identity(
            subject=str(claims["sub"]),
            username=name.strip().lower(),
            role=role,
            mailbox=mail.strip().lower() if isinstance(mail, str) and "@" in mail else None,
            amr=amr_t,
            auth_time=at,
        )

    def _userinfo(self, url: str, access_token: str) -> dict[str, Any]:
        if not _https(url):
            raise OidcError("userinfo endpoint is not https")
        with self._http() as http:
            r = http.get(url, headers={"Authorization": f"Bearer {access_token}"})
        if r.status_code != 200:
            raise OidcError(f"userinfo answered {r.status_code}")
        data = r.json()
        if not isinstance(data, dict):
            raise OidcError("userinfo is not an object")
        return data

    # ------------------------------------------------------------------ ID token
    def _keys(self, refresh: bool = False) -> dict[str, Any]:
        if refresh or not self._jwks:
            with self._http() as http:
                r = http.get(self.metadata()["jwks_uri"])
            if r.status_code != 200:
                raise OidcError(f"jwks answered {r.status_code}")
            self._jwks = {str(k.get("kid", "")): k for k in r.json().get("keys", []) if isinstance(k, dict)}
        return self._jwks

    def verify_id_token(self, token: str, nonce: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise OidcError("id_token is not a signed JWT")
        try:
            header = json.loads(_unb64url(parts[0]))
            claims = json.loads(_unb64url(parts[1]))
            sig = _unb64url(parts[2])
        except (ValueError, json.JSONDecodeError) as exc:
            raise OidcError("id_token is not readable") from exc
        if not isinstance(header, dict) or not isinstance(claims, dict):
            raise OidcError("id_token is not readable")
        alg = header.get("alg")
        if alg not in ALGS:
            raise OidcError(f"id_token algorithm {str(alg)[:10]!r} is not allowed")
        kid = str(header.get("kid", ""))
        key = self._keys().get(kid) or self._keys(refresh=True).get(kid)
        if key is None:
            raise OidcError("id_token key is unknown")
        _verify_sig(alg, key, f"{parts[0]}.{parts[1]}".encode("ascii"), sig)
        now = self.now()
        if str(claims.get("iss", "")).rstrip("/") != self.settings.issuer:
            raise OidcError("id_token issuer")
        aud = claims.get("aud")
        auds = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
        if self.settings.client_id not in auds:
            raise OidcError("id_token audience")
        if len(auds) > 1 and claims.get("azp") != self.settings.client_id:
            raise OidcError("id_token azp")
        if "azp" in claims and claims.get("azp") != self.settings.client_id:
            raise OidcError("id_token azp")
        exp, iat = claims.get("exp"), claims.get("iat")
        if not isinstance(exp, int | float) or now > exp + SKEW:
            raise OidcError("id_token expired")
        if not isinstance(iat, int | float) or iat > now + SKEW:
            raise OidcError("id_token issued in the future")
        got_nonce = claims.get("nonce")
        if not isinstance(got_nonce, str) or not secrets.compare_digest(got_nonce.encode(), nonce.encode()):
            raise OidcError("id_token nonce")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise OidcError("id_token subject")
        return claims


def _verify_sig(alg: str, jwk: Mapping[str, Any], data: bytes, sig: bytes) -> None:
    try:
        if alg == "RS256":
            if jwk.get("kty") != "RSA":
                raise OidcError("key type does not match the algorithm")
            n = int.from_bytes(_unb64url(str(jwk["n"])), "big")
            e = int.from_bytes(_unb64url(str(jwk["e"])), "big")
            rsa.RSAPublicNumbers(e, n).public_key().verify(sig, data, padding.PKCS1v15(), hashes.SHA256())
        else:  # ES256
            if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256" or len(sig) != 64:
                raise OidcError("key type does not match the algorithm")
            x = int.from_bytes(_unb64url(str(jwk["x"])), "big")
            y = int.from_bytes(_unb64url(str(jwk["y"])), "big")
            pub = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
            der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
            pub.verify(der, data, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise OidcError("id_token signature") from exc
    except (KeyError, ValueError) as exc:
        raise OidcError("id_token key is unreadable") from exc
