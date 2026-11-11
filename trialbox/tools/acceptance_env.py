"""The acceptance environment (T-213a, D-410; CR-071, OPS-051): the box's own stack with the identity overlay and the
mirrors a hospital would give it (a test directory, a real-shaped mail server, a test CA), on the acceptance box (the
owner's B200 or the rental workstation). Not ``tools/acceptance.py``, which is the site go-live acceptance (D-83).

    python -m tools.acceptance_env plan    [--gpu NAME] [--dir DIR] [--json]   # the steps and commands; runs nothing
    sudo python3 -m tools.acceptance_env prepare [--dir DIR] [--bind ADDR] [--force]   # the files under DIR
    python -m tools.acceptance_env up      [--gpu NAME] [--dir DIR] [--dry-run]
    python -m tools.acceptance_env check   [--gpu NAME] [--dir DIR] [--dry-run] # writes DIR/record.json
    python -m tools.acceptance_env down    [--gpu NAME] [--dir DIR] [--volumes] [--dry-run]

``prepare`` writes, under DIR (default ``deploy/site/acceptance``, not in git): a test CA (its key is not kept), the
site certificate for ``TB_TLS_MODE=hospital`` naming the console and the Authelia host, the directory's and the mail
server's certificates, the Authelia configuration (``deploy/identity/authelia/configuration.example.yml`` with every
SITE value replaced by the acceptance one and the client secret's digest), Authelia's secrets, the console's client
secret, the directory's settings and seed (synthetic accounts, one per role plus two that must be refused), the mail
keystore, ``acceptance.env`` (the compose variables) and ``accounts.txt`` (who signs in as what; the passwords stay in
``directory/passwords/``). Every secret file is 0600 and owned by the container user that reads it when run as root.
Nothing secret is printed. ``--dry-run`` prints the docker commands without running them. ``check`` reads compose's
own state (every service healthy, every one-shot exited 0) and makes two HTTPS requests through Caddy, verified
against the test CA: the console answers, and Authelia's OpenID configuration names the acceptance issuer (Authelia
is healthy only after it bound to the directory over LDAPS with the read-only account).
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
DEFAULT_DIR = DEPLOY / "site" / "acceptance"
AUTHELIA_TEMPLATE = DEPLOY / "identity" / "authelia" / "configuration.example.yml"
OVERLAY = "docker-compose.acceptance.yml"
GPU_OVERLAYS = ("gb10", "rtx5090", "rtxpro6000", "shared-quota")
MARKER = "acceptance.env"  # written last by prepare; --force removes only a folder that has it

DOMAIN = "acceptance.test"
CONSOLE_HOST = f"trialbox.{DOMAIN}"
AUTH_HOST = f"auth.{DOMAIN}"
DIRECTORY_HOST = f"dc01.{DOMAIN}"
MAIL_HOST = f"mail.{DOMAIN}"
BASE_DN = "dc=acceptance,dc=test"
BIND_ACCOUNT = "svc-trialbox"
DIRECTORY_UID = 1000  # the lldap user of the directory image
CONSOLE_UID = 10001  # the tb user of trialbox-py (tools/trialbox/svc_secrets.py SERVICE_UID)
PBKDF2_ROUNDS = 310000

# directory group -> console role (TB_OIDC_GROUP_ROLES)
ROLE_GROUPS = {
    "TB-Admins": "admin",
    "TB-Coordinators": "coordinator",
    "TB-Investigators": "investigator",
    "TB-Monitors": "cro",
    "TB-Viewers": "viewer",
}


@dataclass(frozen=True)
class Account:
    uid: str
    groups: tuple[str, ...]
    expect: str  # the console role, or "refused"


ACCOUNTS = (
    Account("acc-admin", ("TB-Admins",), "admin"),
    Account("acc-coordinator", ("TB-Coordinators",), "coordinator"),
    Account("acc-investigator", ("TB-Investigators",), "investigator"),
    Account("acc-monitor", ("TB-Monitors",), "cro"),
    Account("acc-viewer", ("TB-Viewers",), "viewer"),
    Account("acc-norole", (), "refused"),  # in no mapped group
    Account("acc-tworoles", ("TB-Coordinators", "TB-Investigators"), "refused"),  # two different roles
)

# the SITE values of the Authelia template and their acceptance values: each must occur exactly once
AUTHELIA_REPLACEMENTS = (
    ("implementation: activedirectory", "implementation: lldap"),
    ("address: ldaps://dc01.hospital.example:636", f"address: ldaps://{DIRECTORY_HOST}:6360"),
    ("server_name: dc01.hospital.example", f"server_name: {DIRECTORY_HOST}"),
    ("base_dn: DC=hospital,DC=example", "base_dn: DC=acceptance,DC=test"),
    ("additional_users_dn: OU=Staff", "additional_users_dn: OU=people"),
    ("additional_groups_dn: OU=Groups", "additional_groups_dn: OU=groups"),
    ("group_search_mode: memberof", "group_search_mode: filter"),  # LLDAP's groups filter, not AD's memberOf
    (
        "user: CN=svc-trialbox,OU=Service Accounts,DC=hospital,DC=example",
        f"user: UID={BIND_ACCOUNT},OU=people,DC=acceptance,DC=test",
    ),
    ("- domain: auth.trialbox.hospital.example", f"- domain: {AUTH_HOST}"),
    ("authelia_url: https://auth.trialbox.hospital.example", f"authelia_url: https://{AUTH_HOST}"),
    ("default_redirection_url: https://trialbox.hospital.example", f"default_redirection_url: https://{CONSOLE_HOST}"),
    ("- https://trialbox.hospital.example/auth/oidc/callback", f"- https://{CONSOLE_HOST}/auth/oidc/callback"),
)
CLIENT_SECRET_LINE = 'client_secret: "$pbkdf2-sha512$310000$SITE-REPLACE-WITH-THE-DIGEST"'

ENV_TEMPLATE = """\
# Written by `python -m tools.acceptance_env prepare` (T-213a, D-410): the compose variables of the acceptance
# environment, read after deploy/.env (--env-file). Secret: 0600. Never copy it to a hospital box.
TB_ACCEPTANCE_DIR={dir}
TB_TLS_HOSTNAME={console}
TB_TLS_MODE=hospital
TB_TLS_CERT_FILE={dir}/tls/site.crt
TB_TLS_KEY_FILE={dir}/tls/site.key
TB_TLS_BIND={bind}
TB_AUTH_HOSTNAME={auth}
TB_AUTHELIA_CONFIG={dir}/authelia/configuration.yml
TB_OIDC_ENABLED=1
TB_OIDC_ISSUER=https://{auth}
TB_OIDC_CLIENT_ID=trialbox-console
TB_OIDC_CLIENT_SECRET={dir}/console/oidc_client_secret.txt
TB_OIDC_LOGOUT_URL=https://{auth}/logout
TB_OIDC_CA={dir}/ca/ca.crt
TB_OIDC_GROUP_ROLES={roles}
TB_OIDC_REQUIRE_MFA=1
TB_EXTRA_CA={dir}/ca/ca.crt
TB_ACCEPTANCE_MAIL_PASSWORD={mail_password}
TB_ACCEPTANCE_MAIL_KEYSTORE_PASSWORD={keystore_password}
"""


class AcceptanceError(Exception):
    """A refusal the operator can fix (printed without a traceback)."""


# ------------------------------------------------------------------------------------------------------- the stack
@dataclass(frozen=True)
class Stack:
    dir: Path = DEFAULT_DIR
    gpu: str | None = None
    deploy: Path = DEPLOY

    def files(self) -> list[str]:
        """The compose files in the order a box adds them: base, secrets, the GPU overlay, identity, acceptance."""
        out = ["docker-compose.yml", "docker-compose.secrets.yml"]
        if self.gpu:
            out.append(f"docker-compose.{self.gpu}.yml")
        return [*out, "docker-compose.identity.yml", OVERLAY]

    def profiles(self) -> list[str]:
        return ["gpu" if self.gpu else "stub", "oidc"]

    def compose(self, *args: str) -> list[str]:
        argv = ["docker", "compose", "--project-directory", str(self.deploy)]
        argv += ["--env-file", str(self.deploy / ".env"), "--env-file", str(self.dir / MARKER)]
        for f in self.files():
            argv += ["-f", str(self.deploy / f)]
        for p in self.profiles():
            argv += ["--profile", p]
        return [*argv, *args]


def plan(stack: Stack) -> list[dict[str, str]]:
    """The steps, in order, with the command of each. Runs nothing."""
    me = "python -m tools.acceptance_env"
    gpu = f" --gpu {stack.gpu}" if stack.gpu else ""
    where = f" --dir {stack.dir}" if stack.dir != DEFAULT_DIR else ""
    return [
        {"step": "service tokens (once per box; the secrets overlay mounts them)",
         "command": "sudo python3 -m tools.trialbox secrets init"},
        {"step": "the acceptance files: test CA, certificates, Authelia, directory seed, mail keystore",
         "command": f"sudo python3 -m tools.acceptance_env prepare{where}"},  # root: each file to its reader
        {"step": "name the hosts on the box (the browser's machine)",
         "command": f"echo '127.0.0.1 {CONSOLE_HOST} {AUTH_HOST}' | sudo tee -a /etc/hosts"},
        {"step": "start the stack with the identity overlay and wait until every service is healthy",
         "command": " ".join(stack.compose("up", "-d", "--wait"))},
        {"step": "check compose's state and the two HTTPS answers; write the record",
         "command": f"{me} check{gpu}{where}"},
        {"step": "sign in once per account of accounts.txt (each role; acc-norole and acc-tworoles are refused)",
         "command": f"https://{CONSOLE_HOST}/login"},
        {"step": "stop (add --volumes to forget the directory's and Authelia's state)",
         "command": f"{me} down{gpu}{where}"},
    ]  # fmt: skip


def preflight(stack: Stack) -> list[str]:
    """What is missing before ``up``: the box's deploy/.env, the service tokens, the prepared folder."""
    out = []
    if not (stack.deploy / ".env").is_file():
        out.append(f"{stack.deploy / '.env'} is missing (copy .env.example and set POSTGRES_PASSWORD, TB_TZ)")
    if not (stack.deploy / "secrets" / "services").is_dir():
        out.append("no service tokens: sudo python3 -m tools.trialbox secrets init")
    if not (stack.dir / MARKER).is_file():
        out.append(f"{stack.dir} is not prepared: python -m tools.acceptance_env prepare --dir {stack.dir}")
    if stack.gpu and not (stack.deploy / f"docker-compose.{stack.gpu}.yml").is_file():
        out.append(f"no overlay docker-compose.{stack.gpu}.yml")
    return out


