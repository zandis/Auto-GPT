"""NEW-LIFE-7 (D-764, the deep review's LIFE-007): a serious adverse event is told at once, and every day.

Nobody was told when an SAE was entered unless the optional office mailbox was set, and the investigator's mail went
on working days only: an SAE typed on Friday 18:00 has its 24-hour sponsor report due Saturday 18:00, and the PI's
first mail was Monday 07:00 (Japan goes live after Golden Week). Now:

* a new SAE case is mailed at once to the study's PI as well as the office mailbox (pseudonymous: the screening
  number, the dates and the due times, never the AE term);
* the investigator's unacknowledged-SAE mail and the coordinator's overdue-report mail go every day, weekends too
  (on a weekend day the coordinator's digest carries only the SAE reports);
* on a box that is not DEV or TEST, a study whose type reports SAEs does not open while the office mailbox is
  unset (a required answer, not an option).

Synthetic data only."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from console import notify
from console.auth import User
from console.sitestore import NotifyPerson

from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name
from tests.console.test_sae_d277 import FATAL

PI = User("pi", "investigator", "pi@hospa.test")
CRC = User("crc", "coordinator", "crc1@hospa.test")
SATURDAY = date(2026, 11, 7)
SUNDAY = date(2026, 11, 8)


# ---------------------------------------------------------------------------------------------- every day
@pytest.mark.parametrize("day", [SATURDAY, SUNDAY])
def test_the_investigators_sae_mail_goes_on_a_weekend_day(day: date) -> None:
    n = notify.build_n1(PI, NotifyPerson("pi", "P1", lang="en"), day, [("GZQO", [])], {"GZQO": {"sae": 1}})
    assert n is not None and n.to == "pi@hospa.test"


def test_the_coordinators_overdue_report_mail_goes_on_a_weekend_day_and_only_it() -> None:
    life = {"GZQO": {"reports": [{"short": "aaaaaaaa", "due": "2026-11-07", "party": "sponsor"}],
                     "today": [{"short": "bbbbbbbb", "visit": "V2", "start": "2026-11-07", "end": "2026-11-09",
                                "due": "2026-11-07"}]}}  # fmt: skip
    person = NotifyPerson("crc", None, lang="en")
    n = notify.build_n2(CRC, person, SATURDAY, [("GZQO", [], {})], None, life)
    assert n is not None and n.counts.get("sae_reports") == 1
    assert "aaaaaaaa" in n.body and "bbbbbbbb" not in n.body  # the weekend digest is the SAE reports only
    assert (
        notify.build_n2(CRC, person, SATURDAY, [("GZQO", [], {})], None, {"GZQO": {"today": life["GZQO"]["today"]}})
        is None
    )


# ---------------------------------------------------------------------------------------------- at once
def _new_case(lb: dict[str, Any]) -> list[tuple[str, list[str], str, str]]:  # noqa: F811
    name_pi(lb, "pi")
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    lb["clock"]["now"] = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)  # Friday 18:00 in Taipei
    c.post("/studies/GZQO/setup/sae", data={"csrf": csrf, "rule_set": "tw_trial"}, follow_redirects=True)
    lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "ae1", "values": FATAL, "by": "rc:read"})
    assert c.post("/studies/GZQO/sae/sync", data={"csrf": csrf}).status_code in (200, 303)
    return list(lb["backend"].notices)


def test_a_new_case_is_mailed_at_once_to_the_pi_and_the_office(
    lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: F811
    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "trial-office@hospa.test")
    sent = _new_case(lb)
    assert len(sent) == 1
    _kind, to, subject, body = sent[0]
    assert sorted(to) == ["pi@hospa.test", "trial-office@hospa.test"]
    assert "Myocardial" not in subject + body and "due" in body  # the due times, never the AE term


def test_without_an_office_mailbox_the_pi_is_still_told(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.delenv("TB_SAE_OFFICE_MAILBOX", raising=False)
    sent = _new_case(lb)
    assert [n[1] for n in sent] == [["pi@hospa.test"]]


# ---------------------------------------------------------------------------------------------- a required answer
def test_a_study_that_reports_saes_does_not_open_on_a_box_without_the_office_mailbox(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from console import study_setup

    monkeypatch.delenv("TB_SAE_OFFICE_MAILBOX", raising=False)
    name_pi(lb, "pi")
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/setup/sae", data={"csrf": csrf, "rule_set": "tw_trial"}, follow_redirects=True)
    c.post("/studies/GZQO/state", data={"csrf": csrf, "state": "paused", "reason": "set-up"}, follow_redirects=False)
    monkeypatch.setattr(study_setup, "environment_name", lambda _env: "PRODUCTION")
    page = c.get("/studies/GZQO/state").text
    from tests.console.test_role_pages import _csrf

    r = c.post("/studies/GZQO/state", data={"csrf": _csrf(page), "state": "open"}, follow_redirects=False)
    assert r.status_code == 409 and 'data-testid="state-error"' in r.text
    monkeypatch.setenv("TB_SAE_OFFICE_MAILBOX", "trial-office@hospa.test")
    r = c.post("/studies/GZQO/state", data={"csrf": _csrf(page), "state": "open"}, follow_redirects=False)
    assert r.status_code == 303
