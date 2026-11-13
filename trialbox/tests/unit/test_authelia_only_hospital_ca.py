"""AUTHELIA-CA (D-722): Authelia trusts only the hospital's directory CA. Its one outbound connection is LDAPS to
the hospital's directory; the image carries 121 public roots, so a certificate under any public CA (or under an
intermediate that should no longer be trusted, CVE-2026-111943) would be accepted for the directory's name. The
identity overlay now makes the hospital's own CA file the whole root list of the container; doctor refuses a box
whose hospital sign-in is on without it, and the release's own step stops such a box before it starts."""

from __future__ import annotations

import datetime as dt
import ssl
import subprocess
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


def _mount() -> dict[str, Any]:
    got: dict[str, Any] = next(v for v in _authelia()["volumes"] if isinstance(v, dict) and v.get("target") == INSIDE)
    return got


def _ca(name: str) -> str:
    """A self-signed CA certificate made here (synthetic: a hospital that does not exist), PEM."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    who = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    start = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(who)
        .issuer_name(who)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _pem(folder: Path, name: str = "hospital-ca.pem", certs: int = 1) -> Path:
    path = folder / name
    path.write_text("".join(_ca(f"Synthetic Hospital Directory CA {n}") for n in range(certs)), encoding="utf-8")
    return path


def _public_roots() -> list[str]:
    """The public roots this machine trusts, PEM, one each: what a host's bundle holds."""
    ders = ssl.create_default_context().get_ca_certs(binary_form=True)
    if not ders:
        pytest.skip("this machine has no public root list")
    return [ssl.DER_cert_to_PEM_cert(d) for d in ders]


# ------------------------------------------------------------------------------------------------- the overlay
def test_the_containers_whole_root_list_is_the_hospitals_file() -> None:
    svc = _authelia()
    env = svc["environment"]
    assert env["SSL_CERT_FILE"] == INSIDE  # Go's crypto/x509 reads this file INSTEAD of the image's bundle
    assert env["SSL_CERT_DIR"].startswith("/run/") and env["SSL_CERT_DIR"] != "/run"  # and no directory of roots
    mounts = [str(v) for v in svc["volumes"]]
    assert _mount() == {
        "type": "bind",
        "source": "${TB_LDAP_CA:-/dev/null}",
        "target": INSIDE,
        "read_only": True,
        "bind": {"create_host_path": False},
    }
    assert not [m for m in mounts if env["SSL_CERT_DIR"] in m]  # nothing is ever mounted where it looks for more
    assert not [m for m in mounts if "/etc/ssl" in m or "ca-certificates" in m]


def test_a_file_that_is_not_there_is_never_made_as_a_folder_on_the_host() -> None:
    """Found by the review: with the short form docker makes a root-owned DIRECTORY where the missing file should
    be; the container's root file is then a folder, and the operator's copy lands inside it."""
    assert _mount()["bind"] == {"create_host_path": False}


def test_unset_the_root_file_is_empty() -> None:
    """Unset, the source is /dev/null: an empty root file (what the binary does with an empty list is said in
    D-722; the release's step below does not let a PRODUCTION box start that way)."""
    assert network_sheet.interpolate(_mount()["source"], {}) == "/dev/null"
    assert network_sheet.interpolate(_mount()["source"], {"TB_LDAP_CA": "/srv/ca.pem"}) == "/srv/ca.pem"


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
    assert "before the update" in runbook  # a box that already runs the hospital sign-in
    assert "TB_LDAP_CA" in (ROOT / "deploy/identity/identity.env.example").read_text(encoding="utf-8")


# -------------------------------------------------------------------------------------------------------- doctor
def _check(**env: str) -> doctor.Check:
    return doctor.check_ldap_ca(doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", **env}))


def test_doctor_has_nothing_to_say_when_the_hospital_sign_in_is_off() -> None:
    c = _check()
    assert (c.name, c.status) == ("ldap_ca", "PASS")


def test_doctor_passes_a_file_of_the_hospitals_own_certificates(tmp_path: Path) -> None:
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(_pem(tmp_path, certs=2)))
    assert c.status == "PASS" and "2 certificate" in c.detail


