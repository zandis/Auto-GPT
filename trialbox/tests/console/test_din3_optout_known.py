"""NEW-DIN-3, the console's half (DIN-003, D-544): the opt-out desk says when a chart number is not a patient of
this box, and registers it anyway only with a written reason; the first-run page asks the chart-number rule, and
only while the box holds no patient."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from adapter.pidmap import PidMap
from console.backend import Unavailable
from fastapi.testclient import TestClient
from tb_common import box_answers, firstrun
from tb_common.optout import OptOutRegister

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture by name
from tests.console.test_d273_privacy_guards import B, _api, _events
from tests.console.test_firstrun import _answers, _with_code
from tests.console.test_firstrun import _box as _first
from tests.console.test_role_pages import PW, _csrf, _user

WHY = "the patient was seen at the affiliated clinic"


def _door(b: dict[str, Any], monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any]) -> TestClient:
    def study_api(method: str, path: str, body: dict[str, Any] | None = None, **_: Any) -> Any:
        if path == "/setup/pseudonym":
            return dict(answer)
        raise Unavailable("no study store in this test")

    monkeypatch.setattr(b["backend"], "study_api", study_api, raising=False)
    if b["users"].get("dpo1") is None:
        return _user(b, "dpo1", "privacy")
    return login(b["app"], "dpo1", PW)[0]


def _post(c: TestClient, **form: str) -> Any:
    return c.post("/site/opt-outs", data={"csrf": _csrf(c.get("/site/opt-outs").text), **form}, follow_redirects=False)


@pytest.mark.parametrize("answer", [{"pid": B, "known": False}, {"pid": B, "known": None}, {"pid": B}])
def test_a_chart_number_the_box_does_not_know_is_not_registered_without_a_reason(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    answer: dict[str, Any],
) -> None:
    """Unknown, cannot say, and an orchestrator that does not answer the question: none of them is "known"."""
    c = _door(box, monkeypatch, answer)
    r = _post(c, chart_no="SYN-0001", lang="en")
    assert r.status_code == 400 and "not a patient of this box" in r.text
    assert B not in r.text and "bbbbbbbb" not in r.text  # the pseudonym is still not given back
    assert OptOutRegister().current() == []
    assert _events(box, "console.opt_out") == []
    look = _events(box, "console.chart_lookup")  # the lookup happened and is on the record, with what the box said
    assert len(look) == 1 and look[0]["detail"]["known"] == ("no" if answer.get("known") is False else "cannot_say")
    api, hdr = _api(box, "dpo1")
    out = api.post("/api/v1/site/opt-outs", json={"chart_no": "SYN-0001"}, headers=hdr)
    assert out.status_code == 400 and B not in out.text
    short = _post(c, chart_no="SYN-0001", unknown_reason="because")
    assert short.status_code == 400 and OptOutRegister().current() == []


def test_with_a_reason_it_is_registered_and_the_record_says_so(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = _door(box, monkeypatch, {"pid": B, "known": False})
    r = _post(c, chart_no="SYN-0001", unknown_reason=WHY)
    assert r.status_code == 303 and r.headers["location"] == "/site/opt-outs?done=added"
    assert [e.pid for e in OptOutRegister().current()] == [B]
    ev = _events(box, "console.opt_out")
    assert len(ev) == 1 and ev[0]["detail"]["known"] == "no" and ev[0]["detail"]["unknown_reason"] == WHY
    api, hdr = _api(box, "dpo1")
    out = api.post("/api/v1/site/opt-outs", json={"chart_no": "SYN-0002", "unknown_reason": WHY}, headers=hdr)
    assert out.status_code == 200 and out.json() == {"opted_out": True, "changed": False}


def test_a_known_patient_needs_no_reason_and_a_lift_is_not_asked(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = _door(box, monkeypatch, {"pid": B, "known": True})
    assert _post(c, chart_no="SYN-0001").status_code == 303
    ev = _events(box, "console.opt_out")
    assert len(ev) == 1 and ev[0]["detail"]["known"] == "yes" and "unknown_reason" not in ev[0]["detail"]
    # the map lost the row since (a rebuilt box): the lift of a registered opt-out is still possible by chart number
    c = _door(box, monkeypatch, {"pid": B, "known": False})
    r = _post(c, chart_no="SYN-0001", lift="1", note="registered by mistake, the patient agreed")
    assert r.status_code == 303 and OptOutRegister().current() == []


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_desk_says_it_in_each_language(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch, lang: str) -> None:  # noqa: F811
    c = _door(box, monkeypatch, {"pid": B, "known": False})
    c.post("/lang", data={"csrf": _csrf(c.get("/site/opt-outs").text), "lang": lang, "back": "/site/opt-outs"})
    page = c.get("/site/opt-outs").text
    assert 'data-testid="optout-unknown-reason"' in page and f'lang="{lang}"' in page
    r = c.post("/site/opt-outs", data={"csrf": _csrf(page), "chart_no": "SYN-0001"}, follow_redirects=False)
    assert r.status_code == 400
    assert "not a patient of this box" in r.text if lang == "en" else "not a patient of this box" not in r.text


# ------------------------------------------------------------------------------------------- the first-run page
def _patient(db_url: str, tmp_path: Path) -> None:
    pm = PidMap(tmp_path / "pid_map.key", db_url)
    try:
        pm.upsert_many([("c" * 32, "00123456")])  # synthetic
    finally:
        pm.close()


def test_the_first_run_page_asks_the_rule_and_hands_it_to_the_installer(tmp_path: Path) -> None:
    b = _first(tmp_path)
    c = _with_code(b)
    assert 'data-testid="firstrun-chartno"' in c.get("/login/first-run/answers").text
    r, _ = _answers(c, chartno_kind="digits", chartno_width="8")
    assert r.status_code == 200, r.text[-300:]
    assert json.loads((b["folder"] / firstrun.ANSWERS).read_text())["chartno_rule"] == "digits:8"


def test_no_answer_hands_over_no_rule_and_a_rule_that_cannot_be_read_is_shown(tmp_path: Path) -> None:
    b = _first(tmp_path)
    c = _with_code(b)
    r, _ = _answers(c, chartno_kind="digits", chartno_width="0")
    assert r.status_code == 422 and 'data-testid="err-chartno_rule"' in r.text and b["users"].count() == 0
    r, _ = _answers(c, chartno_kind="roman")
    assert r.status_code == 422 and 'data-testid="err-chartno_rule"' in r.text
    r, _ = _answers(c)
    assert r.status_code == 200
    assert json.loads((b["folder"] / firstrun.ANSWERS).read_text())["chartno_rule"] == ""


def test_once_the_box_holds_a_patient_the_question_is_gone_and_an_answer_is_refused(
    tmp_path: Path, db_url: str
) -> None:
    """A box set up again over its data (the accounts gone, the pid map kept): another rule would give every
    patient a second pseudonym (D-579). The page does not ask, and a posted rule makes nothing."""
    b = _first(tmp_path)
    _patient(db_url, tmp_path)
    c = _with_code(b)
    assert 'data-testid="firstrun-chartno"' not in c.get("/login/first-run/answers").text
    r, _ = _answers(c, chartno_kind="digits", chartno_width="8")
    assert r.status_code == 422 and 'data-testid="err-chartno_rule"' in r.text
    assert b["users"].count() == 0 and not (b["folder"] / firstrun.ANSWERS).exists()
    r, _ = _answers(c)
    assert r.status_code == 200
    assert json.loads((b["folder"] / firstrun.ANSWERS).read_text())["chartno_rule"] == ""


def test_a_pid_map_that_cannot_be_asked_counts_as_holding_patients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from console import firstrun as page

    b = _first(tmp_path)
    monkeypatch.setattr(page, "box_holds_patients", lambda: None)
    c = _with_code(b)
    assert 'data-testid="firstrun-chartno"' not in c.get("/login/first-run/answers").text
    r, _ = _answers(c, chartno_kind="hex", chartno_width="10")
    assert r.status_code == 422 and b["users"].count() == 0


@pytest.mark.nodb
def test_the_answers_schema_reads_the_rule_both_ways() -> None:
    base = {"site_name": "Site A (synthetic)", "tz": "Asia/Tokyo", "owner_full_name": "Dr Owner",
            "owner_username": "owner", "owner_email": "owner@hospa.test", "backup_kind": "later"}  # fmt: skip
    a, problems = box_answers.parse({**base, "chartno_rule": "HEX:10:lower"})
    assert a is not None and not problems and a.chartno_rule == "hex:10:lower"
    a, _ = box_answers.parse({**base, "chartno_kind": "asis"})
    assert a is not None and a.chartno_rule == "asis"
    a, _ = box_answers.parse(base)
    assert a is not None and a.chartno_rule == "" and a.to_json()["chartno_rule"] == ""
    _, problems = box_answers.parse({**base, "chartno_rule": "digits:eight"})
    assert [str(p) for p in problems] == ["chartno_rule: chartno_rule"]
    _, problems = box_answers.parse({**base, "chartno_kind": "asis", "chartno_width": "8"})
    assert [str(p) for p in problems] == ["chartno_rule: chartno_rule"]