# --------------------------------------------------------------------------------------------------------- prepare
def _ab64(raw: bytes) -> str:
    """The adapted base64 of the PHC/crypt strings Authelia reads ('.' for '+', no padding)."""
    return base64.b64encode(raw).decode("ascii").rstrip("=").replace("+", ".")


def client_secret_digest(secret: str, salt: bytes | None = None, rounds: int = PBKDF2_ROUNDS) -> str:
    """``$pbkdf2-sha512$<rounds>$<salt>$<key>``: what Authelia's ``crypto hash generate pbkdf2 --variant sha512``
    writes, so the configuration holds the digest and only the console holds the secret."""
    salt = salt if salt is not None else os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha512", secret.encode("utf-8"), salt, rounds, 64)
    return f"$pbkdf2-sha512${rounds}${_ab64(salt)}${_ab64(key)}"


def _unab64(text: str) -> bytes:
    return base64.b64decode(text.replace(".", "+") + "=" * (-len(text) % 4))


def verify_client_secret(secret: str, digest: str) -> bool:
    _, scheme, rounds, salt, key = digest.split("$")
    if scheme != "pbkdf2-sha512":
        return False
    want = _unab64(key)
    got = hashlib.pbkdf2_hmac("sha512", secret.encode("utf-8"), _unab64(salt), int(rounds), len(want))
    return hmac.compare_digest(got, want)