@pytest.mark.parametrize(("env", "status"), [("PRODUCTION", "FAIL"), ("VALIDATION", "FAIL"), ("TEST", "WARN")])
def test_doctor_fails_a_box_whose_hospital_sign_in_is_on_without_the_file(env: str, status: str) -> None:
    c = doctor.check_ldap_ca(doctor.DoctorInputs(env={"TB_ENV": env, "TB_OIDC_ENABLED": "1"}))
    assert c.status == status and "TB_LDAP_CA" in c.detail


def test_doctor_fails_a_file_that_is_missing_or_holds_no_certificate(tmp_path: Path) -> None:
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(tmp_path / "gone.pem"))
    assert c.status == "FAIL" and "gone.pem" in c.detail
    for junk in (
        "-----BEGIN CERTIFICATE-----\nnot base64 at all !!!\n-----END CERTIFICATE-----\n",
        "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n",  # well-formed base64, no certificate
        "",
    ):
        empty = tmp_path / "empty.pem"
        empty.write_text(junk, encoding="utf-8")
        c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(empty))
        assert c.status == "FAIL" and "no certificate" in c.detail, junk
    (tmp_path / "a-folder").mkdir()
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(tmp_path / "a-folder"))
    assert c.status == "FAIL" and "cannot be read" in c.detail


def test_doctor_fails_a_file_with_a_private_key_and_never_shows_it(tmp_path: Path) -> None:
    secret = "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgSYNTHETICKEY"
    both = tmp_path / "ca-and-key.pem"
    key = f"-----BEGIN PRIVATE KEY-----\n{secret}\n-----END PRIVATE KEY-----\n"
    both.write_text(_ca("Synthetic CA") + key, encoding="utf-8")
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(both))
    assert c.status == "FAIL" and "private key" in c.detail and secret not in c.detail


def test_doctor_refuses_public_roots_whatever_the_file_is_called(tmp_path: Path) -> None:
    """Found by the review, by running: a copy of the host's bundle under another name, or a link to it, passed
    ("122 certificates ... no public root is trusted"). The check reads what is IN the file: a certificate that is
    also one of the public roots this machine trusts is never a hospital's own CA."""
    roots = _public_roots()
    copy = tmp_path / "hospital-ca.pem"
    copy.write_text("".join(roots), encoding="utf-8")
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(copy))
    assert c.status == "FAIL" and "public root" in c.detail
    link = tmp_path / "link.pem"
    link.symlink_to(copy)
    assert _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(link)).status == "FAIL"
    mixed = tmp_path / "mixed.pem"
    mixed.write_text(_ca("Synthetic Hospital CA") + roots[0], encoding="utf-8")
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(mixed))
    assert c.status == "FAIL" and "1 of its 2" in c.detail  # one public root among the hospital's own is one too many


def test_the_hospitals_own_ca_passes_wherever_the_host_keeps_it(tmp_path: Path) -> None:
    """The first shape refused paths: /usr/local/share/ca-certificates/hospital-ca.crt, the usual place for a
    local CA, was called "the host's public root list". The place does not matter; the content does."""
    place = tmp_path / "usr" / "local" / "share" / "ca-certificates"
    place.mkdir(parents=True)
    c = _check(TB_OIDC_ENABLED="1", TB_LDAP_CA=str(_pem(place, "hospital-ca.crt")))
    assert c.status == "PASS", c.detail


def test_a_windows_line_end_and_a_path_relative_to_deploy(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "secrets" / "tls").mkdir(parents=True)
    (deploy / "secrets" / "tls" / "ca.pem").write_bytes(_ca("Synthetic CA").replace("\n", "\r\n").encode())
    env = {"TB_ENV": "PRODUCTION", "TB_OIDC_ENABLED": "1", "TB_LDAP_CA": "./secrets/tls/ca.pem"}
    c = doctor.check_ldap_ca(doctor.DoctorInputs(env=env, deploy=deploy))
    assert c.status == "PASS", c.detail
    env["TB_LDAP_CA"] = "secrets/tls/ca.pem"  # compose reads a name without ./ or / as a named volume, not a file
    c = doctor.check_ldap_ca(doctor.DoctorInputs(env=env, deploy=deploy))
    assert c.status == "FAIL" and "./" in c.detail


