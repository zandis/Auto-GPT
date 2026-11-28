"""P-16 (R1+1 batch D): M5's support session (10K-15, decision 99) on the real console. Fixed clocks throughout."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from console import app as console_app
from console import i18n_support, support_page
from fastapi.testclient import TestClient

from tests.console.test_console_app import ADMIN_PW, CRC_PW, login
from tests.console.test_rc1_guard import _console

NOW = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)


def _events(tmp: Path, event: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((tmp / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == event]


def test_the_catalogue_holds_the_same_keys_in_three_languages() -> None:
    assert set(i18n_support.EN) == set(i18n_support.JA) == set(i18n_support.ZH)


def test_the_console_registers_the_support_page_file(tmp_path: Path) -> None:
    paths = {getattr(r, "path", "") for r in _console(tmp_path, "TEST")["app"].routes}
    assert "support_page" in console_app.MODULE_PAGES
    assert support_page.PATH in paths


def test_nobody_but_the_administrator_reads_the_support_page(tmp_path: Path) -> None:
    b = _console(tmp_path, "TEST")
    b["app"].state.rc1_guard.h.users.create("crc9", "coordinator", CRC_PW, "crc9@hospa.test")
    c, csrf = login(b["app"], "crc9", CRC_PW)
    assert c.get(support_page.PATH).status_code == 403
    assert c.post(support_page.PATH, data={"csrf": csrf, "confirm": "1"}).status_code == 403


# ------------------------------------------------------------------------------------------------ the support session
def test_a_support_session_closes_patient_pages_to_every_role_and_audits_start_and_end(tmp_path: Path) -> None:
    b = _console(tmp_path, "TEST")
    h = b["app"].state.rc1_guard.h
    clock = {"now": NOW}
    h.clock = lambda: clock["now"]
    h.users.create("crc9", "coordinator", CRC_PW, "crc9@hospa.test")
    crc, _ = login(b["app"], "crc9", CRC_PW)
    admin, csrf = login(b["app"])
    assert crc.get("/home").status_code == 200
    turn = {"csrf": csrf, "confirm": "1"}
    assert admin.post(support_page.PATH, data={"csrf": csrf}).status_code == 400  # the tick first
    r = admin.post(support_page.PATH, data={**turn, "was": "off"}, follow_redirects=False)
    assert r.status_code == 303
    admin.post(support_page.PATH, data={**turn, "was": "off"})  # the same page pressed twice: nothing more
    refused = crc.get("/home")
    assert refused.status_code == 403 and i18n_support.EN["support.refused"] in refused.text
    patient_file = f"/pilot/jobs/{b['screen'].job_id}/files/candidate_list_GZQO.json"
    assert crc.get(patient_file).status_code == 403
    assert admin.get(patient_file).status_code == 403  # every role, the administrator included
    assert admin.get(support_page.PATH).status_code == 200  # the page that ends it stays open
    assert 'data-testid="sp-on"' in admin.get(support_page.PATH).text
    denied = [e for e in _events(tmp_path, "console.denied") if e["detail"].get("refusal") == "support_session"]
    assert {e["detail"]["action"] for e in denied} >= {"/home"}
    admin.post(support_page.PATH, data={**turn, "was": "on"})
    assert crc.get("/home").status_code == 200
    said = [(e["detail"]["action"], e["detail"].get("how")) for e in _events(tmp_path, support_page.EVENT)]
    assert said == [("started", None), ("ended", "hand")]
    assert len({e["detail"]["session"] for e in _events(tmp_path, support_page.EVENT)}) == 1


def test_a_support_session_ends_by_itself_after_two_hours(tmp_path: Path) -> None:
    b = _console(tmp_path, "TEST")
    h = b["app"].state.rc1_guard.h
    clock = {"now": NOW}
    h.clock = lambda: clock["now"]
    switch = b["app"].state.support_session
    switch.start("console:admin")
    clock["now"] = NOW + support_page.AUTO_END - timedelta(seconds=1)
    assert switch.on()
    clock["now"] = NOW + support_page.AUTO_END
    assert not switch.on() and not switch.on()  # ended once
    said = [(e["detail"]["action"], e["detail"].get("how")) for e in _events(tmp_path, support_page.EVENT)]
    assert said == [("started", None), ("ended", "auto")]


def test_a_stop_between_the_state_and_its_event_keeps_the_pages_closed_and_sends_the_event_later(
    tmp_path: Path,
) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []
    calls = {"n": 0}

    class Audit:
        def append(self, event: str, **kw: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise KeyboardInterrupt  # a signal between the state's first write and the start's event
            sent.append((event, kw["detail"]))

    switch = support_page.SupportSession(tmp_path, Audit(), lambda: NOW)
    with pytest.raises(KeyboardInterrupt):
        switch.start("console:admin")
    assert json.loads((tmp_path / support_page.STATE).read_text())["owed"] is True
    assert switch.on()  # closed, and the owed event is sent now
    assert [(e, d["action"]) for e, d in sent] == [(support_page.EVENT, "started")]
    assert switch.on() and len(sent) == 1
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_a_state_that_cannot_be_read_keeps_the_patient_pages_closed(tmp_path: Path) -> None:
    (tmp_path / support_page.STATE).write_text("{not json")
    switch = support_page.SupportSession(tmp_path, SimpleNamespace(append=lambda *a, **k: None), lambda: NOW)
    assert switch.on()
    switch.end("console:admin")
    assert not switch.on()


def test_the_support_switch_has_an_api_twin(tmp_path: Path) -> None:
    b = _console(tmp_path, "TEST")
    h = b["app"].state.rc1_guard.h
    h.clock = lambda: NOW
    c = TestClient(b["app"], base_url="https://testserver")
    token = c.post("/api/v1/session", json={"username": "admin", "password": ADMIN_PW}).json()["token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert c.post("/api/v1" + support_page.PATH, json={"turn": "maybe"}, headers=auth).status_code == 422
    on = c.post("/api/v1" + support_page.PATH, json={"turn": "on"}, headers=auth).json()
    assert on["on"] is True and on["until"] == (NOW + support_page.AUTO_END).isoformat()
    assert b["app"].state.support_session.on()
    assert c.post("/api/v1" + support_page.PATH, json={"turn": "off"}, headers=auth).json()["on"] is False
    said = [e["detail"]["action"] for e in _events(tmp_path, support_page.EVENT)]
    assert said == ["started", "ended"]
