"""10K-21 (D-1365; review 18, SO-21): three choices that were silent are guarded.

1. The chart-number rule: on a PRODUCTION site the settings wizard refuses to finish without an explicit rule
   (``asis`` typed is an answer; Enter or no key is not). ``deploy/install.sh`` tells the wizard the environment.
2. The ``health-page`` backup alert route names the person who opens the health page every working day
   (``TB_BACKUP_ALERT_WATCHER``), stored with the route and shown where the route is shown (the backup install's
   note, ``doctor``).
3. Caddy's own CA: the wizard asks who in hospital IT confirmed the root is on every clinic PC and records who and
   when; ``doctor`` reports a missing confirmation.

An installed site keeps working: its answers files read as before outside PRODUCTION, and a PRODUCTION site without
the new answers gets a ``doctor`` WARN with the next action, never a FAIL (``named_choices``). The box's first-run
page is tested in tests/console/test_firstrun_silent_choices.py."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common.box_answers import parse

from tools import settings_wizard
from tools.backup_drill import DEPLOY
from tools.box import plan as bp
from tools.trialbox import backup_schedule as bs
from tools.trialbox import doctor

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]
REHEARSAL = ROOT / "tools" / "rehearse_box"
INSTALL = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
WIZ_MARK = "# WIZARD-ENV (D-1365)"


def _answers(**over: Any) -> dict[str, Any]:
    a: dict[str, Any] = yaml.safe_load((REHEARSAL / "site_answers.yaml").read_text(encoding="utf-8"))
    a.update({"llm_mode": "stub", **over})
    return {k: v for k, v in a.items() if v is not None}


def _build(environment: str = "", **over: Any) -> tuple[dict[str, str], list[str]]:
    _s, env, warnings = settings_wizard.build(_answers(**over), [REHEARSAL / "mapping"], environment=environment)
    return env, warnings


# ------------------------------------------------------------------------------------- 1. the chart-number rule
def test_production_refuses_an_unanswered_chart_number_rule() -> None:
    with pytest.raises(settings_wizard.WizardError, match="chartno_rule is required in PRODUCTION"):
        _build("PRODUCTION", chartno_rule=None)
    with pytest.raises(settings_wizard.WizardError, match="chartno_rule is required in PRODUCTION"):
        _build("production", chartno_rule="  ")


def test_asis_typed_is_an_answer_and_is_recorded_as_chosen() -> None:
    env, _ = _build("PRODUCTION", chartno_rule="asis", mrn_regex=r"^\d{8}$")
    assert env["TB_CHARTNO_RULE"] == "asis" and env["TB_CHARTNO_RULE_ANSWERED"] == "yes"


@pytest.mark.parametrize("environment", ["", "TEST", "VALIDATION"])
def test_outside_production_an_unanswered_rule_is_asis_and_a_warning_as_before(environment: str) -> None:
    env, warnings = _build(environment, chartno_rule=None)
    assert env["TB_CHARTNO_RULE"] == "asis" and "TB_CHARTNO_RULE_ANSWERED" not in env
    assert any("chartno_rule was not answered" in w for w in warnings)


def test_the_terminal_wizard_asks_the_rule_again_in_production() -> None:
    """Interactive: Enter is not an answer to the chart-number question on a PRODUCTION site; asis typed is."""
    replies: list[str] = []

    def prompt(text: str) -> str:
        replies.append(text)
        if text.startswith("Country"):
            return "tw"
        if text.startswith("Chart-number format"):
            return "asis" if sum(r.startswith("Chart-number format") for r in replies) == 3 else ""
        return ""

    out = settings_wizard.ask({}, prompt, environment="PRODUCTION")
    asked = [r for r in replies if r.startswith("Chart-number format")]
    assert out["chartno_rule"] == "asis" and len(asked) == 3
    assert settings_wizard.CHARTNO_REQUIRED in asked[0]
    with pytest.raises(settings_wizard.WizardError, match="required in PRODUCTION"):
        settings_wizard.ask({}, lambda t: "tw" if t.startswith("Country") else "", environment="PRODUCTION")
    calm = settings_wizard.ask({}, lambda t: "tw" if t.startswith("Country") else "")  # not told: as before
    assert calm["chartno_rule"] == ""


def test_the_command_takes_the_environment_and_refuses_without_writing(tmp_path: Path) -> None:
    """A new command-line path: run once without PYTHONUNBUFFERED set (the lane's rule)."""
    answers = _answers(chartno_rule=None, data_source_host_dir=str(tmp_path))
    f = tmp_path / "site.yaml"
    f.write_text(yaml.safe_dump(answers), encoding="utf-8")
    out = tmp_path / "settings.yaml"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env["PYTHONPATH"] = os.pathsep.join(str(ROOT / p) for p in ("libs", "services", "."))
    run = subprocess.run(
        [sys.executable, "-m", "tools.settings_wizard", "--answers", str(f), "--out", str(out), "--environment",
         "production", "--mapping-dir", str(REHEARSAL / "mapping")],
        capture_output=True, text=True, cwd=ROOT, env=env, check=False, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    assert run.returncode == 1 and "not written: " in run.stderr and "chartno_rule is required" in run.stderr
    assert not out.exists()


# ----------------------------------------------------------------- the installer tells the wizard the environment
def _wiz_block() -> str:
    start = INSTALL.index(WIZ_MARK)
    return INSTALL[start : INSTALL.index("# ---- end of WIZARD-ENV (D-1365)", start)]


def _wiz_env(**var: str) -> str:
    script = (
        "set -euo pipefail\n"
        f"ENVIRONMENT={var.get('ENVIRONMENT', '')!r}\nREHEARSAL={var.get('REHEARSAL', '0')}\n"
        f"PRE_ENV={var.get('PRE_ENV', '')!r}\n{_wiz_block()}\n"
        'printf "%s" "${WIZ_ARGS[*]-}"\n'
    )
    env = {k: v for k, v in os.environ.items() if k != "TB_BOX"}
    if "TB_BOX" in var:
        env["TB_BOX"] = var["TB_BOX"]
    res = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=True)
    return res.stdout


def test_the_installer_tells_the_wizard_the_environment_as_it_decides_it() -> None:
    assert _wiz_env() == "--environment PRODUCTION"  # D-127: nothing set is PRODUCTION
    assert _wiz_env(ENVIRONMENT="validation") == "--environment VALIDATION"
    assert _wiz_env(REHEARSAL="1") == "--environment VALIDATION"
    assert _wiz_env(PRE_ENV="TEST") == "--environment TEST"
    assert _wiz_env(TB_BOX="1") == ""  # the box's first-run page asks the questions itself
    assert INSTALL.index(WIZ_MARK) < INSTALL.index("python -m tools.settings_wizard --answers")
    assert INSTALL.count('--env-out /out/.env ${WIZ_ARGS[@]+"${WIZ_ARGS[@]}"}') == 2  # answers file and questions


# ------------------------------------------------------------------------------- 2. the health page's watcher
PAGE = {"TB_BACKUP_ALERT_ROUTE": "health-page"}


def test_the_page_route_without_a_named_person_is_refused_in_production() -> None:
    with pytest.raises(settings_wizard.WizardError, match="nobody is named to open it every working day"):
        _build("PRODUCTION", env_extra=PAGE)
    _env, warnings = _build("", env_extra=PAGE)  # the box's apply step after its page: a warning
    assert any("nobody is named" in w for w in warnings)
    env, warnings = _build("PRODUCTION", env_extra={**PAGE, "TB_BACKUP_ALERT_WATCHER": "陳 小明"})
    assert env["TB_BACKUP_ALERT_WATCHER"] == "陳 小明" and not any("nobody is named" in w for w in warnings)
    with pytest.raises(settings_wizard.WizardError, match="TB_BACKUP_ALERT_WATCHER is not one plain name"):
        _build("", env_extra={**PAGE, "TB_BACKUP_ALERT_WATCHER": "x $(id)"})


def test_the_box_plan_stores_the_person_with_the_route() -> None:
    from tests.unit.test_box_plan import OWNER, _hw

    a, problems = parse(OWNER | {"health_page_person": "Dr Owner"}, disks=("/dev/sdb",))
    assert a is not None, problems
    env = bp.plan(a, _hw()).env_extra
    assert env["TB_BACKUP_ALERT_ROUTE"] == "health-page" and env["TB_BACKUP_ALERT_WATCHER"] == "Dr Owner"
    assert "TB_BACKUP_ALERT_WATCHER" not in bp.plan(bp.provisional(_hw()), _hw()).env_extra  # not asked: as before


def _deploy(tmp_path: Path) -> Path:
    deploy = tmp_path / "opt" / "tb" / "deploy"
    (deploy / "backup").mkdir(parents=True)
    (deploy / "backup" / "trialbox-backup.cron").write_text(
        (DEPLOY / "backup" / "trialbox-backup.cron").read_text(encoding="utf-8")
    )
    return deploy


def test_the_person_is_shown_where_the_route_is_shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("TB_BACKUP_ALERT_CMD", "TB_BACKUP_MAILTO", "TB_BACKUP_ALERT_ROUTE", "TB_BACKUP_ALERT_WATCHER"):
        monkeypatch.delenv(k, raising=False)
    deploy = _deploy(tmp_path)
    named = {"TB_ENV": "PRODUCTION", **PAGE, "TB_BACKUP_ALERT_WATCHER": "Dr Owner"}
    notes = bs.install_cron(bs.config(deploy, named), tmp_path / "cron.d", deploy.parent, has_mta=False)
    assert any("Dr Owner opens the health tab every working day" in n for n in notes), notes
    notes = bs.install_cron(bs.config(deploy, {"TB_ENV": "PRODUCTION", **PAGE}), tmp_path / "c2", deploy.parent,
                            has_mta=False)  # fmt: skip
    assert any("set TB_BACKUP_ALERT_WATCHER" in n for n in notes), notes  # a site from before: installs, told
    monkeypatch.setattr(bs, "has_mta", lambda: False)
    inp = doctor.DoctorInputs(env=named, deploy=deploy, cron_dir=tmp_path / "none")
    assert "Dr Owner opens the health tab" in doctor.check_backup(inp).detail


# ------------------------------------------------------------------------------- 3. IT's confirmation of the root
def test_the_internal_ca_records_who_confirmed_and_when() -> None:
    env, warnings = _build("PRODUCTION", tls_mode="internal", tls_root_confirmed_by="Lin, IT desk")
    assert env["TB_TLS_ROOT_CONFIRMED_BY"] == "Lin, IT desk"
    assert env["TB_TLS_ROOT_CONFIRMED_ON"] == date.today().isoformat()
    assert not any("nobody from hospital IT" in w for w in warnings)
    env, _ = _build("", tls_mode="internal", tls_root_confirmed_by="Lin", tls_root_confirmed_on="2026-11-02")
    assert env["TB_TLS_ROOT_CONFIRMED_ON"] == "2026-11-02"
    with pytest.raises(settings_wizard.WizardError, match="tls_root_confirmed_on"):
        _build("", tls_mode="internal", tls_root_confirmed_by="Lin", tls_root_confirmed_on="next week")


def test_no_confirmation_is_a_warning_never_a_refusal() -> None:
    """A new box makes its root at Caddy's first start: IT cannot have pushed it before the install."""
    env, warnings = _build("PRODUCTION", tls_mode="internal")
    assert "TB_TLS_ROOT_CONFIRMED_BY" not in env
    assert any(w.startswith("tls_mode internal: nobody from hospital IT has confirmed") for w in warnings)


def test_the_wizard_asks_the_confirmation_for_caddy_s_ca_only() -> None:
    keys = [q[0] for q in settings_wizard.QUESTIONS]
    assert keys.index("tls_root_confirmed_by") > keys.index("tls_mode")
    from tb_common import site_country

    cd = site_country.LEGACY
    assert settings_wizard._asked("tls_root_confirmed_by", cd, {"tls_mode": "internal"})
    assert not settings_wizard._asked("tls_root_confirmed_by", cd, {"tls_mode": "hospital"})


def test_the_box_plan_carries_it_s_confirmation() -> None:
    from tests.unit.test_box_plan import OWNER, _hw

    a, problems = parse(OWNER | {"tls_root_confirmed_by": "Lin"}, disks=("/dev/sdb",))
    assert a is not None, problems
    env = bp.plan(a, _hw()).env_extra
    assert env["TB_TLS_ROOT_CONFIRMED_BY"] == "Lin" and env["TB_TLS_ROOT_CONFIRMED_ON"] == date.today().isoformat()


# -------------------------------------------------------------------- doctor: a site from before is told, not stopped
LEGACY_PROD = {"TB_ENV": "PRODUCTION", "TB_CHARTNO_RULE": "asis", **PAGE, "TB_TLS_HOSTNAME": "trialbox.hospa.test",
               "TB_TLS_MODE": "internal"}  # fmt: skip


def test_a_production_site_from_before_gets_a_warning_with_each_next_action() -> None:
    c = doctor.check_named_choices(doctor.DoctorInputs(env=LEGACY_PROD))
    assert c.status == "WARN"
    assert "TB_CHARTNO_RULE_ANSWERED=yes" in c.detail
    assert "set TB_BACKUP_ALERT_WATCHER" in c.detail
    assert "TB_TLS_ROOT_CONFIRMED_BY" in c.detail and "TB_TLS_ROOT_CONFIRMED_ON" in c.detail


def test_a_site_with_the_answers_passes_and_says_them() -> None:
    env = {**LEGACY_PROD, "TB_CHARTNO_RULE_ANSWERED": "yes", "TB_BACKUP_ALERT_WATCHER": "Dr Owner",
           "TB_TLS_ROOT_CONFIRMED_BY": "Lin", "TB_TLS_ROOT_CONFIRMED_ON": "2026-11-02"}  # fmt: skip
    c = doctor.check_named_choices(doctor.DoctorInputs(env=env))
    assert c.status == "PASS" and "Dr Owner" in c.detail and "confirmed by Lin on 2026-11-02" in c.detail
    ruled = doctor.check_named_choices(doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_CHARTNO_RULE": "digits:8"}))
    assert ruled.status == "PASS"  # only an answer gives a rule other than asis; the hospital's certificate: nothing


def test_outside_production_the_check_passes_and_names_what_is_open() -> None:
    c = doctor.check_named_choices(doctor.DoctorInputs(env={**LEGACY_PROD, "TB_ENV": "VALIDATION"}))
    assert c.status == "PASS" and c.detail.startswith("VALIDATION: not required")