def test_doctor_runs_the_check() -> None:
    assert doctor.check_ldap_ca in doctor.CHECKS


def _host_mount(tmp_path: Path, line: str) -> list[str]:
    """The lines of check_host.sh that find the file, run as they stand; the docker arguments they give."""
    host = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    start = host.index("  # D-722: doctor's ldap_ca check")
    block = host[start : host.index("\n  # OPS-004 (D-570)", start)]
    env_file = tmp_path / ".env"
    env_file.write_text(line + "\n", encoding="utf-8")
    show = 'set -- ${LDAP_MOUNT:+-v "$LDAP_MOUNT"}; [ $# -eq 0 ] || printf "%s\\n" "$@"'
    script = f'set -eu\nENV_FILE="{env_file}"\n{block}\n{show}\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    return r.stdout.splitlines()


def test_the_host_check_hands_the_doctor_the_file_whole(tmp_path: Path) -> None:
    """Found by the review: a quoted value was not mounted (a false FAIL), and a path with a space broke the
    doctor's whole run (the second half was read as the image's name)."""
    ca = _pem(tmp_path, "hospital directory ca.pem")
    assert _host_mount(tmp_path, f"TB_LDAP_CA={ca}") == ["-v", f"{ca}:{ca}:ro"]
    assert _host_mount(tmp_path, f'TB_LDAP_CA="{ca}"  ') == ["-v", f"{ca}:{ca}:ro"]
    assert _host_mount(tmp_path, "TB_LDAP_CA=./secrets/tls/ca.pem") == []  # inside the mount of deploy/ already
    assert _host_mount(tmp_path, f"TB_LDAP_CA={tmp_path / 'gone.pem'}") == []
    host = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    run = host[host.index('${KEK_MOUNT:+-v "$KEK_MOUNT"}') - 200 :]
    assert '${LDAP_MOUNT:+-v "$LDAP_MOUNT"}' in run[:600]  # on the doctor's own docker run line


# -------------------------------------------------------------------------------- before a start, and an update
def _prestart(tmp_path: Path, env_lines: str) -> str:
    from tools.trialbox import prestart
    from tools.trialbox.update import ComposeBox

    deploy = tmp_path / "deploy"
    deploy.mkdir(exist_ok=True)
    (deploy / ".env").write_text(env_lines, encoding="utf-8")
    step = dict(prestart.STEPS)["hospital directory CA"]
    return step(ComposeBox(deploy))


def test_a_box_whose_hospital_sign_in_is_on_is_not_started_without_the_file(tmp_path: Path) -> None:
    """Found by the review: a site that already runs the hospital sign-in and takes this release got an Authelia
    that trusts nothing, with no word before. The new release's own step, run before any service starts (by the
    update and by install.sh), stops with the reason; the update puts the box back."""
    from tools.trialbox.update import UpdateFailed

    with pytest.raises(UpdateFailed) as stop:
        _prestart(tmp_path, "TB_ENV=PRODUCTION\nTB_OIDC_ENABLED=1\n")
    assert "TB_LDAP_CA" in str(stop.value) and "nothing was started" in str(stop.value)


def test_the_step_lets_every_other_box_through(tmp_path: Path) -> None:
    assert "off" in _prestart(tmp_path, "TB_ENV=PRODUCTION\n")
    ca = _pem(tmp_path)
    assert "1 certificate" in _prestart(tmp_path, f"TB_ENV=PRODUCTION\nTB_OIDC_ENABLED=1\nTB_LDAP_CA={ca}\n")
    assert "TB_LDAP_CA" in _prestart(tmp_path, "TB_ENV=TEST\nTB_OIDC_ENABLED=1\n")  # a TEST box is told, not stopped


def test_the_step_is_one_of_those_run_before_any_service_starts() -> None:
    """``pre-start`` is what the update and install.sh run before the services are put on the release; the step is
    the last of them (the steps before it make keys, which are harmless to a box that is then put back)."""
    from tools.trialbox import prestart

    assert prestart.STEPS[-1][0] == "hospital directory CA"
    assert dict(prestart.PHASES["pre-start"])["hospital directory CA"] is prestart._ldap_ca
