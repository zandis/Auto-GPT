"""AUTHELIA-CA (D-722): Authelia trusts only the hospital's directory CA. Its one outbound connection is LDAPS to
the hospital's directory; the image carries 121 public roots, so a certificate under any public CA (or under an
intermediate that should no longer be trusted, CVE-2026-111943) would be accepted for the directory's name. The
identity overlay now makes the hospital's own CA file the whole root list of the container; doctor refuses a box
whose hospital sign-in is on without it."""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

import pytest

from tools import network_sheet
from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
FILES = ["deploy/docker-compose.yml", "deploy/docker-compose.secrets.yml", "deploy/docker-compose.identity.yml"]
INSIDE = "/run/tb-ldap-ca.pem"

pytestmark = pytest.mark.nodb


def _authelia() -> dict[str, Any]:
    got: dict[str, Any] = network_sheet.load(FILES)["services"]["authelia"]
    return got


def _pem(tmp_path: Path, name: str = "hospital-ca.pem", certs: int = 1) -> Path:
    """A file of well-formed certificate blocks (the bytes are not a real certificate: the check reads the form)."""
    block = ssl.DER_cert_to_PEM_cert(b"synthetic-not-a-real-certificate" * 8)
    path = tmp_path / name
    path.write_text(block * certs, encoding="utf-8")
    return path


# ------------------------------------------------------------------------------------------------- the overlay
def test_the_containers_whole_root_list_is_the_hospitals_file() -> None:
    svc = _authelia()
    env = svc["environment"]
    assert env["SSL_CERT_FILE"] == INSIDE  # Go's crypto/x509 reads this file INSTEAD of the image's bundle
    assert env["SSL_CERT_DIR"].startswith("/run/") and env["SSL_CERT_DIR"] != "/run"  # and no directory of roots
    mounts = [str(v) for v in svc["volumes"]]
    assert "${TB_LDAP_CA:-/dev/null}:" + INSIDE + ":ro" in mounts
    assert not [m for m in mounts if env["SSL_CERT_DIR"] in m]  # nothing is ever mounted where it looks for more
    assert not [m for m in mounts if "/etc/ssl" in m or "ca-certificates" in m]


def test_without_the_file_the_container_trusts_nothing() -> None:
    """Unset, the mount is /dev/null: an empty root list, so every LDAPS handshake fails. Closed, never the image's
    public roots."""
    mount = next(str(v) for v in _authelia()["volumes"] if INSIDE in str(v))
    assert mount.startswith("${TB_LDAP_CA:-/dev/null}:")


def test_no_other_service_gets_the_root_list_changed() -> None:
    for name, svc in network_sheet.load(FILES)["services"].items():
        env = svc.get("environment") or {}
        if name != "authelia" and isinstance(env, dict):
            assert "SSL_CERT_FILE" not in env and "SSL_CERT_DIR" not in env, name


def test_the_example_configuration_and_the_runbook_say_where_the_ca_goes() -> None:
    example = (ROOT / "deploy/identity/authelia/configuration.example.yml").read_text(encoding="utf-8")
    assert "TB_LDAP_CA" in example and "skip_verify: false" in example
    runbook = (ROOT / "docs/runbook/12-identity-and-tls.md").read_text(encoding="utf-8")
    assert "TB_LDAP_CA" in runbook and "no public" in runbook
    assert "TB_LDAP_CA" in (ROOT / "deploy/identity/identity.env.example").read_text(encoding="utf-8")


# -------------------------------------------------------------------------------------------------------- doctor
def _check(**env: str) -> doctor.Check:
    return doctor.check_ldap_ca(doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", **env}))


def test_doctor_has_nothing_to_say_when_the_hospital_sign_in_is_off(tmp_path: Path) -> None:
    c = _check()
    assert (c.name, c.status) == ("ldap_ca", "PASS")


def test_doctor_passes_a_file_of_the_hospitals_own_certificates(tmp_path: Path) -> None:
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(_pem(tmp_path, certs=2)))
    assert c.status == "PASS" and "2 certificate" in c.detail


@pytest.mark.parametrize(("env", "status"), [("PRODUCTION", "FAIL"), ("VALIDATION", "FAIL"), ("TEST", "WARN")])
def test_doctor_fails_a_box_whose_hospital_sign_in_is_on_without_the_file(env: str, status: str) -> None:
    c = doctor.check_ldap_ca(doctor.DoctorInputs(env={"TB_ENV": env, "TB_OIDC_ENABLED": "1"}))
    assert c.status == status and "TB_LDAP_CA" in c.detail and "trusts nothing" in c.detail


def test_doctor_fails_a_file_that_is_missing_or_holds_no_certificate(tmp_path: Path) -> None:
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(tmp_path / "gone.pem"))
    assert c.status == "FAIL" and "gone.pem" in c.detail
    empty = tmp_path / "empty.pem"
    empty.write_text(
        "-----BEGIN CERTIFICATE-----\nnot base64 at all !!!\n-----END CERTIFICATE-----\n", encoding="utf-8"
    )
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(empty))
    assert c.status == "FAIL" and "no certificate" in c.detail
    key = tmp_path / "key.pem"
    key.write_text("-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n", encoding="utf-8")
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(key))
    assert c.status == "FAIL" and "private key" in c.detail  # and never its content


@pytest.mark.parametrize("bundle", ["/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
                                    "/etc/ssl/cert.pem", "/etc/ssl/certs"])  # fmt: skip
def test_doctor_refuses_the_hosts_public_root_list_as_the_hospitals_ca(bundle: str) -> None:
    """The one way to undo the card with a setting: point it at the public roots."""
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=bundle)
    assert c.status == "FAIL" and "public root" in c.detail


def test_doctor_runs_the_check_and_the_host_check_hands_it_the_file() -> None:
    assert doctor.check_ldap_ca in doctor.CHECKS
    host = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    assert "TB_LDAP_CA" in host  # the doctor runs in the box's image: the file is mounted where the setting names it
