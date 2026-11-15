"""BOX-MAIL-ID (D-825), the owner's blocker 9 of 2026-11-15: a box made by the wizard can have a mail identity.

The mail gateway trusts an Authentication-Results header only from the hospital MTA it names
(``TB_MAIL_AUTHSERV_ID``, D-369, SEC-11): empty, every mailed FEAS or SCREEN is refused (fails closed). A box's plan
wrote it empty, always. The owner's answers now take the MTA's authserv-id (optional, one host name); the plan hands
it to the settings wizard, which writes ``TB_MAIL_AUTHSERV_ID``. Left empty, mail stays closed and ``doctor`` says
so (``mail_auth``, WARN on a site box)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tb_common import box_answers as ba

from tests.unit.test_box_plan import _hw
from tools import settings_wizard as sw
from tools.box import plan as bp
from tools.trialbox import doctor

pytestmark = pytest.mark.nodb


def _raw(**over: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {"site_name": "Hospital A", "tz": "Asia/Taipei", "language": "en",
                           "owner": {"full_name": "Owner", "username": "owner", "email": "owner@hospa.test"},
                           "box_name": "box1", "backup": {"kind": "later"}, "source": "later"}  # fmt: skip
    raw.update(over)
    return raw


def test_the_answer_reaches_the_mail_gateway_setting(tmp_path: Path) -> None:
    a, problems = ba.parse(_raw(mta_authserv_id="MX.Hospa.test"))
    assert problems == [] and a is not None and a.mta_authserv_id == "mx.hospa.test"
    p = bp.plan(a, _hw())
    assert p.wizard_answers["mta_authserv_id"] == "mx.hospa.test"
    for rel, text in p.files.items():  # the box's site files, as box-install writes them under deploy/
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    _, env, _ = sw.build(p.wizard_answers, [tmp_path / "site" / "mapping"])
    assert env["TB_MAIL_AUTHSERV_ID"] == "mx.hospa.test"


def test_unanswered_stays_closed() -> None:
    a, _ = ba.parse(_raw())
    assert a is not None and a.mta_authserv_id == "" and bp.plan(a, _hw()).wizard_answers["mta_authserv_id"] == ""


@pytest.mark.parametrize(
    "bad", ["mx hospa", "mx.hospa.test;", "*.hospa.test", "mx..hospa", "http://mx.hospa.test", "-mx.t"]
)
def test_anything_but_one_host_name_is_a_problem_of_the_form(bad: str) -> None:
    a, problems = ba.parse(_raw(mta_authserv_id=bad))
    assert a is None and [(p.field, p.code) for p in problems] == [("mta_authserv_id", "mta_authserv_id")]


@pytest.mark.parametrize(("env", "status"), [("PRODUCTION", "WARN"), ("VALIDATION", "WARN"), ("DEV", "PASS")])
def test_doctor_says_when_mail_is_closed(env: str, status: str) -> None:
    def one(e: dict[str, str]) -> doctor.Check:
        return next(c for c in doctor.run(doctor.DoctorInputs(env=e, host_tz="Asia/Taipei"), (doctor.check_mail_auth,))
                    if c.name == "mail_auth")  # fmt: skip

    c = one({"TB_ENV": env})
    assert c.status == status
    if status == "WARN":
        assert "TB_MAIL_AUTHSERV_ID" in c.detail and "refused" in c.detail
    assert one({"TB_ENV": env, "TB_MAIL_AUTHSERV_ID": "mx.hospa.test"}).status == "PASS"
    assert doctor.check_mail_auth in doctor.CHECKS
