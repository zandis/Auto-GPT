"""D-887 (the integrator's (i), 2026-11-15): the box rehearsal runs on a VALIDATION box, where D3 goes to the box's own
models (D-823), so that SCREEN reaches both pinned builds through the gateway; a TEST box's class ceiling is D0.

The integrator's conditions, each tested here:
1. the rehearsal mark is written only by ``deploy/install.sh --rehearsal`` (deploy/site/rehearsal.json, then
   TB_REHEARSAL=1 in deploy/.env) and recorded in installed.json; an environment variable alone makes no rehearsal box;
2. the pin's three conditions stay (a rehearsal box, now TEST or VALIDATION with the recorded mark; a rehearsal
   bundle; every folder a placeholder); PRODUCTION never;
3. a rehearsal VALIDATION box is never mistaken for a validation box: the doctor's standing line, the console's
   banner, and qualify, ``--promote`` and promote-shipped refuse on it by name;
4. a VALIDATION box without the mark refuses a rehearsal bundle and a placeholder pin exactly as before;
5. the record says what the rehearsal reaches and what it cannot."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from registry.registry import DEFAULT_PATH, Registry, RegistryError
from tb_common.policy.classes import Environment

from tests.unit.test_rehearsal_placeholder_pin import JUDGE, _box
from tests.unit.test_rehearsal_profile import EARLY, SETTINGS, _block, _sh
from tests.unit.test_release_dirty_refused import EnvBox, _release, _upd, _with
from tools import pin_model
from tools.trialbox import doctor
from tools.trialbox import update as up

ROOT = Path(__file__).resolve().parents[2]
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
REHEARSAL_VALIDATION = {"TB_ENV": "VALIDATION", "TB_REHEARSAL": "1"}

pytestmark = pytest.mark.nodb


class MarkedBox(EnvBox):
    """A box whose deploy/site holds the mark install.sh --rehearsal writes (or not)."""

    def __init__(self, env: str, marked: bool) -> None:
        super().__init__(env)
        self._marked = marked

    def rehearsal_mark(self) -> bool:
        return self._marked

    def rehearsal_box(self) -> bool:
        return self._marked


# ------------------------------------------------------------------------------------- 1. the mark and its record
def test_the_installer_makes_the_rehearsal_box_validation(tmp_path: Path) -> None:
    (tmp_path / "deploy" / "site").mkdir(parents=True)
    (tmp_path / "deploy" / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    r = _sh(tmp_path, _block(SETTINGS), env_lines="TB_TZ=Asia/Taipei\n")
    assert r.returncode == 0, r.stderr
    lines = (tmp_path / "deploy" / ".env").read_text(encoding="utf-8").splitlines()
    assert "TB_ENV=VALIDATION" in lines and "TB_REHEARSAL=1" in lines and "TB_ENV=TEST" not in lines


def test_a_rehearsal_validation_box_run_again_goes_on(tmp_path: Path) -> None:
    (tmp_path / "deploy" / "site").mkdir(parents=True)
    (tmp_path / "deploy" / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    r = _sh(tmp_path, _block(EARLY), volumes="trialbox_db-data\n", env_lines="TB_ENV=VALIDATION\nTB_REHEARSAL=1\n")
    assert r.returncode == 0, r.stderr


def test_a_validation_box_without_the_mark_is_never_made_a_rehearsal_box(tmp_path: Path) -> None:
    """TB_REHEARSAL=1 written by hand is not the mark: the early block still refuses a VALIDATION box."""
    r = _sh(tmp_path, _block(EARLY), env_lines="TB_ENV=VALIDATION\nTB_REHEARSAL=1\n")
    assert r.returncode == 1 and "VALIDATION" in r.stderr
    assert not (tmp_path / "deploy" / "site" / "rehearsal.json").exists()


def test_the_load_records_the_mark_in_installed_json(tmp_path: Path) -> None:
    upd = _upd(MarkedBox("TEST", True), tmp_path)
    assert upd.run(_with(tmp_path, {**_release(True), "rehearsal": True}))["ok"]
    rec = json.loads((tmp_path / "updates" / "installed.json").read_text(encoding="utf-8"))
    assert rec["rehearsal"] is True and rec["rehearsal_box"] is True
    plain = tmp_path / "plain"
    assert _upd(MarkedBox("TEST", False), plain).run(_with(plain, {**_release(False), "rehearsal": True}))["ok"]
    assert "rehearsal_box" not in json.loads((plain / "updates" / "installed.json").read_text(encoding="utf-8"))


def test_the_compose_box_reads_the_mark_and_the_env_file(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    box = up.ComposeBox(deploy)
    assert not box.rehearsal_mark() and not box.rehearsal_box()
    (deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")
    assert box.rehearsal_mark() and box.rehearsal_box()  # the first load: no deploy/.env yet
    (deploy / ".env").write_text("TB_ENV=VALIDATION\n", encoding="utf-8")
    assert not box.rehearsal_box()  # the mark alone, on a box whose deploy/.env lost TB_REHEARSAL: not a rehearsal
    (deploy / ".env").write_text("TB_ENV=VALIDATION\nTB_REHEARSAL=1\n", encoding="utf-8")
    assert box.rehearsal_box()


# ------------------------------------------------------------------------------------ 2. the pin's three conditions
def _validation_box(tmp: Path, *, recorded: bool = True) -> tuple[Path, Path]:
    models, out = _box(tmp)
    rec_path = tmp / "deploy" / "updates" / "installed.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    if not recorded:
        rec.pop("rehearsal_box", None)
    rec_path.write_text(json.dumps(rec), encoding="utf-8")
    return models, out


def test_a_rehearsal_validation_box_pins_the_placeholders_and_the_gateway_routes_them(tmp_path: Path) -> None:
    models, out = _validation_box(tmp_path)
    ok, lines = pin_model.install_pins("rtxpro6000", models, out, dict(REHEARSAL_VALIDATION))
    assert ok, lines
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))["builds"]
    assert {e["status"] for e in doc.values()} == {"candidate"}
    reg = Registry.load(DEFAULT_PATH, out)
    for env in (Environment.TEST, Environment.VALIDATION):
        assert reg.resolve("j-workhorse", "serving", role="judge", env=env).build.build_id == JUDGE
    with pytest.raises(RegistryError):
        reg.resolve("j-workhorse", "serving", role="judge", env=Environment.PRODUCTION)


@pytest.mark.parametrize(
    ("env", "recorded", "why"),
    [
        ({"TB_ENV": "VALIDATION"}, True, "rehearsal box"),  # no TB_REHEARSAL
        (REHEARSAL_VALIDATION, False, "rehearsal box"),  # TB_REHEARSAL=1 but installed.json records no mark
        ({"TB_ENV": "PRODUCTION", "TB_REHEARSAL": "1"}, True, "rehearsal box"),  # never PRODUCTION
        ({"TB_ENV": "DEV", "TB_REHEARSAL": "1"}, True, "rehearsal box"),
    ],
)
def test_without_the_recorded_mark_or_on_another_box_nothing_is_pinned(
    tmp_path: Path, env: dict[str, str], recorded: bool, why: str
) -> None:
    models, out = _validation_box(tmp_path, recorded=recorded)
    ok, lines = pin_model.install_pins("rtxpro6000", models, out, env)
    assert not ok and any(why in x for x in lines), lines
    assert not out.exists()


# --------------------------------------------------------------------------- 3. never mistaken for a validation box
def _mark(deploy: Path) -> None:
    (deploy / "site").mkdir(parents=True, exist_ok=True)
    (deploy / "site" / "rehearsal.json").write_text('{"rehearsal": true}\n', encoding="utf-8")


def test_the_doctor_carries_a_standing_line_on_a_rehearsal_validation_box(tmp_path: Path) -> None:
    _mark(tmp_path)
    c = doctor.check_rehearsal(doctor.DoctorInputs(env=dict(REHEARSAL_VALIDATION), deploy=tmp_path))
    assert c.status == "WARN" and "REHEARSAL BOX: placeholder models, synthetic data only" in c.detail
    # no setting turns it off: every other variable the box could carry leaves it there
    loud = {**REHEARSAL_VALIDATION, "TB_DOCTOR_QUIET": "1", "TB_REHEARSAL_QUIET": "1", "TB_HOST_PROFILE": "poc"}
    assert "REHEARSAL BOX" in doctor.check_rehearsal(doctor.DoctorInputs(env=loud, deploy=tmp_path)).detail
    test_box = doctor.check_rehearsal(doctor.DoctorInputs(env={"TB_ENV": "TEST", "TB_REHEARSAL": "1"}))
    assert test_box.status == "WARN" and "REHEARSAL BOX" in test_box.detail


def test_the_doctor_fails_half_a_mark_on_a_validation_box(tmp_path: Path) -> None:
    """TB_REHEARSAL=1 without the mark file (or the file without TB_REHEARSAL) on VALIDATION: a site box that was
    touched by hand, never a rehearsal box."""
    c = doctor.check_rehearsal(doctor.DoctorInputs(env=dict(REHEARSAL_VALIDATION), deploy=tmp_path))
    assert c.status == "FAIL" and "VALIDATION" in c.detail
    _mark(tmp_path)
    c = doctor.check_rehearsal(doctor.DoctorInputs(env={"TB_ENV": "VALIDATION"}, deploy=tmp_path))
    assert c.status == "FAIL"


def test_a_validation_box_routes_its_candidate_pair_and_the_doctor_says_pass(tmp_path: Path) -> None:
    """D-823: VALIDATION routes candidates; "none is champion, so VALIDATION roles route nothing" was wrong there."""
    models, out = _validation_box(tmp_path)
    assert pin_model.install_pins("rtxpro6000", models, out, dict(REHEARSAL_VALIDATION))[0]
    c = doctor.check_registry_pins(
        doctor.DoctorInputs(env={**REHEARSAL_VALIDATION, "TB_REGISTRY_OVERRIDE": str(out)}, deploy=tmp_path / "deploy")
    )
    assert c.status == "PASS" and "rehearsal placeholder" in c.detail, c.detail
    prod = doctor.check_registry_pins(
        doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_REGISTRY_OVERRIDE": str(out)}, deploy=tmp_path / "deploy")
    )
    assert prod.status == "WARN" and "route nothing" in prod.detail


def test_the_console_banner_says_rehearsal() -> None:
    from console.app import environment_banner

    assert "REHEARSAL" in environment_banner({"TB_ENV": "VALIDATION", "TB_REHEARSAL": "1"})
    assert "REHEARSAL" not in environment_banner({"TB_ENV": "VALIDATION"})
    assert "REHEARSAL" in environment_banner({"TB_ENV": "TEST", "TB_REHEARSAL": "1"})


def test_promote_and_promote_shipped_refuse_on_a_rehearsal_box_by_name(tmp_path: Path, capsys: Any) -> None:
    models, out = _validation_box(tmp_path)
    assert pin_model.install_pins("rtxpro6000", models, out, dict(REHEARSAL_VALIDATION))[0]
    _mark(out.parent.parent)  # deploy/site/rehearsal.json beside the pins
    with pytest.raises(pin_model.PinError, match="rehearsal box"):
        pin_model.promote(JUDGE, tmp_path / "any-record.json", out)
    rc = pin_model.main(["--promote-shipped", "rtxpro6000", "--records", str(tmp_path / "q"), "--out", str(out)])
    assert rc == 5 and "rehearsal box" in capsys.readouterr().out


def test_qualify_refuses_on_a_rehearsal_box_by_name(tmp_path: Path) -> None:
    from tools import qualify as q

    models, out = _validation_box(tmp_path)
    assert pin_model.install_pins("rtxpro6000", models, out, dict(REHEARSAL_VALIDATION))[0]
    _mark(out.parent.parent)
    got = q.placeholder_problems(out)
    assert any("rehearsal box" in p for p in got), got


# ---------------------------------------------------------------- 4. a VALIDATION box without the mark: as before
def test_a_validation_box_without_the_mark_refuses_a_rehearsal_bundle(tmp_path: Path) -> None:
    box = MarkedBox("VALIDATION", False)
    with pytest.raises(up.UpdateRefused) as exc:
        _upd(box, tmp_path).preflight(_with(tmp_path, {**_release(False), "rehearsal": True}))
    assert "rehearsal" in str(exc.value) and "VALIDATION" in str(exc.value)
    assert box.calls == []


def test_a_marked_rehearsal_validation_box_takes_its_rehearsal_bundle(tmp_path: Path) -> None:
    """The second install of the rehearsal (the reinstall step), once deploy/.env says VALIDATION: a working tree's
    rehearsal bundle, as the rehearsal makes it (tools/make_bundle.sh --allow-dirty --rehearsal)."""
    assert _upd(MarkedBox("VALIDATION", True), tmp_path).run(_with(tmp_path, {**_release(True), "rehearsal": True}))[
        "ok"
    ]


def test_a_production_box_refuses_a_rehearsal_bundle_whatever_marks_it_carries(tmp_path: Path) -> None:
    box = MarkedBox("PRODUCTION", True)
    with pytest.raises(up.UpdateRefused):
        _upd(box, tmp_path).preflight(_with(tmp_path, {**_release(False), "rehearsal": True}))


def test_the_stand_ins_need_the_mark_file_on_a_validation_box(tmp_path: Path) -> None:
    start = INSTALL.index("rehearsal_only() {")
    fn = INSTALL[start : INSTALL.index("\n}\n", start) + 3]
    body = f'TB_ENV_SITE=VALIDATION\n{fn}\nrehearsal_only standins "the model stand-ins"\necho through'
    r = _sh(tmp_path, body, env_lines="TB_ENV=VALIDATION\nTB_REHEARSAL=1\n")
    # TB_REHEARSAL=1 alone, no mark file. H-94 (the owner's ruling 7092087958): a VALIDATION box is a PoC box, so it
    # is a warning and a line of the list, and the step goes on; on PRODUCTION it stops (below)
    assert r.returncode == 0 and "through" in r.stdout and "warning (PoC box, H-94)" in r.stderr
    assert "--rehearsal" in r.stderr
    prod = _sh(tmp_path, body.replace("TB_ENV_SITE=VALIDATION", "TB_ENV_SITE=PRODUCTION"),
               env_lines="TB_ENV=PRODUCTION\nTB_REHEARSAL=1\n")  # fmt: skip
    assert prod.returncode == 1 and "--rehearsal" in prod.stderr and "through" not in prod.stdout
    _mark(tmp_path / "deploy")
    r = _sh(tmp_path, body, env_lines="TB_ENV=VALIDATION\nTB_REHEARSAL=1\n")
    assert r.returncode == 0 and "through" in r.stdout, r.stderr


def test_the_host_check_knows_a_rehearsal_validation_box_by_both_marks() -> None:
    check = (ROOT / "deploy" / "check_host.sh").read_text(encoding="utf-8")
    start = check.index("rehearsal_box() {")
    fn = check[start : check.index("}", start) + 1]
    assert "VALIDATION" in fn and "rehearsal.json" in fn and "TB_REHEARSAL" in fn
    assert subprocess.run(["bash", "-n", str(ROOT / "deploy" / "check_host.sh")], check=False).returncode == 0


# ------------------------------------------------------------------------------------------------- 5. the record
def test_the_record_says_what_the_rehearsal_reaches_and_what_it_cannot() -> None:
    record = next((ROOT / "docs" / "decisions").glob("D-887-*.md")).read_text(encoding="utf-8")
    flat = " ".join(record.split())
    for reached in ("VALIDATION's gates", "D3 on the box", "both pinned builds through the gateway"):
        assert reached in flat, reached
    for unreached in ("a real model", "a GPU", "the shipped egress rules", "a TPM"):
        assert unreached in flat, unreached


def test_the_rehearsal_installs_the_example_study_as_an_operator_does_on_a_validation_box() -> None:
    """A VALIDATION box seeds no example (D-640): the seventh run's SCREEN found no approved GZQO. The rehearsal
    installs it by the operator's synthetic-run command of RUNBOOK §1 step 2, before SCREEN; and its own doctor call
    reads the box's deploy/.env as the host check's does (db_passwords and chartno_rule were not judged)."""
    box = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    screen = box[box.index("\nscreen)") : box.index("in_svc mail-gateway", box.index("\nscreen)"))]
    assert 'python -m criteria_compiler.import_ruleset /tmp/GZQO.zip --by "synthetic-run:box-rehearsal"' in screen
    runbook = " ".join((ROOT / "docs" / "runbook" / "01-install-a-new-site.md").read_text(encoding="utf-8").split())
    assert 'python -m criteria_compiler.import_ruleset /tmp/GZQO.zip --by "synthetic-run:<who>"' in runbook
    helper = box[box.index("doctor() {") : box.index("\n}\n", box.index("doctor() {"))]
    assert "--env-file /app/deploy/.env" in helper


def test_the_probe_names_the_prompt_and_the_doctor_sees_the_stand_ins_file() -> None:
    """The eighth run (SCREEN passed on VALIDATION): outside DEV and TEST the gateway requires X-TB-Prompt-Sha, so the
    wrong-name and missing-key probes were refused prompt_changed, not for the fault they test; and the doctor's
    db_passwords and chartno_rule could not read the stand-ins compose file outside deploy/."""
    box = (ROOT / "tools" / "rehearse_box" / "box.sh").read_text(encoding="utf-8")
    probe = box[box.index("gateway_probe() {") : box.index("\nEOF\n", box.index("gateway_probe() {"))]
    assert "prompt_sha=p.sha256" in probe
    helper = box[box.index("doctor() {") : box.index("\n}\n", box.index("doctor() {"))]
    assert 'more+=(-v "$cf:$cf:ro")' in helper and "COMPOSE_FILE" in helper
