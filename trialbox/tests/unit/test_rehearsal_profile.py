"""REHEARSAL (D-726): a rehearsal box says so. The owner's five conditions (2026-11-13): one explicit installer
argument; the box is TEST before anything loads, refused on a PRODUCTION or VALIDATION box or a box with site data;
the model stand-ins and an unmeasured card honoured only on TEST; doctor says "rehearsal box"; a rehearsal bundle is
marked and a PRODUCTION box refuses it."""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_release_bundle import HAPI, OWN, VLLM, _gate_record, _make, kit  # noqa: F401
from tests.unit.test_release_dirty_refused import EnvBox, _release, _upd, _with
from tools.trialbox import doctor
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
BOX_INSTALL = (ROOT / "deploy" / "box-install.sh").read_text(encoding="utf-8")
STANDINS = "tools/rehearse_box/standins.yml"

pytestmark = pytest.mark.nodb


def _block(marker: str) -> str:
    start = INSTALL.index(marker)
    return INSTALL[start : INSTALL.index("\n# ---- end of " + marker.removeprefix("# "), start)]


def _sh(
    tmp: Path, body: str, *, volumes: str = "", env_lines: str | None = None, docker_rc: int = 0, rehearsal: int = 1
) -> subprocess.CompletedProcess[str]:
    """The installer's lines as they stand, in a folder laid out as an installer's, with a stand-in for docker."""
    (tmp / "deploy" / "site").mkdir(parents=True, exist_ok=True)
    (tmp / "tools" / "rehearse_box").mkdir(parents=True, exist_ok=True)
    (tmp / STANDINS).write_text("services: {}\n", encoding="utf-8")
    if env_lines is not None:
        (tmp / "deploy" / ".env").write_text(env_lines, encoding="utf-8")
    script = (
        "set -euo pipefail\n"
        f'ROOT="{tmp}"\ncd "$ROOT"\nREHEARSAL={rehearsal}\n'
        'die() { echo "install: $*" >&2; exit 1; }\n'
        'envget() { sed -n "s/^$1=//p" deploy/.env | tail -1; }\n'
        'envset() { sed -i "/^$1=/d" deploy/.env && printf \'%s=%s\\n\' "$1" "$2" >> deploy/.env; }\n'
        f'docker() {{ printf "%s" "{volumes}"; return {docker_rc}; }}\n'
        f"{body}\n"
        'printf "override=%s\\nunmeasured=%s\\n" "${TB_COMPOSE_OVERRIDE:-}" "${TB_ACCEPT_UNMEASURED_GPU:-}"\n'
    )
    env = {k: v for k, v in os.environ.items() if k not in ("TB_COMPOSE_OVERRIDE", "TB_ACCEPT_UNMEASURED_GPU")}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False, env=env)


EARLY = "# REHEARSAL (D-726): before anything loads"
SETTINGS = "# REHEARSAL (D-726): the box says TEST"


# ------------------------------------------------------------------------------- 1. one explicit argument
def test_the_installer_and_the_box_installer_take_the_one_argument() -> None:
    assert "    --rehearsal) REHEARSAL=1 ;;" in INSTALL
    assert "    --rehearsal) REHEARSAL=1 ;;" in BOX_INSTALL
    assert '[ "$REHEARSAL" = 1 ] && INSTALL_ARGS+=(--rehearsal)' in BOX_INSTALL  # handed on to install.sh
    assert INSTALL.index(EARLY) < INSTALL.index('say "bundle: verify and load')


# --------------------------------------------- 2. TEST before anything loads; refused on a site box or site data
@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION"])
def test_a_box_that_is_already_a_site_box_is_refused(tmp_path: Path, env: str) -> None:
    r = _sh(tmp_path, _block(EARLY), env_lines=f"TB_ENV={env}\n")
    assert r.returncode == 1 and env in r.stderr and "rehearsal" in r.stderr
    assert not (tmp_path / "deploy" / "site" / "rehearsal.json").exists()


def test_a_box_that_holds_data_and_was_not_a_rehearsal_is_refused(tmp_path: Path) -> None:
    r = _sh(tmp_path, _block(EARLY), volumes="trialbox_db-data\n")
    assert r.returncode == 1 and "data" in r.stderr and "trialbox_db-data" in r.stderr