def render_authelia(template: str, client_digest: str) -> str:
    """The site template with each SITE value replaced; refuses a template whose SITE lines moved."""
    out = template
    for old, new in (*AUTHELIA_REPLACEMENTS, (CLIENT_SECRET_LINE, f'client_secret: "{client_digest}"')):
        n = out.count(old)
        if n != 1:
            raise AcceptanceError(f"{AUTHELIA_TEMPLATE.name}: {old!r} occurs {n} times (expected once)")
        out = out.replace(old, new)
    if "hospital.example" in out or "SITE-REPLACE" in out:
        raise AcceptanceError(f"{AUTHELIA_TEMPLATE.name}: a SITE value is left after the replacements")
    head = (
        "# Generated by `python -m tools.acceptance_env prepare` (T-213a, D-410) from\n"
        "# deploy/identity/authelia/configuration.example.yml: the SITE values are the acceptance environment's\n"
        "# (the directory is LLDAP, so `implementation: lldap`). Never copy it to a hospital box.\n"
        "certificates_directory: /config/certificates   # the acceptance test CA (LDAPS to the test directory)\n\n"
    )
    return head + out


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TrialBox acceptance"),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])  # fmt: skip


CA_USAGE = x509.KeyUsage(
    digital_signature=False,
    content_commitment=False,
    key_encipherment=False,
    data_encipherment=False,
    key_agreement=False,
    key_cert_sign=True,
    crl_sign=True,
    encipher_only=False,
    decipher_only=False,
)


