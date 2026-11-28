"""TOL-INSTALL part 2 (TOL-1 section 2.1): the minute-1 preflight on a PRODUCTION install's answers, the health page
as an answer and as the default of the backup alert route, and the unnamed watcher as a warning."""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
import yaml
from tb_common import site_needs

from tests.unit.test_poc_stops_bench_h94 import Box
from tests.unit.test_poc_stops_h94 import PLANTED, PROD_SITE, RUNNING
from tools import settings_wizard
from tools.trialbox import backup_schedule, update

pytestmark = [pytest.mark.nodb]
ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "tests" / "fixtures" / "onboarding" / "site_c_answers.yaml"  # synthetic; no off-box folders or route


def test_the_dry_run_names_the_four_items_still_needed(capsys: pytest.CaptureFixture[str]) -> None:
    """Done-when (a) at minute 1: the kit minus the audit share, the backup target and the alert route (and no backup
    key yet) is read, nothing refused, and each item that stays open is one line."""
    assert settings_wizard.main(["--answers", str(KIT), "--dry-run", "--environment", "PRODUCTION"]) == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("still needed after the install")]
    want =[n.title["en"] for n in site_needs.NEEDS if n.key in ("backup_target", "backup_key", "backup_alarm",
                                                                    "audit_share")]  # fmt: skip
    assert len(lines) == 4 and all(any(t in ln for ln in lines) for t in want), out


def test_the_dry_run_refuses_a_bad_answer_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = yaml.safe_load(KIT.read_text(encoding="utf-8"))
    del answers["tz"]
    bad = tmp_path / "answers.yaml"
    bad.write_text(yaml.safe_dump(answers, allow_unicode=True), encoding="utf-8")
    assert settings_wizard.main(["--answers", str(bad), "--dry-run", "--environment", "PRODUCTION"]) == 1
    err = capsys.readouterr().err
    assert "the answers are refused, nothing was loaded or written: " in err and "tz is required" in err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["answers.yaml"]


def test_a_malformed_answers_file_is_refused_without_its_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review I1: a YAML error says where, never the line it quotes (a planted secret stays out of the log)."""
    bad = tmp_path / "answers.yaml"
    bad.write_text("site_name: Site A\nadmin_password: synthetic-s3cret: [\n", encoding="utf-8")
    assert settings_wizard.main(["--answers", str(bad), "--dry-run", "--environment", "PRODUCTION"]) == 1
    out = capsys.readouterr()
    assert re.search(r"answers\.yaml is not valid YAML at line 2, column \d+$", out.err.strip()), out.err
    assert not any(s in out.out + out.err for s in ("s3cret", "admin_password"))


def test_a_production_install_refuses_a_bad_answer_within_a_minute_before_the_load(tmp_path: Path) -> None:
    """Done-when (d): the refusal is in the install's log within 60 s of the start, and nothing was loaded."""
    box = Box(tmp_path / "prod", env=PROD_SITE + f"TB_SOURCE_DIR={tmp_path}\n")
    started = time.monotonic()
    r = box.install("--mode", "stub", "--yes", force=("preflight-answers",), env={"TB_BOX_DEFER_SEAL": "1", **PLANTED})
    assert time.monotonic() - started < 60
    assert r.rc == 1 and r.err.splitlines()[-1].startswith("the answers are refused"), r.text[-3000:]
    assert "preflight: the answers, read before the load" in r.out and "bundle: verify" not in r.out
    assert "load " not in (box.tmp / "calls.log").read_text(encoding="utf-8")


def test_a_refused_answers_file_leaves_the_deploy_folder_as_it_was(tmp_path: Path) -> None:
    """Review (#1660, 5): the read-only preflight runs before the answers' own files are looked at: a refusal there
    ends the run with nothing of the answers' written or asked."""
    box = Box(tmp_path / "prod", env=PROD_SITE + f"TB_SOURCE_DIR={tmp_path}\n")
    before = sorted(str(p.relative_to(box.deploy)) for p in box.deploy.rglob("*"))
    r = box.install("--mode", "stub", "--yes", force=("preflight-answers",), env={"TB_BOX_DEFER_SEAL": "1", **PLANTED})
    assert r.rc == 1 and r.err.splitlines()[-1].startswith("the answers are refused"), r.text[-3000:]
    assert "tools.answers_files" not in (box.tmp / "calls.log").read_text(encoding="utf-8")
    after = sorted(str(p.relative_to(box.deploy)) for p in box.deploy.rglob("*"))
    assert [p for p in after if p not in before and not p.startswith("site/poc-stops")] == [], after


