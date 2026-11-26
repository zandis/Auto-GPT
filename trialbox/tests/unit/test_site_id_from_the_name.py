"""A box installed by the four questions runs on the marked stand-in name, so its site id was the stand-in's cut to 24
characters (``TRIALBOX-SITE-NAME-NEEDE``), and it stayed so when the hospital's name was given on "Information still
needed". The id is derived from the first name given: ``deploy/.env`` and ``settings.yaml`` both take it, and a later
name changes the display name only. Synthetic values only."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from tb_common import box_answers as ba

from tests.unit.test_install_m1 import TYPED, _build, _hw, _prompt
from tools import settings_wizard
from tools.box import __main__ as box
from tools.box import ask, needs_apply
from tools.box import plan as bp
from tools.trialbox import finish_check as fc


@pytest.mark.nodb
def test_the_site_id_is_the_given_hospital_name_s_never_the_stand_in_s(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    a, _ = box.owner_answers({**ask.four(_hw(), _prompt(TYPED), env={}), "environment": "VALIDATION"}, ())
    assert a.site_name == ba.PLACEHOLDER_NAME
    settings, env, _ = _build(bp.plan(a, _hw()), deploy)
    box.keep_answers(deploy, a)
    settings_wizard.write(settings, env, deploy / "settings.yaml", deploy / ".env")
    assert fc.read_env(deploy / ".env")["TB_SITE_ID"] == "TRIALBOX-SITE-NAME-NEEDE"  # the stand-in's, until given

    needs_apply.run(deploy, {"item": "site_name", "site_name": "Hospital A (synthetic)"}, restart=False)
    site = yaml.safe_load((deploy / "settings.yaml").read_text(encoding="utf-8"))["site"]
    assert fc.read_env(deploy / ".env")["TB_SITE_ID"] == site["id"] == "HOSPITAL-A-SYNTHETIC"
    assert site["name"] == "Hospital A (synthetic)"


def _stand_in_box(tmp_path: Path) -> Path:
    deploy = tmp_path / "deploy"
    a, _ = box.owner_answers({**ask.four(_hw(), _prompt(TYPED), env={}), "environment": "VALIDATION"}, ())
    settings, env, _ = _build(bp.plan(a, _hw()), deploy)
    box.keep_answers(deploy, a)
    settings_wizard.write(settings, env, deploy / "settings.yaml", deploy / ".env")
    return deploy


def _doctor(deploy: Path) -> dict[str, tuple[str, str]]:
    settings = yaml.safe_load((deploy / "settings.yaml").read_text(encoding="utf-8"))
    return {k: (s, t) for k, s, t in needs_apply.doctor_checks(deploy, fc.read_env(deploy / ".env"), settings)}


@pytest.mark.nodb
def test_go_live_is_refused_and_doctor_warns_until_the_name_is_given(tmp_path: Path) -> None:
    from tools import acceptance as acc

    assert bp.site_id(ba.PLACEHOLDER_NAME) == ba.PLACEHOLDER_SITE_ID
    deploy = _stand_in_box(tmp_path)
    body = acc.check_site_name(deploy)
    assert body["passed"] is False and "site name not set" in body["summary"], body
    status, said = _doctor(deploy)["site_id"]
    assert status == "WARN" and "site name not set" in said, said
    assert acc.check_site_name(tmp_path / "nowhere")["passed"] is False  # no .env: fails closed

    needs_apply.run(deploy, {"item": "site_name", "site_name": "Hospital A (synthetic)"}, restart=False)
    assert acc.check_site_name(deploy) == {"passed": True, "summary": "site id HOSPITAL-A-SYNTHETIC"}
    assert "site_id" not in _doctor(deploy)


@pytest.mark.nodb
def test_a_later_name_changes_the_display_name_never_the_site_id(tmp_path: Path) -> None:
    """The id is set once, from the first real name: a renamed hospital keeps the id its backups, reports and audit
    carry, so restore's same-site check still takes them."""
    deploy = _stand_in_box(tmp_path)
    needs_apply.run(deploy, {"item": "site_name", "site_name": "Hospital A (synthetic)"}, restart=False)
    needs_apply.run(deploy, {"item": "site_name", "site_name": "Hospital A East (synthetic)"}, restart=False)
    site = yaml.safe_load((deploy / "settings.yaml").read_text(encoding="utf-8"))["site"]
    assert fc.read_env(deploy / ".env")["TB_SITE_ID"] == site["id"] == "HOSPITAL-A-SYNTHETIC"
    assert site["name"] == "Hospital A East (synthetic)"


def test_a_backup_on_the_stand_in_site_id_is_written_and_doctor_warns(tmp_path: Path, db_url: str) -> None:
    """A box holding data keeps its nightly backup while the name is not given: the backup carries the stand-in id
    (restored with --other-site once the name is given), and doctor says so."""
    from tb_common.db import Database

    from tests import pg_client
    from tools.trialbox import backup as bk

    Database.connect(db_url, "site").migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY)"])
    pub = tmp_path / "backup.pub"
    bk.keygen(tmp_path / "backup.key", pub)
    env = {**pg_client.env(), "TB_DB_URL": db_url, "TB_SITE_ID": ba.PLACEHOLDER_SITE_ID}
    made = bk.backup([tmp_path / "nas"], pub, env=env, dirs={})
    assert [f.name.startswith(f"trialbox-{ba.PLACEHOLDER_SITE_ID}-") for f in made] == [True], made
    status, said = _doctor(_stand_in_box(tmp_path))["site_id"]
    assert status == "WARN" and "site name not set" in said and "--other-site" in said, said
