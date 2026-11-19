"""Card 10K-9 (D-1362): the drill of RUNBOOK §12, "certificate renewal" (``docs/runbook/12-certificate-renewal.md``).

Steps 1 to 3 of the hospital-certificate procedure are run as the page writes them, through the same command
(``python -m console.cli check-tls``): a certificate that ends in 20 days gives the 30-day warning; the new
certificate and key are put in the files ``TB_TLS_CERT_FILE`` and ``TB_TLS_KEY_FILE`` name; the check then passes
with no warning, and each mistake the page says step 3 catches (a key that is not the certificate's, a wrong name, a
date not valid today) fails it. Steps 4 and 5 (Caddy recreated, the browser, the old key deleted) need the running
box and are not rehearsed here; the page says so.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from console import cli
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

HOST = "trialbox.hosp.test"


def certificate(crt: Path, key: Path, names: list[str], days: int, start: int = -1) -> None:
    """A self-signed certificate (synthetic, made here) for ``names``, ending in ``days`` days, and its key (0600)."""
    k = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(k.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + timedelta(days=start))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False)
        .sign(k, hashes.SHA256())
    )
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))  # fmt: skip
    os.chmod(key, 0o600)


def check_tls(capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """The page's command, ``python -m console.cli check-tls``: its exit code, what it printed and what it failed."""
    capsys.readouterr()
    rc = cli.main(["check-tls"])
    got = capsys.readouterr()
    return rc, got.out, got.err


def test_runbook_12_certificate_renewal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tls = tmp_path / "tls"
    tls.mkdir()
    crt, key = tls / "console.crt", tls / "console.key"
    for k in ("TB_TLS_MODE", "TB_TLS_HOSTNAME", "TB_TLS_CERT_FILE", "TB_TLS_KEY_FILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TB_TLS_MODE", "hospital")
    monkeypatch.setenv("TB_TLS_HOSTNAME", HOST)
    monkeypatch.setenv("TB_TLS_CERT_FILE", str(crt))
    monkeypatch.setenv("TB_TLS_KEY_FILE", str(key))

    # the box today: the hospital's certificate ends in 20 days
    certificate(crt, key, [HOST], days=20)
    ends = (datetime.now(UTC) + timedelta(days=20)).strftime("%Y-%m-%d")

    # step 1: check-tls warns 30 days before the end (a warning: the certificate still serves, exit 0)
    rc, out, err = check_tls(capsys)
    assert rc == 0 and not err
    assert f"note: the certificate ends on {ends}: ask hospital IT for the next one" in out
    # ... and only then: a certificate with 31 days left gives no warning
    certificate(tmp_path / "far.crt", tmp_path / "far.key", [HOST], days=31)
    monkeypatch.setenv("TB_TLS_CERT_FILE", str(tmp_path / "far.crt"))
    monkeypatch.setenv("TB_TLS_KEY_FILE", str(tmp_path / "far.key"))
    rc, out, _ = check_tls(capsys)
    assert rc == 0 and "ends on" not in out
    monkeypatch.setenv("TB_TLS_CERT_FILE", str(crt))
    monkeypatch.setenv("TB_TLS_KEY_FILE", str(key))

    # step 2: the old files are kept until step 4 passes; the new certificate (same name) and key go into the files
    # TB_TLS_CERT_FILE and TB_TLS_KEY_FILE name, the key 0600
    shutil.copy2(crt, tls / "console.crt.old")
    shutil.copy2(key, tls / "console.key.old")
    new = tmp_path / "from-hospital-it"
    new.mkdir()
    certificate(new / "console.crt", new / "console.key", [HOST], days=397)
    shutil.copyfile(new / "console.crt", crt)
    shutil.copyfile(new / "console.key", key)
    os.chmod(key, 0o600)
    assert (key.stat().st_mode & 0o777) == 0o600

    # step 3: check-tls passes, with no warning left
    rc, out, err = check_tls(capsys)
    assert rc == 0 and not err and "ends on" not in out and f"host {HOST}" in out

    # step 3 fails on each mistake the page names
    # (a) a key that is not the certificate's: the old key put back beside the new certificate
    shutil.copyfile(tls / "console.key.old", key)
    rc, _, err = check_tls(capsys)
    assert rc == 1 and "FAIL: the key file does not belong to the certificate" in err
    shutil.copyfile(new / "console.key", key)
    # (b) a wrong name: hospital IT issued it for another host
    certificate(tmp_path / "wrong.crt", tmp_path / "wrong.key", ["other.hosp.test"], days=397)
    monkeypatch.setenv("TB_TLS_CERT_FILE", str(tmp_path / "wrong.crt"))
    monkeypatch.setenv("TB_TLS_KEY_FILE", str(tmp_path / "wrong.key"))
    rc, _, err = check_tls(capsys)
    assert rc == 1 and f"FAIL: the certificate does not name {HOST}" in err
    # (c) a date not valid today: a certificate that starts tomorrow
    certificate(tmp_path / "early.crt", tmp_path / "early.key", [HOST], days=397, start=1)
    monkeypatch.setenv("TB_TLS_CERT_FILE", str(tmp_path / "early.crt"))
    monkeypatch.setenv("TB_TLS_KEY_FILE", str(tmp_path / "early.key"))
    rc, _, err = check_tls(capsys)
    assert rc == 1 and "FAIL: the certificate is not valid now" in err

    # the files of the box hold the new pair, and check-tls passes on them again
    monkeypatch.setenv("TB_TLS_CERT_FILE", str(crt))
    monkeypatch.setenv("TB_TLS_KEY_FILE", str(key))
    assert check_tls(capsys)[0] == 0