def test_a_production_backup_route_that_cannot_alert_installs_the_schedule_on_the_health_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review (#1660, 1): a bad TB_BACKUP_ALERT_ROUTE on PRODUCTION never leaves the box without backups: the health
    page is written to deploy/.env, said, and the schedule installed (backup-install exits 0)."""
    from tools.backup_drill import DEPLOY

    for k in ("TB_ENV", "TB_BACKUP_ALERT_CMD", "TB_BACKUP_MAILTO", "TB_BACKUP_ALERT_ROUTE", "TB_BACKUP_TARGETS",
              "TB_PG_ARCHIVE_MODE"):  # fmt: skip
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TB_COMPOSE", "false")
    monkeypatch.setenv("TB_SYSTEMD", "0")
    deploy = tmp_path / "opt" / "tb" / "deploy"
    (deploy / "backup").mkdir(parents=True)
    (deploy / "backup" / "trialbox-backup.cron").write_text(
        (DEPLOY / "backup" / "trialbox-backup.cron").read_text(encoding="utf-8"), encoding="utf-8"
    )
    # a route value that must never reach the log; put together, so that no credential URL stands in the file as one text
    given = "smtp://" + "it-login:s3cret" + "@mail.hospital.example"
    (deploy / ".env").write_text(f"TB_ENV=PRODUCTION\nTB_PG_ARCHIVE_MODE=off\nTB_BACKUP_ALERT_ROUTE={given}\n")
    with pytest.raises(ValueError, match=re.escape(f"TB_BACKUP_ALERT_ROUTE={given!r}")):  # install_cron alone
        backup_schedule.install_cron(backup_schedule.config(deploy, {"TB_ENV": "PRODUCTION",
                                                                     "TB_BACKUP_ALERT_ROUTE": given}),
                                     tmp_path / "c", deploy.parent, has_mta=False)  # fmt: skip
    cron = tmp_path / "cron.d"
    assert backup_schedule.main_install(deploy, cron, first=False) == 0
    out = capsys.readouterr().out
    assert any(ln.startswith(backup_schedule.ROUTE_DEFAULTED + " (the route given cannot carry alerts)")
               and "TB_BACKUP_ALERT_ROUTE=health-page" in ln for ln in out.splitlines()), out  # fmt: skip
    assert given not in out and "s3cret" not in out and "it-login" not in out  # never the value given
    assert (cron / backup_schedule.CRON_NAME).is_file()
    env = (deploy / ".env").read_text(encoding="utf-8").splitlines()
    assert "TB_BACKUP_ALERT_ROUTE=health-page" in env and f"TB_BACKUP_ALERT_ROUTE={given}" not in env
    nightly = backup_schedule.config(deploy, update._env_file(deploy / ".env"), process_env=False)
    assert nightly.setting_errors == [] and nightly.alert_page  # the nightly run reads no bad setting: backups run


def test_a_production_install_with_good_answers_goes_on(tmp_path: Path) -> None:
    box = Box(tmp_path / "prod", env=PROD_SITE + f"TB_SOURCE_DIR={tmp_path}\n")
    r = box.install("--mode", "stub", "--yes", env={"TB_BOX_DEFER_SEAL": "1", **PLANTED})
    assert "preflight: the answers, read before the load" in r.out and RUNNING in r.out, r.text[-3000:]
    assert r.out.index("preflight: the answers") < r.out.index("bundle: verify")


def test_a_poc_install_has_no_preflight(tmp_path: Path) -> None:
    r = Box(tmp_path / "b").install("--environment", "TEST", "--mode", "stub", "--yes", force=("preflight-answers",))
    assert r.rc == 0 and "preflight: the answers" not in r.out, r.text[-3000:]


def test_the_health_page_answers_who_is_told() -> None:
    """REAL2 M-17: TB_BACKUP_ALERT_ROUTE=health-page answers the readiness item backup_alarm."""
    need = next(n for n in site_needs.NEEDS if n.key == "backup_alarm")
    assert site_needs.state(need, env={"TB_BACKUP_ALERT_ROUTE": "health-page"}) == "given"
    assert site_needs.state(need, env={}) == "missing"


def test_an_unnamed_watcher_is_a_warning_on_production() -> None:
    """TOL-1 T-I168, T-I169: the wizard warns, naming who is told meanwhile; it no longer refuses."""
    errors: list[str] = []
    warnings: list[str] = []
    settings_wizard.watcher_problem({"TB_BACKUP_ALERT_ROUTE": "health-page"}, True, errors, warnings)
    assert errors == [] and len(warnings) == 1 and "the first administrator is told there meanwhile" in warnings[0]


def test_production_with_no_alert_route_takes_the_health_page(tmp_path: Path) -> None:
    """TOL-1 T-I144: the schedule installs (backups run) with the health page as the route, and says so."""
    cfg = backup_schedule.config(tmp_path, {"TB_ENV": "PRODUCTION"}, process_env=False)
    assert cfg.alert_route and cfg.alert_defaulted
    notes = backup_schedule._route_notes(cfg, has_mta=False)
    assert any(n.startswith("warning: no backup alert route was given") and "TB_BACKUP_ALERT_WATCHER" in n
               for n in notes), notes  # fmt: skip
    # the harm the old refusal guarded, planted: a backup that failed (none good) on such a box is an alert in the
    # backup status, which the /admin health tab shows (the page route: nobody is mailed)
    target = tmp_path / "target"
    target.mkdir()
    failed = backup_schedule.config(
        tmp_path, {"TB_ENV": "PRODUCTION", "TB_BACKUP_TARGETS": str(target)}, process_env=False
    )
    st = backup_schedule.status(failed)
    assert st["level"] == "alert" and st["problems"] and st["age_hours"] is None, st  # no good backup: an alert
    assert failed.alert_defaulted and failed.page_only(has_mta=False)
    given = backup_schedule.config(tmp_path, {"TB_ENV": "PRODUCTION", "TB_BACKUP_ALERT_CMD": "true"}, process_env=False)
    assert not given.alert_defaulted
    poc = backup_schedule.config(tmp_path, {"TB_ENV": "TEST"}, process_env=False)
    assert not poc.alert_route and not poc.alert_defaulted
