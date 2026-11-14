"""NEW-JRN-6 (D-771, the deep review's JRN-006): the privacy office answers "who saw my record" from a chart number.

A patient asks who saw their record and gives a chart number. The one-patient audit report took a 32-character
pseudonym only ("Chart numbers are not searched here"), and by design no page gives the privacy office a pseudonym
back: APPI 開示 and PDPA 查詢 requests could not be answered from the console. Now the audit browser takes a chart
number: the box turns it into the pseudonym at the door (as the opt-out door does: capped per person and hour, its own
audit event ``console.chart_lookup`` with ``for: disclosure``) and shows that patient's report without the pseudonym
anywhere on the page. Synthetic data only."""

from __future__ import annotations

import json
from typing import Any

import pytest
from console.backend import Unavailable

from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf, _user

B = "b" * 32  # the pseudonym the box gives for the synthetic chart number


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted(b["backend"].audit_dir.glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text().splitlines() if x and json.loads(x).get("event") == name]
    return out


@pytest.fixture
def door(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:  # noqa: F811
    def study_api(method: str, path: str, body: dict[str, Any] | None = None, **_: Any) -> Any:
        if path == "/setup/pseudonym":
            return {"pid": B, "known": True}
        raise Unavailable("no study store in this test")

    monkeypatch.setattr(box["backend"], "study_api", study_api, raising=False)
    box["app"].state.helpers.au.append("console.reveal", actor="console:crc", detail={"pid": B, "purpose": "contact"})
    return box


def test_the_privacy_office_gets_the_report_for_a_chart_number_without_the_pseudonym(door: dict[str, Any]) -> None:
    dpo = _user(door, "dpo1", "privacy")
    page = dpo.get("/audit").text
    assert 'data-testid="audit-by-chart"' in page
    r = dpo.post("/audit/patients/by-chart", data={"csrf": _csrf(page), "chart_no": "SYN-0001"})
    assert r.status_code == 200, r.text[-300:]
    assert 'data-testid="audit-report-by-chart"' in r.text, r.text[r.text.find("<main") :][:1500]
    assert "crc" in r.text[r.text.find('data-testid="audit-report-by-chart"') :]  # who saw the record
    assert B not in r.text and B[:8] not in r.text  # the pseudonym is never shown
    lookups = _events(door, "console.chart_lookup")
    assert lookups and lookups[-1]["detail"]["for"] == "disclosure" and lookups[-1]["detail"]["pid"] == B


def test_a_reader_without_the_audit_right_is_refused_and_lookups_are_capped(door: dict[str, Any]) -> None:
    crc = _user(door, "crc5", "coordinator")
    assert crc.post("/audit/patients/by-chart", data={"csrf": _csrf(crc.get("/home").text), "chart_no": "X1"},
                    follow_redirects=False).status_code == 403  # fmt: skip
    dpo = _user(door, "dpo2", "privacy")
    csrf = _csrf(dpo.get("/audit").text)
    codes = [dpo.post("/audit/patients/by-chart", data={"csrf": csrf, "chart_no": f"SYN-{i:04d}"}).status_code
             for i in range(31)]  # fmt: skip
    assert codes[:30] == [200] * 30 and codes[30] == 429  # the opt-out door's cap, per person and hour


def test_the_api_twin_gives_the_events_without_the_pseudonym(door: dict[str, Any]) -> None:
    from fastapi.testclient import TestClient

    from tests.console.test_role_pages import PW

    _user(door, "dpo3", "privacy")
    api = TestClient(door["app"])
    tok = api.post("/api/v1/session", json={"username": "dpo3", "password": PW}).json()["token"]
    r = api.post("/api/v1/audit/patients/by-chart", json={"chart_no": "SYN-0001"},
                 headers={"Authorization": f"Bearer {tok}"})  # fmt: skip
    assert r.status_code == 200, r.text[:300]
    assert any(e["event"] == "console.reveal" for e in r.json()["events"]) and B not in r.text and B[:8] not in r.text