def test_a_rehearsal_box_run_again_goes_on(tmp_path: Path) -> None:
    """The installer goes on from the step that stopped: the second run finds the rehearsal's own volumes."""
    (tmp_path / "deploy" / "site").mkdir(parents=True)
    (tmp_path / "deploy" / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    r = _sh(tmp_path, _block(EARLY), volumes="trialbox_db-data\n")
    assert r.returncode == 0, r.stderr


def test_a_fresh_rehearsal_is_marked_and_takes_the_stand_ins_and_the_unmeasured_card(tmp_path: Path) -> None:
    r = _sh(tmp_path, _block(EARLY))
    assert r.returncode == 0, r.stderr
    mark = json.loads((tmp_path / "deploy" / "site" / "rehearsal.json").read_text(encoding="utf-8"))
    assert mark["rehearsal"] is True
    assert f"override={tmp_path / STANDINS}" in r.stdout and "unmeasured=1" in r.stdout


def test_an_empty_override_is_a_card_s_trial_boot_with_its_real_model_servers(tmp_path: Path) -> None:
    """An unmeasured card is measured on its real model servers: TB_COMPOSE_OVERRIDE set empty keeps the stand-ins
    out; the box is a rehearsal box all the same."""
    r = _sh(tmp_path, f"export TB_COMPOSE_OVERRIDE=\n{_block(EARLY)}")
    assert r.returncode == 0, r.stderr
    assert "override=\n" in r.stdout and "unmeasured=1" in r.stdout
    assert (tmp_path / "deploy" / "site" / "rehearsal.json").is_file()


def test_the_trial_boot_is_written_as_a_rehearsal_wherever_it_is_told() -> None:
    """The runbook's trial boot and the tier refusal's advice name the argument: without it the box is PRODUCTION
    and the installer refuses the unmeasured card."""
    from tools import tiers

    runbook = (ROOT / "docs" / "runbook" / "01-install-a-new-site.md").read_text(encoding="utf-8")
    assert "TB_COMPOSE_OVERRIDE= TB_ACCEPT_UNMEASURED_GPU=1 deploy/install.sh <bundle> --gpu <profile> --rehearsal" in (
        " ".join(runbook.split())
    )
    assert "--rehearsal" in (ROOT / "tools" / "tiers.py").read_text(encoding="utf-8")
    assert tiers is not None


def test_the_box_is_test_before_the_bundle_is_loaded(tmp_path: Path) -> None:
    """The bundle is loaded (and its release record judged) before the settings are written: the box's environment
    is read then from the mark, not from a deploy/.env that does not exist yet."""
    (tmp_path / "deploy" / "site").mkdir(parents=True)
    box = up.ComposeBox(tmp_path / "deploy")
    assert box.environment() == "PRODUCTION"  # no file, no mark: the strict side (D-127)
    (tmp_path / "deploy" / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    assert box.environment() == "TEST"
    (tmp_path / "deploy" / ".env").write_text("TB_ENV=PRODUCTION\n", encoding="utf-8")
    assert box.environment() == "PRODUCTION"  # what deploy/.env says wins: a mark never loosens a site box


@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION"])
def test_answers_that_make_a_site_box_are_refused_after_the_settings(tmp_path: Path, env: str) -> None:
    r = _sh(tmp_path, _block(SETTINGS), env_lines=f"TB_ENV={env}\n")
    assert r.returncode == 1 and env in r.stderr


def test_after_the_settings_the_box_says_test_and_rehearsal(tmp_path: Path) -> None:
    r = _sh(tmp_path, _block(SETTINGS), env_lines="TB_TZ=Asia/Taipei\n")
    assert r.returncode == 0, r.stderr
    lines = (tmp_path / "deploy" / ".env").read_text(encoding="utf-8").splitlines()
    assert "TB_ENV=TEST" in lines and "TB_REHEARSAL=1" in lines
    assert INSTALL.index(SETTINGS) < INSTALL.index("TB_ENV_SITE=\"$(sed -n 's/^TB_ENV=//p' deploy/.env | tail -1)\"")


# ------------------------------------------------------ 3. the stand-ins and an unmeasured card only on TEST
def _only_on_test(tmp: Path, env: str, what: str, marked: bool = True) -> subprocess.CompletedProcess[str]:
    start = INSTALL.index("rehearsal_only() {")
    fn = INSTALL[start : INSTALL.index("\n}\n", start) + 3]
    lines = f"TB_ENV={env}\n" + ("TB_REHEARSAL=1\n" if marked else "")
    return _sh(tmp, f'TB_ENV_SITE={env}\n{fn}\nrehearsal_only "{what}"\necho through', env_lines=lines)


def test_a_test_box_that_is_no_rehearsal_box_is_refused_too(tmp_path: Path) -> None:
    """A hospital's own TEST box (review F5): TEST alone is not a rehearsal box."""
    r = _only_on_test(tmp_path, "TEST", "the model stand-ins", marked=False)
    assert r.returncode == 1 and "--rehearsal" in r.stderr


@pytest.mark.parametrize(("env", "ok"), [("TEST", True), ("DEV", False), ("PRODUCTION", False), ("VALIDATION", False)])
def test_a_rehearsal_thing_is_refused_off_a_test_box(tmp_path: Path, env: str, ok: bool) -> None:
    r = _only_on_test(tmp_path, env, "TB_ACCEPT_UNMEASURED_GPU=1")
    assert (r.returncode == 0 and "through" in r.stdout) is ok, r.stderr
    if not ok:
        assert "TB_ACCEPT_UNMEASURED_GPU=1" in r.stderr and "TEST" in r.stderr and "--rehearsal" in r.stderr


def test_both_rehearsal_things_go_through_that_rule() -> None:
    assert 'rehearsal_only "TB_ACCEPT_UNMEASURED_GPU=1' in INSTALL
    assert 'rehearsal_only "the model stand-ins' in INSTALL
    assert INSTALL.index("rehearsal_only() {") < INSTALL.index('rehearsal_only "TB_ACCEPT_UNMEASURED_GPU=1')


# ----------------------------------------------------------------------------------- 4. doctor says so
def test_doctor_says_rehearsal_box_on_a_test_box() -> None:
    c = doctor.check_rehearsal(doctor.DoctorInputs(env={"TB_ENV": "TEST", "TB_REHEARSAL": "1"}))
    assert (c.name, c.status) == ("rehearsal", "WARN") and "rehearsal box" in c.detail


@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION", "DEV"])
def test_doctor_fails_a_rehearsal_mark_on_any_other_box(env: str) -> None:
    c = doctor.check_rehearsal(doctor.DoctorInputs(env={"TB_ENV": env, "TB_REHEARSAL": "1"}))
    assert c.status == "FAIL" and "rehearsal" in c.detail and env in c.detail


def test_doctor_finds_the_mark_file_too(tmp_path: Path) -> None:
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    c = doctor.check_rehearsal(doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION"}, deploy=tmp_path))
    assert c.status == "FAIL"


def test_doctor_has_nothing_to_say_on_a_box_that_is_no_rehearsal(tmp_path: Path) -> None:
    c = doctor.check_rehearsal(doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION"}, deploy=tmp_path))
    assert c.status == "PASS"
    assert doctor.check_rehearsal in doctor.CHECKS


# ------------------------------------------------------- 5. a rehearsal bundle is marked; a site box refuses it
def test_a_bundle_built_for_a_rehearsal_says_so(kit: dict[str, Any]) -> None:  # noqa: F811
    gates, sbom = _gate_record(kit["tmp"], [*OWN, HAPI, VLLM])
    res = _make(kit, "--release-seq", "4", "--gates", str(gates), "--sbom-dir", str(sbom), "--rehearsal")
    assert res.returncode == 0, res.stdout + res.stderr
    with tarfile.open(kit["tmp"] / "out.tar") as tf:
        rel = json.loads(tf.extractfile("release.json").read())  # type: ignore[union-attr]
    assert rel["rehearsal"] is True


def test_a_bundle_built_for_a_site_does_not(kit: dict[str, Any]) -> None:  # noqa: F811
    gates, sbom = _gate_record(kit["tmp"], [*OWN, HAPI, VLLM])
    res = _make(kit, "--release-seq", "4", "--gates", str(gates), "--sbom-dir", str(sbom))
    assert res.returncode == 0, res.stdout + res.stderr
    with tarfile.open(kit["tmp"] / "out.tar") as tf:
        rel = json.loads(tf.extractfile("release.json").read())  # type: ignore[union-attr]
    assert "rehearsal" not in rel


@pytest.mark.parametrize("env", ["PRODUCTION", "VALIDATION"])
def test_a_site_box_refuses_a_rehearsal_bundle_at_install_and_update(tmp_path: Path, env: str) -> None:
    box = EnvBox(env)
    rel = {**_release(False), "rehearsal": True}
    with pytest.raises(up.UpdateRefused) as exc:
        _upd(box, tmp_path).preflight(_with(tmp_path, rel))
    assert "rehearsal" in str(exc.value) and env in str(exc.value)
    assert box.calls == []


@pytest.mark.parametrize("env", ["TEST", "DEV"])
def test_a_test_box_takes_a_rehearsal_bundle(tmp_path: Path, env: str) -> None:
    assert _upd(EnvBox(env), tmp_path).run(_with(tmp_path, {**_release(False), "rehearsal": True}))["ok"]


def test_the_release_schema_knows_the_mark() -> None:
    schema = json.loads((ROOT / "schemas" / "release.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["rehearsal"] == {"type": "boolean", "description": schema["properties"]["rehearsal"][
        "description"]}  # fmt: skip
    assert "rehearsal" not in schema["required"]


# ---------------------------------------------------------------------------------- the review's findings
def test_the_stand_ins_are_known_by_their_content_wherever_they_lie(tmp_path: Path) -> None:
    """F1: a copy, or the release tree's own (current/tools/...), is the stand-ins all the same."""
    assert "\nx-trialbox-rehearsal-standins: true\n" in (ROOT / STANDINS).read_text(encoding="utf-8")
    start = INSTALL.index("is_standins() {")
    fn = INSTALL[start : INSTALL.index("\n}\n", start) + 3]
    copy = tmp_path / "elsewhere.yml"
    copy.write_text((ROOT / STANDINS).read_text(encoding="utf-8"), encoding="utf-8")
    other = tmp_path / "site.yml"
    other.write_text("services: {}\n", encoding="utf-8")
    r = _sh(tmp_path, f'{fn}\nis_standins "{copy}" && echo copy-is\nis_standins "{other}" || echo other-not')
    assert "copy-is" in r.stdout and "other-not" in r.stdout, r.stderr
    assert 'is_standins "$OVR" && rehearsal_only "the model stand-ins' in INSTALL


def test_doctor_fails_the_stand_ins_in_the_compose_files_of_a_site_box(tmp_path: Path) -> None:
    c = doctor.check_rehearsal(
        doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "COMPOSE_FILE": f"a.yml:{ROOT / STANDINS}"}, deploy=tmp_path)
    )
    assert c.status == "FAIL" and "stand-ins" in c.detail
    own_test = doctor.check_rehearsal(  # a hospital's own TEST box, not a rehearsal (F5)
        doctor.DoctorInputs(env={"TB_ENV": "TEST", "COMPOSE_FILE": str(ROOT / STANDINS)}, deploy=tmp_path)
    )
    assert own_test.status == "FAIL"
    rehearsal = doctor.check_rehearsal(
        doctor.DoctorInputs(env={"TB_ENV": "TEST", "TB_REHEARSAL": "1", "COMPOSE_FILE": str(ROOT / STANDINS)})
    )
    assert rehearsal.status == "WARN"


@pytest.mark.parametrize("where", ["mark", "env"])
def test_a_site_install_on_a_box_left_a_rehearsal_is_refused(tmp_path: Path, where: str) -> None:
    """F2: a leftover mark (a rehearsal that died, a box half emptied) never makes a site install TEST."""
    (tmp_path / "deploy" / "site").mkdir(parents=True)
    if where == "mark":
        (tmp_path / "deploy" / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    r = _sh(tmp_path, _block(EARLY), rehearsal=0, env_lines="TB_REHEARSAL=1\n" if where == "env" else None)
    assert r.returncode == 1 and "rehearsal" in r.stderr and "RUNBOOK" in r.stderr


def test_a_site_install_on_a_box_never_rehearsed_goes_on(tmp_path: Path) -> None:
    r = _sh(tmp_path, _block(EARLY), rehearsal=0, volumes="trialbox_db-data\n", env_lines="TB_ENV=PRODUCTION\n")
    assert r.returncode == 0, r.stderr
    assert "override=\n" in r.stdout and not (tmp_path / "deploy" / "site" / "rehearsal.json").exists()


@pytest.mark.parametrize("value", ["production", '"PRODUCTION"', "PRODUCTION\r", " VALIDATION ", "STAGING"])
@pytest.mark.parametrize("block", [EARLY, SETTINGS])
def test_any_spelling_of_a_site_environment_is_refused(tmp_path: Path, value: str, block: str) -> None:
    """F3: only DEV, TEST or nothing; the name as Python reads it (stripped, unquoted, upper case)."""
    r = _sh(tmp_path, _block(block), env_lines=f"TB_ENV={value}\n")
    assert r.returncode == 1 and "rehearsal" in r.stderr, r.stdout + r.stderr


@pytest.mark.parametrize("left", ["deploy/settings.yaml", "deploy/updates/installed.json"])
def test_a_box_with_settings_or_an_installed_release_is_refused(tmp_path: Path, left: str) -> None:
    """F4: the box's data is not only in volumes."""
    (tmp_path / left).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / left).write_text("{}\n", encoding="utf-8")
    r = _sh(tmp_path, _block(EARLY))
    assert r.returncode == 1 and left.removeprefix("deploy/") in r.stderr


def test_docker_that_cannot_list_volumes_stops_the_rehearsal_with_a_reason(tmp_path: Path) -> None:
    r = _sh(tmp_path, _block(EARLY), docker_rc=1)
    assert r.returncode == 1 and "cannot list" in r.stderr


@pytest.mark.parametrize("other", ["--prepare", "--firstrun"])
def test_a_prepared_or_first_run_box_is_never_a_rehearsal(other: str) -> None:
    """F7: a prepared box goes to a site."""
    r = subprocess.run(["bash", str(ROOT / "deploy" / "box-install.sh"), "x.tar", "--rehearsal", other],
                       capture_output=True, text=True, check=False, timeout=30)  # fmt: skip
    assert r.returncode == 2 and "--rehearsal" in r.stderr and other in r.stderr
