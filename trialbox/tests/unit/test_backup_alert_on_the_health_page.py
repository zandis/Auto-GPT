"""T-730c (D-735): on a box with no mail, the site may choose the /admin health tab as the backup alert route.

D-274 refused a PRODUCTION install without ``TB_BACKUP_ALERT_CMD`` or ``TB_BACKUP_MAILTO`` and a mail relay: a box
with no mail could not be installed. ``TB_BACKUP_ALERT_ROUTE=health-page`` is the site's written choice that the
health tab (red backup tile) and the audit carry the alert: install goes on and says nobody is mailed; status is not
red for a missing route; ``doctor`` WARNs in PRODUCTION so the choice stays in sight. Any other value is a setting
error, never a silent route. Unset, everything is as D-274 decided."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.backup_drill import DEPLOY
from tools.trialbox import backup_schedule as bs
from tools.trialbox import doctor

pytestmark = pytest.mark.nodb

PROD = {"TB_ENV": "PRODUCTION"}
PAGE = {**PROD, "TB_BACKUP_ALERT_ROUTE": "health-page"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("TB_ENV", "TB_BACKUP_ALERT_CMD", "TB_BACKUP_MAILTO", "TB_BACKUP_ALERT_ROUTE", "TB_BACKUP_TARGETS",
              "TB_BACKUP_OFFBOX", "TB_PG_ARCHIVE_MODE"):  # fmt: skip
        monkeypatch.delenv(k, raising=False)


def _deploy(tmp_path: Path) -> Path:
    deploy = tmp_path / "opt" / "tb" / "deploy"
    (deploy / "backup").mkdir(parents=True)
    (deploy / "backup" / "trialbox-backup.cron").write_text(
        (DEPLOY / "backup" / "trialbox-backup.cron").read_text(encoding="utf-8")
    )
    (deploy / ".env").write_text("TB_ENV=PRODUCTION\n")
    return deploy


def test_production_without_mail_installs_when_the_site_chose_the_health_page(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    cron = tmp_path / "cron.d"
    notes = bs.install_cron(bs.config(deploy, PAGE), cron, deploy.parent, has_mta=False)
    assert (cron / bs.CRON_NAME).is_file() and 'MAILTO=""' in (cron / bs.CRON_NAME).read_text()
    assert any("health" in n and "nobody is mailed" in n for n in notes), notes


def test_unset_production_still_refuses_as_d274_decided(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    with pytest.raises(ValueError, match="PRODUCTION needs a backup alert route"):
        bs.install_cron(bs.config(deploy, PROD), tmp_path / "cron.d", deploy.parent, has_mta=False)
    assert "TB_BACKUP_ALERT_ROUTE=health-page" in bs.ROUTE_HINT


@pytest.mark.parametrize("value", ["health", "page", "yes", "on", "HEALTH-PAGE "])
def test_any_other_value_is_a_setting_error_and_no_route(tmp_path: Path, value: str) -> None:
    cfg = bs.config(_deploy(tmp_path), {**PROD, "TB_BACKUP_ALERT_ROUTE": value})
    if value.strip().lower() == "health-page":
        assert cfg.alert_page and not cfg.setting_errors
        return
    assert not cfg.alert_route and not cfg.alert_page
    assert any("TB_BACKUP_ALERT_ROUTE" in e for e in cfg.setting_errors)


def test_status_is_not_red_for_a_missing_route_when_the_page_is_chosen(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    assert any("no alert route" in p for p in bs.status(bs.config(deploy, PROD))["problems"])
    assert not any("alert route" in p for p in bs.status(bs.config(deploy, PAGE))["problems"])


def test_the_page_does_not_replace_a_mail_route_already_there(tmp_path: Path) -> None:
    cfg = bs.config(_deploy(tmp_path), {**PAGE, "TB_BACKUP_ALERT_CMD": "/usr/local/bin/tb-mail"})
    assert cfg.alert_route and bs.send_cmd(cfg.alert_cmd) is not None and cfg.page_only is False


def test_doctor_warns_in_production_when_the_page_is_the_only_route(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("")
    cron = tmp_path / "cron.d"
    cron.mkdir()
    (cron / bs.CRON_NAME).write_text("# installed\n")
    env = {**PAGE, "TB_PG_ARCHIVE_MODE": "on"}
    inp = doctor.DoctorInputs(env=env, deploy=deploy, cron_dir=cron, host_tz="Asia/Taipei")
    c = next(x for x in doctor.run(inp, (doctor.check_backup,)) if x.name == "backup")
    assert c.status != "PASS" and "the only backup alert route is the health page" in c.detail
    assert "no alert route" not in c.detail
