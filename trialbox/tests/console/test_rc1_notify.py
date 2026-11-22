"""R22-34 (D-1072; the integrator's go 7082962352 and 7084254835): on a refused box the morning mails carry no
candidate rows. The N1 investigator's mail and the N2 coordinator's mail are built in ``console.notify`` from the
week's list; the mail gateway cannot tell them from the health mail (both are notices without a job, tagged
aggregate), so the refusal is asked where the rows are put in: as for a paused study, the list is left out and the
enrolled participants' care stays."""

from __future__ import annotations

import pytest
from console import notify
from console.sitestore import NotifyPerson, SiteStore

from tests.console.test_study_state_d386 import MONDAY, _helpers


def _store() -> SiteStore:
    store = SiteStore()
    store.save_notify_person(NotifyPerson("pi", None, lang="en"))
    store.save_notify_person(NotifyPerson("crc", None, lang="en"))
    return store


@pytest.mark.parametrize("env", ["PRODUCTION", None, "STAGING"])
def test_a_refused_box_mails_no_candidate_rows(env: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    if env is None:
        monkeypatch.delenv("TB_ENV", raising=False)  # unset is PRODUCTION (D-127)
    else:
        monkeypatch.setenv("TB_ENV", env)
    assert notify.collect(_helpers(_store()), MONDAY) == []


def test_a_refused_box_still_mails_the_participants_care(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    h = _helpers(_store(), life={"today": [], "week": [], "overdue": [], "reports": [], "sae": 1})
    n1 = notify.collect(h, MONDAY, ("N1",))
    assert len(n1) == 1 and n1[0].counts == {"today": 0, "week": 0, "sae": 1}
    assert "11111111" not in n1[0].body and "22222222" not in n1[0].body


@pytest.mark.parametrize("env", ["VALIDATION", "TEST", "DEV"])
def test_an_allowed_box_mails_its_rows(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_ENV", env)
    sent = notify.collect(_helpers(_store()), MONDAY)
    assert {n.kind for n in sent} == {"N1", "N2"}
    assert any("11111111" in n.body for n in sent if n.kind == "N1")