def make_ca(days: int = 365) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = _key()
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name("TrialBox acceptance test CA"))
        .issuer_name(_name("TrialBox acceptance test CA"))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(CA_USAGE, critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def issue(ca_key: rsa.RSAPrivateKey, ca: x509.Certificate, names: Sequence[str], days: int = 365
          ) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:  # fmt: skip
    """A server certificate for ``names`` (DNS names, or IP addresses), signed by the test CA."""
    key = _key()
    now = dt.datetime.now(dt.UTC)
    alt: list[x509.GeneralName] = []
    for n in names:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            alt.append(x509.DNSName(n))
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(names[0]))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _pem_key(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())  # fmt: skip


def _pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _write(path: Path, data: str | bytes, mode: int = 0o600, uid: int | None = None) -> None:
    """Create ``path`` with ``mode`` from the start (no moment with wider permissions); chown to ``uid`` as root."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)
    os.chmod(path, mode)
    if uid is not None and os.geteuid() == 0:
        os.chown(path, uid, uid)


def _own_tree(folder: Path, uid: int) -> None:
    if os.geteuid() != 0:
        return
    for p in [folder, *folder.rglob("*")]:
        os.chown(p, uid, uid)


def _secret() -> str:
    return secrets.token_hex(32)  # hex: safe in GreenMail's user:password@domain and in TOML


def lldap_config(jwt_secret: str, admin_password: str, key_seed: str) -> str:
    return f"""\
# Written by `python -m tools.acceptance_env prepare` (T-213a, D-410): the acceptance test directory. Secret: 0600.
ldap_host = "0.0.0.0"
ldap_port = 3890
http_host = "0.0.0.0"
http_port = 17170
http_url = "http://acceptance-directory:17170"
jwt_secret = "{jwt_secret}"
ldap_base_dn = "{BASE_DN}"
ldap_user_dn = "admin"
ldap_user_email = "admin@{DOMAIN}"
ldap_user_pass = "{admin_password}"
force_ldap_user_pass_reset = false
database_url = "sqlite:///data/users.db?mode=rwc"
key_seed = "{key_seed}"

