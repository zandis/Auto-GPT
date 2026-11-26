"""A box installed by the four questions runs on the marked stand-in name, so its site id was the stand-in's cut to 24
characters (``TRIALBOX-SITE-NAME-NEEDE``), and it stayed so when the hospital's name was given on "Information still
needed". The id is derived from the name given: ``deploy/.env`` and ``settings.yaml`` both take it. Synthetic values
only."""

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

pytestmark = pytest.mark.nodb


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


def test_the_first_backup_is_refused_while_the_site_id_is_the_stand_in(tmp_path: Path) -> None:
    from tools.trialbox import backup as bk

    with pytest.raises(bk.BackupError, match="site name not set"):
        bk.backup([tmp_path / "nas"], tmp_path / "backup.pub", env={"TB_SITE_ID": ba.PLACEHOLDER_SITE_ID}, dirs={})
    assert not (tmp_path / "nas").exists()  # refused before anything is written
