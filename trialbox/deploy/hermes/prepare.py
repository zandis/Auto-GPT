#!/usr/bin/env python3
"""Deploy-time material for the Hermes fragment (spec v4 §9.2-§9.4; S1-11). Never commit its output.

    python deploy/hermes/prepare.py --admin-email admin@hospa.test            # DEV/TEST (POC)
    python deploy/hermes/prepare.py --env PRODUCTION --directory site/directory.yaml

Writes into ``deploy/secrets/hermes/`` (gitignored; ``--out`` to move it):

* an internal CA (``tb-ca.pem``; the CA key is used once and not written) and one certificate per service, each with
  its DNS name as CN and SAN and both TLS client and server usage: ``hermes-client.*`` (CN ``hermes``: MCP client,
  relay-reply client, inject-listener server), ``frontdoor-mcp.*``, ``channel-relay.*``;
* the relay's ES256 assertion key (``relay-signing.key``, channel-relay only) and its public half (``relay.pub``,
  frontdoor-mcp only). In production the private key lives in the key service (§9.4); this file is the DEV/TEST
  stand-in;
* ``directory.yaml``: groups, delegations and Teams object ids. DEV/TEST builds it from ``--admin-email``; elsewhere
  pass the export generated from the directory groups (HER-16);
* ``hermes-config.yaml`` (DEV/TEST only): the committed profile with the two values the DEV/TEST gateway routes
  differ on: the model alias (``--model``, default the committed ``f-frontdesk``, which DEV/TEST serve from the stub
  build ``f-frontdesk-stub-1``; DEV with OpenRouter and the on-box GPU stack: ``j-workhorse``) and
  ``X-TB-Data-Class: D0`` (DEV and TEST hold D0 only, §17.8; D3 calls need a live study step, LLM-2). VALIDATION and
  PRODUCTION mount the committed profile unchanged.

Certificates carry SKI/AKI (Python 3.13+ verifies X.509 strictly). Private keys are ``0600`` and owned by the
container user that reads them (Hermes ``10000``, TrialBox ``10001``) when the script runs as root; otherwise
``0644`` inside a ``0700`` directory, with a warning.
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "deploy" / "secrets" / "hermes"
HERMES_UID = 10000
TB_UID = 10001
SERVICES = {
    "hermes-client": ("hermes", HERMES_UID),
    "frontdoor-mcp": ("frontdoor-mcp", TB_UID),
    "channel-relay": ("channel-relay", TB_UID),
}
DEV_ENVS = ("DEV", "TEST")
VALIDITY = dt.timedelta(days=90)


def _name(cn: str) -> x509.Name:
    return x509.Name(
        [x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TrialBox"), x509.NameAttribute(NameOID.COMMON_NAME, cn)]
    )


def _key_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def make_ca(now: dt.datetime) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name("TrialBox internal CA"))
        .issuer_name(_name("TrialBox internal CA"))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def issue(
    ca_key: ec.EllipticCurvePrivateKey, ca: x509.Certificate, cn: str, now: dt.datetime, extra_dns: tuple[str, ...] = ()
) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    sans: list[x509.GeneralName] = [x509.DNSName(cn), *(x509.DNSName(d) for d in extra_dns)]
    sans.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
        )
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _write(path: Path, data: bytes, *, private: bool = False, uid: int | None = None) -> None:
    path.write_bytes(data)
    if not private:
        path.chmod(0o644)
        return
    if os.geteuid() == 0 and uid is not None:
        os.chown(path, uid, uid)
        path.chmod(0o600)
    else:
        path.chmod(0o644)  # the directory is 0700; the container user must be able to read it
        print(f"prepare: warning: {path.name} is 0644 (run as root to give it to uid {uid} with 0600)", file=sys.stderr)


def poc_directory(admin: str) -> dict[str, Any]:
    """DEV/TEST directory: the POC administrator is research office, CRC and steward on the demo study GZQO."""
    return {
        "groups": {"TB-CRC": [admin], "TB-Research-Office": [admin], "TB-Steward": [admin]},
        "delegations": {admin: ["GZQO"]},
        "addresses": {admin: admin},
        "teams": {"aad-poc-admin": admin},
    }


def render_dev_profile(profile: Path, model: str) -> str:
    """The committed profile with the DEV/TEST model alias and data class; everything else unchanged."""
    cfg = yaml.safe_load(profile.read_text(encoding="utf-8"))
    cfg["model"]["default"] = model
    cfg["model"]["default_headers"]["X-TB-Data-Class"] = "D0"
    head = (
        f"# GENERATED by deploy/hermes/prepare.py from {profile.relative_to(ROOT)} for DEV/TEST only: model "
        f"{model!r}, X-TB-Data-Class D0. Do not edit; do not use outside DEV/TEST.\n"
    )
    return head + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--env", default=os.environ.get("TB_ENV", "TEST"))
    ap.add_argument("--profile", default=os.environ.get("TB_HERMES_PROFILE", "tb-staff"))
    ap.add_argument("--model", default=os.environ.get("TB_HERMES_DEV_MODEL", "f-frontdesk"))
    ap.add_argument("--admin-email", default=os.environ.get("TB_POC_ADMIN_EMAIL", "admin@hospa.test"))
    ap.add_argument("--directory", type=Path, help="directory export (required outside DEV/TEST)")
    ap.add_argument("--force", action="store_true", help="re-issue everything (old certificates stop working)")
    a = ap.parse_args(argv)
    env = a.env.upper()
    out: Path = a.out
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    now = dt.datetime.now(dt.UTC)
    if a.force or not (out / "tb-ca.pem").exists():
        ca_key, ca = make_ca(now)
        _write(out / "tb-ca.pem", ca.public_bytes(serialization.Encoding.PEM))
        for stem, (cn, uid) in SERVICES.items():
            key, cert = issue(ca_key, ca, cn, now)
            _write(out / f"{stem}.pem", cert.public_bytes(serialization.Encoding.PEM))
            _write(out / f"{stem}.key", _key_pem(key), private=True, uid=uid)
        del ca_key  # the CA key is never written: re-run with --force to rotate
        relay = ec.generate_private_key(ec.SECP256R1())
        _write(out / "relay-signing.key", _key_pem(relay), private=True, uid=TB_UID)
        pub = relay.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        _write(out / "relay.pub", pub)
        print(f"prepare: issued CA, service certificates and the relay assertion key in {out}")
    if a.directory:
        directory = yaml.safe_load(a.directory.read_text(encoding="utf-8"))
    elif env in DEV_ENVS:
        directory = poc_directory(a.admin_email)
    else:
        print("prepare: --directory (the directory-group export, HER-16) is required outside DEV/TEST", file=sys.stderr)
        return 2
    _write(out / "directory.yaml", yaml.safe_dump(directory, sort_keys=True).encode())
    profile = ROOT / "integrations" / "hermes" / "profiles" / a.profile / "config.yaml"
    if env in DEV_ENVS:
        _write(out / "hermes-config.yaml", render_dev_profile(profile, a.model).encode())
        print(f"prepare: DEV/TEST profile {a.profile} (model {a.model}, D0) -> {out / 'hermes-config.yaml'}")
    elif (out / "hermes-config.yaml").exists():
        (out / "hermes-config.yaml").unlink()  # VALIDATION/PRODUCTION mount the committed profile
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
