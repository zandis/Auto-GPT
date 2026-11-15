"""D-837: a VALIDATION box on a plain VM. install.sh takes the environment as an answer, and one declared setting,
TB_HOST_PROFILE=poc, makes the host-facility checks (TPM seal, LUKS, egress table, systemd units, firewall, SSH,
cron) WARN and listed in install.sh, check_host.sh and doctor. Never on PRODUCTION.

Before: a pre-written TB_ENV=VALIDATION was overwritten by the wizard and the box silently became PRODUCTION, and
no setting let a plain VM end the host check with exit 0 (LUKS, plain keys, the anchor folder, egress each FAILed).
TB_BOX_DEFER_SEAL and TB_SYSTEMD=0 existed undeclared; they are declared now and the profile sets their defaults."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tools.trialbox import doctor as d

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")

pytestmark = pytest.mark.nodb


def _block(marker: str) -> str:
    start = INSTALL.index(f"# {marker} (D-837)")
    return INSTALL[start : INSTALL.index(f"# ---- end of {marker}", start)]


def _install(tmp: Path, block: str, env_lines: str, pre: str = "", **shell: str) -> subprocess.CompletedProcess[str]:
    (tmp / "deploy").mkdir(exist_ok=True)
    (tmp / "deploy" / ".env").write_text(env_lines, encoding="utf-8")
    sets = "".join(f"{k}={v}\n" for k, v in shell.items())
    script = (
        "set -euo pipefail\n"
        'die() { echo "install: $*" >&2; exit 1; }\n'
        'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n'
        'envset() { sed -i "/^$1=/d" deploy/.env && printf "%s=%s\\n" "$1" "$2" >> deploy/.env; }\n'
        f'cd "{tmp}"\nREHEARSAL=0\nENVIRONMENT=""\nPRE_ENV=""\n{sets}{pre}'
        + _block(block)
        + '\necho "TB_SYSTEMD=${TB_SYSTEMD:-1}"\n'
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    return subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, env=env, check=False)


def _env_of(tmp: Path) -> dict[str, str]:
    out = {}
    for line in (tmp / "deploy" / ".env").read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        out[k] = v
    return out


# ------------------------------------------------------------------------------------------------ the environment
def test_the_environment_answer_makes_a_validation_box(tmp_path: Path) -> None:
    res = _install(tmp_path, "ENVIRONMENT", "TB_TOPOLOGY=A\n", ENVIRONMENT="VALIDATION")
    assert res.returncode == 0, res.stderr
    assert _env_of(tmp_path)["TB_ENV"] == "VALIDATION"


def test_a_pre_written_environment_survives_the_wizard(tmp_path: Path) -> None:
    """The wizard rewrote deploy/.env without it: the D-127 default then made the box PRODUCTION."""
    res = _install(tmp_path, "ENVIRONMENT", "TB_TOPOLOGY=A\n", PRE_ENV="VALIDATION")
    assert res.returncode == 0, res.stderr
    assert _env_of(tmp_path)["TB_ENV"] == "VALIDATION"


def test_a_conflicting_environment_is_refused(tmp_path: Path) -> None:
    res = _install(tmp_path, "ENVIRONMENT", "TB_ENV=PRODUCTION\n", ENVIRONMENT="VALIDATION")
    assert res.returncode == 1 and "PRODUCTION" in res.stderr and "VALIDATION" in res.stderr
    bad = _install(tmp_path, "ENVIRONMENT", "\n", ENVIRONMENT="STAGING")
    assert bad.returncode == 1 and "--environment" in bad.stderr
    rehearsal = _install(tmp_path, "ENVIRONMENT", "\n", ENVIRONMENT="VALIDATION", REHEARSAL="1")
    assert rehearsal.returncode == 1 and "TEST" in rehearsal.stderr


def test_install_takes_the_environment_option() -> None:
    assert '--environment) ENVIRONMENT="$2"' in INSTALL
    assert INSTALL.index("# ENVIRONMENT (D-837)") < INSTALL.index(
        "grep -q '^TB_ENV=' deploy/.env || echo \"TB_ENV=PRODUCTION\""
    )
    assert INSTALL.index('PRE_ENV="') < INSTALL.index("python -m tools.settings_wizard --answers")


# ------------------------------------------------------------------------------------------------ the host profile
def test_the_poc_profile_is_never_production(tmp_path: Path) -> None:
    res = _install(tmp_path, "HOST PROFILE", "TB_ENV=PRODUCTION\n", TB_ENV_SITE="PRODUCTION", TB_HOST_PROFILE="poc")
    assert res.returncode == 1 and "never" in res.stderr and "PRODUCTION" in res.stderr


def test_the_poc_profile_is_kept_and_skips_the_systemd_units(tmp_path: Path) -> None:
    res = _install(tmp_path, "HOST PROFILE", "TB_ENV=VALIDATION\n", TB_ENV_SITE="VALIDATION", TB_HOST_PROFILE="poc")
    assert res.returncode == 0, res.stderr
    assert _env_of(tmp_path)["TB_HOST_PROFILE"] == "poc"
    assert "TB_SYSTEMD=0" in res.stdout and "WARN" in res.stdout


def test_an_unknown_profile_is_refused(tmp_path: Path) -> None:
    res = _install(tmp_path, "HOST PROFILE", "TB_ENV=VALIDATION\n", TB_ENV_SITE="VALIDATION", TB_HOST_PROFILE="lab")
    assert res.returncode == 1 and "TB_HOST_PROFILE" in res.stderr


def test_the_settings_are_declared() -> None:
    from tb_common.config import DECLARED

    for name in ("TB_HOST_PROFILE", "TB_BOX_DEFER_SEAL", "TB_SYSTEMD"):
        assert name in DECLARED and DECLARED[name].doc, name


# ------------------------------------------------------------------------------------------------ check_host.sh
def _baseline(tmp: Path, env_name: str, profile: str) -> subprocess.CompletedProcess[str]:
    from tests.unit import test_host_baseline as hb

    args, env = hb._box(tmp, plain=True, crypt=False, env_name=env_name)
    envf = Path(args[args.index("--env") + 1])
    envf.write_text(envf.read_text(encoding="utf-8") + f"TB_HOST_PROFILE={profile}\n", encoding="utf-8")
    return hb._sh(args, env)


def test_check_host_warns_and_lists_the_host_facilities_under_poc(tmp_path: Path) -> None:
    r = _baseline(tmp_path, "VALIDATION", "poc")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout.replace("FAIL in VALIDATION", "")
    assert "WARN  site_hmac.key is a plain file" in r.stdout and "[host profile poc]" in r.stdout
    assert "LUKS" in r.stdout.split("host profile poc:")[-1]  # the closing list names each one


def test_check_host_still_fails_them_without_the_profile(tmp_path: Path) -> None:
    r = _baseline(tmp_path, "VALIDATION", "site")
    assert r.returncode == 1 and "FAIL  site_hmac.key is a plain file" in r.stdout


def test_check_host_fails_poc_on_production(tmp_path: Path) -> None:
    r = _baseline(tmp_path, "PRODUCTION", "poc")
    assert r.returncode == 1 and "TB_HOST_PROFILE=poc" in r.stdout


# ------------------------------------------------------------------------------------------------ doctor
def _fake(name: str, status: str):  # type: ignore[no-untyped-def]
    def check(_inp: d.DoctorInputs) -> d.Check:
        return d.Check(name, status, f"{name} said {status}")  # type: ignore[arg-type]

    check.__name__ = f"check_{name}"
    return check


def test_doctor_turns_host_facility_fails_into_listed_warnings_under_poc() -> None:
    checks = (_fake("key_custody", "FAIL"), _fake("anchor_mount", "FAIL"), _fake("registry_pins", "FAIL"))
    out = d.run(d.DoctorInputs(env={"TB_ENV": "VALIDATION", "TB_HOST_PROFILE": "poc"}), checks)
    by = {c.name: c for c in out}
    assert by["key_custody"].status == "WARN" and "host profile poc" in by["key_custody"].detail
    assert by["anchor_mount"].status == "WARN"
    assert by["registry_pins"].status == "FAIL"  # not a host facility: the pair is still to be qualified
    assert by["host_profile"].status == "WARN" and "key_custody" in by["host_profile"].detail


def test_doctor_fails_poc_on_production_and_keeps_its_fails() -> None:
    out = d.run(d.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_HOST_PROFILE": "poc"}), (_fake("key_custody", "FAIL"),))
    by = {c.name: c for c in out}
    assert by["key_custody"].status == "FAIL" and by["host_profile"].status == "FAIL"


def test_doctor_without_the_profile_is_unchanged() -> None:
    out = d.run(d.DoctorInputs(env={"TB_ENV": "VALIDATION"}), (_fake("key_custody", "FAIL"),))
    assert [(c.name, c.status) for c in out] == [("key_custody", "FAIL")]