[ldaps_options]
enabled = true
port = 6360
cert_file = "/run/directory/tls/directory.crt"
key_file = "/run/directory/tls/directory.key"
"""


def seed_users() -> list[dict[str, Any]]:
    """The directory's accounts as LLDAP's bootstrap reads them (one JSON per account)."""
    rows: list[dict[str, Any]] = [
        {"id": a.uid, "email": f"{a.uid}@{DOMAIN}", "displayName": f"Acceptance {a.uid.removeprefix('acc-')}",
         "password_file": f"/run/directory/passwords/{a.uid}", "groups": list(a.groups)}
        for a in ACCOUNTS
    ]  # fmt: skip
    rows.append({"id": BIND_ACCOUNT, "email": f"{BIND_ACCOUNT}@{DOMAIN}", "displayName": "TrialBox bind account",
                 "password_file": f"/run/directory/passwords/{BIND_ACCOUNT}",
                 "groups": ["lldap_strict_readonly"]})  # fmt: skip
    return rows


def accounts_text() -> str:
    lines = ["# The acceptance accounts (synthetic). Passwords: directory/passwords/<account> (0600).",
             "# account            groups                               expected at the console sign-in"]  # fmt: skip
    for a in ACCOUNTS:
        expect = f"role {a.expect}" if a.expect != "refused" else "refused (audited console.login_failed, via oidc)"
        lines.append(f"{a.uid:<20} {','.join(a.groups) or '-':<36} {expect}")
    lines.append(f"{BIND_ACCOUNT:<20} {'lldap_strict_readonly':<36} Authelia's read-only bind account; no sign-in")
    return "\n".join(lines) + "\n"


@dataclass
class Prepared:
    dir: Path
    files: list[Path] = field(default_factory=list)


def prepare(target: Path, bind: str = "127.0.0.1", force: bool = False, template: Path = AUTHELIA_TEMPLATE) -> Prepared:
    """Write the acceptance files under ``target``. Refuses a folder that has files unless ``force``, and with
    ``force`` removes only a folder this tool made (it holds acceptance.env)."""
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        if not force:
            raise AcceptanceError(f"{target} is not empty: prepare again with --force (every secret is new)")
        if not (target / MARKER).is_file():
            raise AcceptanceError(f"{target} has no {MARKER}: not made by this tool, not removed")
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    os.chmod(target, 0o755)  # the containers' users enter it; every secret inside is 0600
    done = Prepared(target)

    def put(rel: str, data: str | bytes, mode: int = 0o600, uid: int | None = None) -> None:
        _write(target / rel, data, mode, uid)
        done.files.append(target / rel)

    ca_key, ca = make_ca()
    put("ca/ca.crt", _pem(ca), 0o644)  # public; the CA key is never written
    site_key, site = issue(ca_key, ca, [CONSOLE_HOST, AUTH_HOST])
    put("tls/site.crt", _pem(site) + _pem(ca), 0o644)
    put("tls/site.key", _pem_key(site_key))  # Caddy runs as root
    dir_key, dir_cert = issue(ca_key, ca, [DIRECTORY_HOST, "acceptance-directory", "localhost"])
    mail_key, mail_cert = issue(ca_key, ca, [MAIL_HOST, "acceptance-mail"])
    del ca_key

    # Authelia (runs as root): the configuration and its secrets
    client_secret = secrets.token_urlsafe(48)
    bind_password = _secret()
    put("authelia/configuration.yml", render_authelia(template.read_text(encoding="utf-8"),
                                                      client_secret_digest(client_secret)))  # fmt: skip
    for name in ("jwt_secret", "session_secret", "storage_key", "oidc_hmac"):
        put(f"authelia/secrets/{name}", _secret())
    put("authelia/secrets/ldap_password", bind_password)
    put("authelia/secrets/oidc_jwks.pem", _pem_key(_key()))
    put("console/oidc_client_secret.txt", client_secret, uid=CONSOLE_UID)

    # the directory (uid 1000): settings, LDAPS certificate, seed
    admin_password = _secret()
    put("directory/lldap_config.toml", lldap_config(_secret(), admin_password, _secret()))
    put("directory/admin_password", admin_password)
    put("directory/tls/directory.crt", _pem(dir_cert) + _pem(ca), 0o644)
    put("directory/tls/directory.key", _pem_key(dir_key))
    for row in seed_users():
        password = bind_password if row["id"] == BIND_ACCOUNT else secrets.token_urlsafe(18)
        put(f"directory/passwords/{row['id']}", password)
        put(f"directory/users/{row['id']}.json", json.dumps(row, indent=1) + "\n", 0o644)
    for group in ROLE_GROUPS:
        put(f"directory/groups/{group}.json", json.dumps({"name": group}) + "\n", 0o644)
    _own_tree(target / "directory", DIRECTORY_UID)

    # the mail server: a password-encrypted keystore (GreenMail's user is not known in advance, so 0644)
    keystore_password = _secret()
    p12 = pkcs12.serialize_key_and_certificates(
        b"acceptance-mail", mail_key, mail_cert, [ca],
        serialization.BestAvailableEncryption(keystore_password.encode("ascii")),
    )  # fmt: skip
    put("mail/mail.p12", p12, 0o644)

    put("accounts.txt", accounts_text(), 0o644)
    roles = ",".join(f"{g}:{r}" for g, r in ROLE_GROUPS.items())
    put(MARKER, ENV_TEMPLATE.format(dir=target, console=CONSOLE_HOST, auth=AUTH_HOST, bind=bind, roles=roles,
                                    mail_password=_secret(), keystore_password=keystore_password))  # fmt: skip
    return done


def env_names(env_file: Path) -> set[str]:
    """The variable names an env file sets (the process environment would override them in compose)."""
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        text = ENV_TEMPLATE
    return {ln.split("=", 1)[0].strip() for ln in text.splitlines() if "=" in ln and not ln.lstrip().startswith("#")}


def compose_env(stack: Stack) -> dict[str, str]:
    """The caller's environment without what would override acceptance.env or choose other compose files."""
    drop = env_names(stack.dir / MARKER)
    return {k: v for k, v in os.environ.items() if k not in drop and not k.startswith("COMPOSE_")}


