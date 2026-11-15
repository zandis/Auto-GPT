"""T-730c (D-735): on a box with no mail, the site may choose the /admin health tab as the backup alert route.

D-274 refused a PRODUCTION install without ``TB_BACKUP_ALERT_CMD`` or ``TB_BACKUP_MAILTO`` and a mail relay: a box
with no mail could not be installed. ``TB_BACKUP_ALERT_ROUTE=health-page`` is the site's written choice that the
health tab (red backup tile) and the audit carry the alert: install goes on and says nobody is mailed; status is not
red for a missing route; ``doctor`` WARNs in PRODUCTION so the choice stays in sight. Any other value is a setting
error, never a silent route. Unset, everything is as D-274 decided."""

from __future__ import annotations

import json
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


@pytest.mark.parametrize("value", ["health", "page", "yes", "on", "healthpage"])
def test_any_other_value_is_a_setting_error_and_no_route(tmp_path: Path, value: str) -> None:
    cfg = bs.config(_deploy(tmp_path), {**PROD, "TB_BACKUP_ALERT_ROUTE": value})
    assert not cfg.alert_route and not cfg.alert_page
    assert any("TB_BACKUP_ALERT_ROUTE" in e for e in cfg.setting_errors)


def test_status_is_not_red_for_a_missing_route_when_the_page_is_chosen(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    assert any("no alert route" in p for p in bs.status(bs.config(deploy, PROD))["problems"])
    assert not any("alert route" in p for p in bs.status(bs.config(deploy, PAGE))["problems"])


def test_the_page_does_not_replace_a_mail_route_already_there(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    cfg = bs.config(deploy, {**PAGE, "TB_BACKUP_ALERT_CMD": "/usr/local/bin/tb-mail"})
    assert cfg.alert_route and bs.send_cmd(cfg.alert_cmd) is not None and cfg.page_only(has_mta=False) is False
    mail = bs.config(deploy, {**PAGE, "TB_BACKUP_MAILTO": "owner@hospital.example"})
    assert mail.page_only(has_mta=True) is False and mail.page_only(has_mta=False) is True


def test_a_box_with_the_owner_s_mail_but_no_mail_agent_installs_on_the_page(tmp_path: Path) -> None:
    """Review FIX FIRST 1: a box's settings always name the owner's address (tools/box/plan.py); without a mail
    transfer agent the page carries the alert and the install goes on."""
    deploy = _deploy(tmp_path)
    cron = tmp_path / "cron.d"
    cfg = bs.config(deploy, {**PAGE, "TB_BACKUP_MAILTO": "owner@hospital.example"})
    notes = bs.install_cron(cfg, cron, deploy.parent, has_mta=False)
    assert (cron / bs.CRON_NAME).is_file() and 'MAILTO=""' in (cron / bs.CRON_NAME).read_text()
    assert any("nobody is mailed" in n for n in notes) and any("no mail transfer agent" in n for n in notes)
    with pytest.raises(ValueError, match="no mail transfer agent"):  # without the page, as D-274 decided
        bs.install_cron(bs.config(deploy, {**PROD, "TB_BACKUP_MAILTO": "o@h.example"}), cron, deploy.parent,
                        has_mta=False)  # fmt: skip


def test_a_box_plan_writes_the_page_route(tmp_path: Path) -> None:
    from tests.unit.test_box_plan import _hw
    from tools.box import plan as bp

    p = bp.plan(bp.provisional(_hw()), _hw())
    assert p.env_extra["TB_BACKUP_ALERT_ROUTE"] == "health-page" and p.env_extra["TB_BACKUP_MAILTO"]


def test_a_bad_route_value_is_named_where_the_install_stops(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    with pytest.raises(ValueError, match="TB_BACKUP_ALERT_ROUTE='healthpage'"):
        bs.install_cron(bs.config(deploy, {**PROD, "TB_BACKUP_ALERT_ROUTE": "healthpage"}), tmp_path / "c",
                        deploy.parent, has_mta=False)  # fmt: skip


def test_the_health_facts_ask_the_archiver_so_the_tile_shows_archiving_problems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review FIX FIRST 2: archiving problems reached only the hourly mail; on a page-only box the tile carries them."""
    from tools.trialbox import ops

    deploy = _deploy(tmp_path)
    seen: dict[str, object] = {}
    monkeypatch.setattr(bs.ComposeOps, "__init__", lambda self, d, run=None: None)
    monkeypatch.setattr(bs.ComposeOps, "archiver", lambda self: {"failing": True, "error": "archive_command failed"})
    real = bs.status

    def spy(cfg: bs.Config, **kw: object) -> dict[str, object]:
        seen.update(kw)
        return real(cfg, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(bs, "status", spy)
    env = {**PAGE, "TB_PG_ARCHIVE_MODE": "on"}
    ops.health_facts(ops.Box("compose", deploy, env))
    assert seen.get("archiver") == {"failing": True, "error": "archive_command failed"}
    seen.clear()
    ops.health_facts(ops.Box("local", deploy, env))  # the in-process box has no compose to ask
    assert seen.get("archiver") is None


def test_doctor_warns_in_production_when_the_page_is_the_only_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A box that is otherwise well (an off-box share, the cron file, a good backup two hours old, archiving on):
    the page as the only route is the one WARN."""
    from datetime import UTC, datetime, timedelta

    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    (deploy / ".env").write_text("")
    cron = tmp_path / "cron.d"
    cron.mkdir()
    (cron / bs.CRON_NAME).write_text("# installed\n")
    nas = tmp_path / "nas"
    nas.mkdir()
    (nas / bs.OFFBOX_MARKER).write_text("")
    at = datetime.now(UTC) - timedelta(hours=2)
    f = nas / f"trialbox-CGMH-{at.strftime('%Y%m%dT%H%M%SZ')}.tbbak"
    f.write_bytes(b"x")
    bs.sidecar(f).write_text(f"{'a' * 64}  {f.name}\n")
    (deploy / "site" / "backup-last.json").write_text(json.dumps({"ok": True, "good_at": at.isoformat(),
        "good_file": {"name": f.name, "bytes": 1, "sha256": "a" * 64}}))  # fmt: skip
    env = {**PAGE, "TB_PG_ARCHIVE_MODE": "on", "TB_BACKUP_TARGETS": str(nas), "TB_BACKUP_OFFBOX": str(nas)}
    monkeypatch.setattr(bs, "has_mta", lambda: False)
    inp = doctor.DoctorInputs(env=env, deploy=deploy, cron_dir=cron, host_tz="Asia/Taipei")
    c = next(x for x in doctor.run(inp, (doctor.check_backup,)) if x.name == "backup")
    assert c.status == "WARN" and "the only backup alert route is the health page" in c.detail, c
    monkeypatch.setattr(bs, "has_mta", lambda: True)
    mailed = {**env, "TB_BACKUP_MAILTO": "owner@hospital.example"}
    inp = doctor.DoctorInputs(env=mailed, deploy=deploy, cron_dir=cron, host_tz="Asia/Taipei")
    assert next(x for x in doctor.run(inp, (doctor.check_backup,)) if x.name == "backup").status == "PASS"
