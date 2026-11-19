"""10K-21 (D-1365; review 18, SO-21): three choices that were silent are guarded.

1. The chart-number rule: on a PRODUCTION site the settings wizard refuses to finish without an explicit rule
   (``asis`` typed is an answer; Enter or no key is not). ``deploy/install.sh`` tells the wizard the environment.
2. The ``health-page`` backup alert route names the person who opens the health page every working day
   (``TB_BACKUP_ALERT_WATCHER``), stored with the route and shown where the route is shown (the backup install's
   note, ``doctor``).
3. Caddy's own CA: who in hospital IT confirmed the root is on every clinic PC, and when, is recorded once the root
   exists (the box's first-run page, or ``deploy/.env``); the terminal wizard, which runs before it exists, records
   none; ``doctor`` reports a missing confirmation (a WARN in PRODUCTION).

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


def _wiz_run(**var: str) -> subprocess.CompletedProcess[str]:
    script = (
        "set -euo pipefail\n"
        'die() { printf "install: %s\\n" "$*" >&2; exit 1; }\n'
        f"ENVIRONMENT={var.get('ENVIRONMENT', '')!r}\nREHEARSAL={var.get('REHEARSAL', '0')}\n"
        f"PRE_ENV={var.get('PRE_ENV', '')!r}\n{_wiz_block()}\n"
        'printf "%s" "${WIZ_ARGS[*]-}"\n'
    )
    env = {k: v for k, v in os.environ.items() if k != "TB_BOX"}
    if "TB_BOX" in var:
        env["TB_BOX"] = var["TB_BOX"]
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, check=False)


def _wiz_env(**var: str) -> str:
    res = _wiz_run(**var)
    assert res.returncode == 0, res.stderr
    return res.stdout


@pytest.mark.parametrize(
    "var",
    [
        {"ENVIRONMENT": "prod"},
        {"ENVIRONMENT": " PRODUCTION"},
        {"PRE_ENV": "BOGUS"},
        {"PRE_ENV": "BOGUS", "TB_BOX": "1"},
    ],
)
def test_an_unknown_environment_stops_the_install_before_the_wizard(var: dict[str, str]) -> None:
    """Review of #1175, S1: a typo never runs the wizard unguarded (it would leave a settings.yaml the next run
    keeps): the block stops with nothing written, before the wizard's docker run."""
    res = _wiz_run(**var)
    assert res.returncode == 1 and "is not DEV, TEST, VALIDATION or PRODUCTION: nothing was written" in res.stderr
    assert res.stdout == ""
    assert INSTALL.index("# ---- end of WIZARD-ENV (D-1365)") < INSTALL.index("SETTINGS_NEW=0")


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
def test_the_terminal_wizard_records_no_confirmation_before_the_root_exists() -> None:
    """Review of #1175, S3: the wizard runs before Caddy's first start, when there is no root to push: an answer is
    not recorded as a confirmation, and the warning says the next action (a doctor WARN in PRODUCTION after)."""
    env, warnings = _build("PRODUCTION", tls_mode="internal", tls_root_confirmed_by="Lin, IT desk")
    assert "TB_TLS_ROOT_CONFIRMED_BY" not in env and "TB_TLS_ROOT_CONFIRMED_ON" not in env
    assert any("is not recorded: the root does not exist yet" in w for w in warnings)
    env, warnings = _build("PRODUCTION", tls_mode="internal")  # a warning, never a refusal
    assert "TB_TLS_ROOT_CONFIRMED_BY" not in env
    assert any("put TB_TLS_ROOT_CONFIRMED_BY" in w and "TB_TLS_ROOT_CONFIRMED_ON" in w for w in warnings)
    assert "tls_root_confirmed_by" not in [q[0] for q in settings_wizard.QUESTIONS]  # not asked at install
    c = doctor.check_named_choices(doctor.DoctorInputs(env={**LEGACY_PROD, **env}))
    assert c.status == "WARN" and "TB_TLS_ROOT_CONFIRMED_BY" in c.detail  # the fresh install stays in sight


def test_the_box_plan_carries_it_s_confirmation() -> None:
    from tests.unit.test_box_plan import OWNER, _hw

    a, problems = parse(OWNER | {"tls_root_confirmed_by": "Lin"}, disks=("/dev/sdb",))
    assert a is not None, problems
    env = bp.plan(a, _hw()).env_extra
    assert env["TB_TLS_ROOT_CONFIRMED_BY"] == "Lin" and env["TB_TLS_ROOT_CONFIRMED_ON"] == date.today().isoformat()


# ----------------------------------------------------------- B2: a name is one printable line for every reader
SEPARATORS = ["\u2028", "\u2029", "\u0085"]  # str.splitlines breaks at each; .env's Python readers use it


@pytest.mark.parametrize("sep", SEPARATORS)
def test_a_watcher_name_with_a_unicode_line_break_is_refused_and_never_reaches_env(sep: str) -> None:
    name = f"Jane Doe{sep}TB_ENV=DEV"
    for environment in ("", "PRODUCTION"):
        with pytest.raises(settings_wizard.WizardError, match="TB_BACKUP_ALERT_WATCHER is not one plain name"):
            _build(environment, env_extra={**PAGE, "TB_BACKUP_ALERT_WATCHER": name})


@pytest.mark.parametrize("field", ["health_page_person", "tls_root_confirmed_by"])
@pytest.mark.parametrize("sep", SEPARATORS)
def test_the_first_run_answers_refuse_a_unicode_line_break_in_a_name(field: str, sep: str) -> None:
    from tests.unit.test_box_plan import OWNER

    a, problems = parse(OWNER | {field: f"Lin{sep}TB_CONSOLE_SECURE_COOKIE=0"}, disks=("/dev/sdb",))
    assert a is None and [(p.field, p.code) for p in problems] == [(field, "person_name")]


def test_a_name_is_one_printable_line_and_a_japanese_space_is_kept() -> None:
    from tb_common.box_answers import person_name

    assert person_name("山田\u3000花子") == "山田\u3000花子" and person_name("陳 小明") == "陳 小明"
    for bad in ("a\u200bb", "a\x0bb", "a\u00a0b\u2028", "x" * 101, "a\tb"):
        assert person_name(bad) is None, repr(bad)


def test_a_written_watcher_is_read_back_as_one_value(tmp_path: Path) -> None:
    from tb_common.config import _read_dotenv

    env, _ = _build("PRODUCTION", chartno_rule="asis", env_extra={**PAGE, "TB_BACKUP_ALERT_WATCHER": "山田\u3000花子"})
    f = tmp_path / ".env"
    f.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
    back = _read_dotenv(f)
    assert back["TB_BACKUP_ALERT_WATCHER"] == "山田\u3000花子" and set(back) == set(env)


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