# ----------------------------------------------------------------------------------------------------------- check
def _rows(ps_output: str) -> list[dict[str, Any]]:
    """``docker compose ps --format json``: one JSON object per line (compose v2.21+) or one array (older)."""
    text = ps_output.strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        return [r for r in data if isinstance(r, dict)]
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def evaluate_ps(config: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    """Each service of the rendered config against compose's state: a long-running service is running and healthy
    (or running, without a check); a one-shot (restart "no") exited 0."""
    by_service: dict[str, dict[str, Any]] = {}
    for r in rows:
        by_service.setdefault(str(r.get("Service", "")), r)
    states: dict[str, str] = {}
    problems: list[str] = []
    for name, body in sorted((config.get("services") or {}).items()):
        row = by_service.get(name)
        if row is None:
            states[name] = "absent"
            problems.append(f"{name}: no container")
            continue
        state, health = str(row.get("State", "")), str(row.get("Health", ""))
        one_shot = str(body.get("restart", "")) == "no"
        if one_shot:
            code = int(row.get("ExitCode", -1))
            states[name] = f"{state} ({code})"
            if state != "exited" or code != 0:
                problems.append(f"{name}: one-shot {state}, exit code {code}")
        else:
            states[name] = f"{state}/{health or '-'}"
            if state != "running" or (health and health != "healthy"):
                problems.append(f"{name}: {state}, health {health or 'none'}")
    return states, problems


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to ``addr`` with SNI and certificate checks for ``host`` (the box needs no hosts entry for the check)."""

    def __init__(self, addr: str, host: str, port: int, ctx: ssl.SSLContext, timeout: float) -> None:
        super().__init__(host, port, context=ctx, timeout=timeout)
        self._addr, self._ctx = addr, ctx

    def connect(self) -> None:
        raw = socket.create_connection((self._addr, self.port), self.timeout)
        self.sock = self._ctx.wrap_socket(raw, server_hostname=self.host)


def https_get(addr: str, port: int, host: str, path: str, ca_file: Path, timeout: float = 10.0) -> tuple[int, bytes]:
    ctx = ssl.create_default_context(cafile=str(ca_file))
    conn = _PinnedHTTPS(addr, host, port, ctx, timeout)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        return resp.status, resp.read(1 << 20)
    finally:
        conn.close()


def probes(addr: str, port: int, ca_file: Path) -> tuple[dict[str, str], list[str]]:
    """The console answers on 443 and Authelia's OpenID configuration names the acceptance issuer."""
    out: dict[str, str] = {}
    problems: list[str] = []
    try:
        status, _ = https_get(addr, port, CONSOLE_HOST, "/login", ca_file)
        out["console"] = f"HTTP {status}"
        if status >= 500:
            problems.append(f"console: HTTP {status}")
    except (OSError, ssl.SSLError, http.client.HTTPException) as e:
        out["console"] = f"error {type(e).__name__}"
        problems.append(f"console: {e}")
    try:
        status, body = https_get(addr, port, AUTH_HOST, "/.well-known/openid-configuration", ca_file)
        issuer = json.loads(body).get("issuer") if status == 200 else None
        out["oidc"] = f"HTTP {status}, issuer {issuer}"
        if issuer != f"https://{AUTH_HOST}":
            problems.append(f"oidc: HTTP {status}, issuer {issuer!r}")
    except (OSError, ssl.SSLError, http.client.HTTPException, ValueError) as e:
        out["oidc"] = f"error {type(e).__name__}"
        problems.append(f"oidc: {e}")
    return out, problems


def _bind(stack: Stack) -> str:
    for ln in (stack.dir / MARKER).read_text(encoding="utf-8").splitlines():
        if ln.startswith("TB_TLS_BIND="):
            value = ln.split("=", 1)[1].strip()
            try:
                every = ipaddress.ip_address(value).is_unspecified  # every address: ask the loopback
            except ValueError:
                every = not value
            return "127.0.0.1" if every else value
    return "127.0.0.1"


def check(stack: Stack, port: int = 443) -> int:
    env = compose_env(stack)
    cfg = subprocess.run(stack.compose("config", "--format", "json"), capture_output=True, text=True, env=env,
                         check=False, timeout=120)  # fmt: skip
    if cfg.returncode:
        print(f"check: docker compose config failed: {cfg.stderr.strip()[-500:]}", file=sys.stderr)
        return 1
    ps = subprocess.run(stack.compose("ps", "--all", "--format", "json"), capture_output=True, text=True, env=env,
                        check=False, timeout=120)  # fmt: skip
    states, problems = evaluate_ps(json.loads(cfg.stdout), _rows(ps.stdout))
    answers, bad = probes(_bind(stack), port, stack.dir / "ca" / "ca.crt")
    problems += bad
    record = {
        "format": "trialbox-acceptance-env/1",
        "card": "T-213a",
        "decision": "D-410",
        "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "files": stack.files(),
        "profiles": stack.profiles(),
        "services": states,
        "probes": answers,
        "problems": problems,
        "passed": not problems,
    }
    _write(stack.dir / "record.json", json.dumps(record, indent=1) + "\n", 0o644)
    for name, state in states.items():
        print(f"  {name:<28} {state}")
    for name, answer in answers.items():
        print(f"  {name:<28} {answer}")
    print(f"check: {'PASS' if not problems else 'FAIL'} ({stack.dir / 'record.json'})")
    for p in problems:
        print(f"  - {p}")
    return 0 if not problems else 1


# ------------------------------------------------------------------------------------------------------------ main
def _run(argv: list[str], stack: Stack, dry_run: bool) -> int:
    print("$ " + " ".join(argv))
    if dry_run:
        return 0
    return subprocess.run(argv, env=compose_env(stack), check=False).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.acceptance_env", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "prepare", "up", "check", "down"):
        p = sub.add_parser(name)
        p.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="the acceptance folder (default %(default)s)")
        if name != "prepare":
            p.add_argument("--gpu", choices=GPU_OVERLAYS, help="the GPU overlay (none: the stub model)")
        if name in ("up", "check", "down"):
            p.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")
    sub.choices["plan"].add_argument("--json", action="store_true")
    sub.choices["prepare"].add_argument("--bind", default="127.0.0.1", help="the address 443 listens on")
    sub.choices["prepare"].add_argument("--force", action="store_true", help="replace a folder made by this tool")
    sub.choices["down"].add_argument("--volumes", action="store_true", help="also remove the volumes")
    args = ap.parse_args(argv)
    stack = Stack(dir=args.dir.resolve(), gpu=getattr(args, "gpu", None))
    try:
        if args.cmd == "plan":
            steps = plan(stack)
            if args.json:
                print(json.dumps({"files": stack.files(), "profiles": stack.profiles(), "steps": steps}, indent=1))
            else:
                for n, s in enumerate(steps, 1):
                    print(f"{n}. {s['step']}\n   {s['command']}")
            return 0
        if args.cmd == "prepare":
            done = prepare(stack.dir, bind=args.bind, force=args.force)
            print(f"prepare: {len(done.files)} files under {done.dir} (secrets 0600, never printed)")
            print(f"  compose variables: {done.dir / MARKER}")
            print(f"  accounts:          {done.dir / 'accounts.txt'}")
            print(f"  next:              python -m tools.acceptance_env up --dir {done.dir}")
            return 0
        if args.cmd == "up":
            missing = preflight(stack)
            if missing and not args.dry_run:
                raise AcceptanceError("not ready:\n  " + "\n  ".join(missing))
            rc = _run(stack.compose("config", "--quiet"), stack, args.dry_run)
            return rc or _run(stack.compose("up", "-d", "--wait"), stack, args.dry_run)
        if args.cmd == "check":
            if args.dry_run:
                print("$ " + " ".join(stack.compose("config", "--format", "json")))
                print("$ " + " ".join(stack.compose("ps", "--all", "--format", "json")))
                print(f"GET https://{CONSOLE_HOST}/login and https://{AUTH_HOST}/.well-known/openid-configuration "
                      f"(trusting {stack.dir / 'ca' / 'ca.crt'}); record {stack.dir / 'record.json'}")  # fmt: skip
                return 0
            if not (stack.dir / MARKER).is_file():
                raise AcceptanceError(f"{stack.dir} is not prepared")
            return check(stack)
        down = ["down", "--volumes"] if args.volumes else ["down"]
        return _run(stack.compose(*down), stack, args.dry_run)
    except AcceptanceError as e:
        print(f"acceptance_env: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
