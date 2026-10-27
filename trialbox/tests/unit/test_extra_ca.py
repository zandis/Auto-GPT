"""A hospital TLS-inspection CA is trusted at run time next to the public CAs (stress test #21)."""

from __future__ import annotations

import ssl
from pathlib import Path

import certifi
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from tb_common.extra_ca import BUNDLE_NAME, install


def _ca_pem() -> str:
    import datetime as dt

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Hospital TLS Inspection CA")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_mounted_ca_is_added_to_the_public_bundle(tmp_path: Path) -> None:
    ca = tmp_path / "extra.pem"
    ca.write_text(_ca_pem())
    env: dict[str, str] = {"TB_EXTRA_CA_FILE": str(ca)}
    out = install(env, str(tmp_path))
    assert out == str(tmp_path / BUNDLE_NAME) and env["SSL_CERT_FILE"] == out == env["REQUESTS_CA_BUNDLE"]
    ctx = ssl.create_default_context(cafile=out)
    subjects = {str(rdn[0][1]) for c in ctx.get_ca_certs() for rdn in c["subject"] if rdn[0][0] == "commonName"}
    assert "Hospital TLS Inspection CA" in subjects
    public = ssl.create_default_context(cafile=certifi.where())
    assert len(ctx.get_ca_certs()) == len(public.get_ca_certs()) + 1  # public CAs stay trusted


def test_no_or_empty_ca_changes_nothing(tmp_path: Path) -> None:
    empty = tmp_path / "empty.pem"
    empty.write_text("")
    for env in ({"TB_EXTRA_CA_FILE": str(empty)}, {"TB_EXTRA_CA_FILE": str(tmp_path / "missing.pem")}):
        assert install(env, str(tmp_path)) is None and "SSL_CERT_FILE" not in env
