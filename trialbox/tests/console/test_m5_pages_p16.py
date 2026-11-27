"""P-16 (R1+1 batch D): M5's three page files on the real console: the health page (10K-6), the support session
(10K-15, decision 99) and the data step (10K-16). Fixed clocks throughout."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from console import app as console_app
from console import data_step, health_page, i18n_m5, support_page
from fastapi.testclient import TestClient
from tb_contracts import Job, JobMetrics

from tests.console.test_console_app import ADMIN_PW, CRC_PW, login
from tests.console.test_rc1_guard import _console

NOW = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)


def _rec(event: str, ts: datetime, **detail: Any) -> SimpleNamespace:
    return SimpleNamespace(event=event, ts=ts.isoformat(), detail=detail)


def _job(n: int, state: Any, received: datetime, *, calls: int = 0, wall: float = 0.0) -> Job:
    return Job(job_id=f"01JB{n:022d}", type="SCREEN", ruleset="GZQO", requested_by="t", received_at=received,
               updated_at=received, state=state, metrics=JobMetrics(llm_calls=calls, wall_seconds=wall))  # fmt: skip


def _events(tmp: Path, event: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((tmp / "audit").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [e for e in out if e["event"] == event]


def _api(app: Any, path: str) -> Any:
    c = TestClient(app, base_url="https://testserver")
    token = c.post("/api/v1/session", json={"username": "admin", "password": ADMIN_PW}).json()["token"]
    return c.get(path, headers={"Authorization": f"Bearer {token}"}).json()


def test_the_three_catalogues_hold_the_same_keys() -> None:
    assert set(i18n_m5.EN) == set(i18n_m5.JA) == set(i18n_m5.ZH)


def test_the_console_registers_each_declared_page_file_it_now_has(tmp_path: Path) -> None:
    paths = {getattr(r, "path", "") for r in _console(tmp_path, "TEST")["app"].routes}
    assert {"health_page", "data_step", "support_page"} <= set(console_app.MODULE_PAGES)
    assert {health_page.PATH, data_step.PATH, support_page.PATH} <= paths


# ------------------------------------------------------------------------------------------------ the health page
def _levels(got: list[health_page.Line]) -> dict[str, str]:
    return {f"{x.kind}:{x.values.get('source', '')}": x.level for x in got}


def test_a_feed_that_stopped_is_red_the_next_morning() -> None:
    last_night = [_rec("ingest.done", NOW - timedelta(hours=6), source="ssmix2", counts={"Patient": 3})]
    stopped = [_rec("ingest.done", NOW - timedelta(hours=30), source="ssmix2", counts={"Patient": 3})]
    assert _levels(health_page.night_lines(last_night, NOW))["ingest:ssmix2"] == "ok"
    assert _levels(health_page.night_lines(stopped, NOW))["ingest:ssmix2"] == "red"
    assert [x.kind for x in health_page.night_lines([], NOW)] == ["ingest_none"]


@pytest.mark.parametrize(("event", "level"), [("ingest.done", "ok"), ("ingest.held", "red"), ("ingest.failed", "red")])
def test_rows_in_and_held_turn_red_when_the_night_was_held_or_failed(event: str, level: str) -> None:
    recs = [_rec("ingest.done", NOW - timedelta(hours=30), source="csv", counts={"Patient": 1}),
            _rec(event, NOW - timedelta(hours=6), source="csv", counts={"Patient": 4, "Encounter": 6})]  # fmt: skip
    (rows,) = [x for x in health_page.night_lines(recs, NOW) if x.kind == "rows"]
    assert rows.level == level and rows.values["rows"] == 10


def test_the_oldest_waiting_job_turns_red_after_its_hours() -> None:
    fresh = [_job(1, "running", NOW - timedelta(hours=1)), _job(2, "done", NOW - timedelta(days=3))]
    stale = [*fresh, _job(3, "received", NOW - timedelta(hours=health_page.WAIT_RED_H + 1))]
    assert health_page.jobs_line(fresh, NOW).as_dict() == {"kind": "jobs", "level": "ok", "waiting": 1, "hours": 1.0}
    assert health_page.jobs_line(stale, NOW).level == "red"


def test_the_audit_drain_lag_turns_red_when_nothing_reaches_the_chain() -> None:
    assert health_page.drain_line("file", None, NOW).kind == "drain_file"
    assert health_page.drain_line("db", NOW - timedelta(minutes=2), NOW).level == "ok"
    assert health_page.drain_line("db", NOW - timedelta(minutes=health_page.DRAIN_RED_MIN + 1), NOW).level == "red"
    assert health_page.drain_line("db", None, NOW).level == "red"


def test_model_latency_turns_red_above_its_seconds_per_call() -> None:
    quick = [_job(1, "done", NOW - timedelta(hours=2), calls=100, wall=500.0)]
    slow = [_job(1, "done", NOW - timedelta(hours=2), calls=10, wall=10 * (health_page.CALL_RED_S + 5))]
    old = [_job(1, "done", NOW - timedelta(days=5), calls=10, wall=9999.0)]
    assert health_page.latency_line(quick, NOW).as_dict() == {"kind": "latency", "level": "ok", "seconds": 5.0,
                                                              "calls": 100}  # fmt: skip
    assert health_page.latency_line(slow, NOW).level == "red"
    assert health_page.latency_line(old, NOW).kind == "latency_none"


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_administrator_reads_the_health_page_and_its_twin(tmp_path: Path, lang: str) -> None:
    b = _console(tmp_path, "TEST")
    h = b["app"].state.rc1_guard.h
    h.clock = lambda: NOW
    h.au.append("ingest.done", ts=NOW - timedelta(hours=30), actor="adapter",
                detail={"source": "ssmix2", "counts": {"Patient": 2}})  # fmt: skip
    c, csrf = login(b["app"])
    c.post("/lang", data={"lang": lang, "csrf": csrf})
    page = c.get(health_page.PATH)
    words = {"en": i18n_m5.EN, "ja": i18n_m5.JA, "zh-TW": i18n_m5.ZH}[lang]
    assert page.status_code == 200 and words["healthpage.title"] in page.text
    assert 'data-testid="hp-ingest" data-level="red"' in page.text and "ssmix2" in page.text
    api = _api(b["app"], "/api/v1" + health_page.PATH)
    assert api["level"] == "red" and {"kind": "ingest", "level": "red", "source": "ssmix2", "hours": 30.0,
                                      "at": "2026-11-25T02:00+00:00"} in api["lines"]  # fmt: skip
    (rows,) = [x for x in api["lines"] if x["kind"] == "rows"]  # read through the console's own audit reader
    assert (rows["rows"], rows["state"], rows["level"]) == (2, "in", "ok")


def test_nobody_but_the_administrator_reads_the_three_pages(tmp_path: Path) -> None:
    b = _console(tmp_path, "TEST")
    b["app"].state.rc1_guard.h.users.create("crc9", "coordinator", CRC_PW, "crc9@hospa.test")
    c, csrf = login(b["app"], "crc9", CRC_PW)
    for path in (health_page.PATH, data_step.PATH, support_page.PATH):
        assert c.get(path).status_code == 403, path
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
    assert refused.status_code == 403 and i18n_m5.EN["support.refused"] in refused.text
    assert crc.get(f"/pilot/jobs/{b['screen'].job_id}/files/candidate_list_GZQO.json").status_code == 403
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


# ------------------------------------------------------------------------------------------------ the data step
#: the synthetic Japanese hospital's night, as the adapter's ``ingest.done`` carries it: counts and type names only
NIGHT: dict[str, Any] = {
    "source": "ssmix2",
    "counts": {"Patient": 120, "Encounter": 480, "Condition": 310, "Observation": 2400, "MedicationRequest": 650},
    "site_profile": {
        "id": "synthetic-jp",
        "version": "1.0",
        "types_declared": 6,
        "types_arrived": 5,
        "not_arrived": ["OML-11"],
        "not_read": [],
        "not_declared": ["PPR-01"],
        "unmapped_codes": 4,
        "unmapped_rows": 9,
        "verify_rows": 2,
    },
}


def test_the_synthetic_japanese_hospital_gives_counts_per_type_on_the_data_step(tmp_path: Path) -> None:
    b = _console(tmp_path, "TEST")
    h = b["app"].state.rc1_guard.h
    c, _ = login(b["app"])
    assert 'data-testid="ds-none"' in c.get(data_step.PATH).text
    h.au.append("ingest.done", ts=NOW, actor="adapter", detail=NIGHT)
    h.au.append("ingest.done", ts=NOW + timedelta(hours=1), actor="adapter", detail={"source": "csv", "counts": {}})
    page = c.get(data_step.PATH).text
    assert 'data-testid="ds-done"' in page and 'data-testid="ds-total">3960<' in page
    for t, n in NIGHT["counts"].items():
        assert f'data-testid="ds-type-{t}"' in page and f"<td>{n}</td>" in page
    assert "5 of 6 declared arrived" in page and "OML-11" in page and "PPR-01" in page
    api = _api(b["app"], "/api/v1" + data_step.PATH)
    assert api["counts"] == NIGHT["counts"] and api["done"] is True and api["coverage"]["unmapped_rows"] == 9


def test_a_held_night_leaves_the_data_step_not_done() -> None:
    st = data_step.step([_rec("ingest.done", NOW - timedelta(days=1), **NIGHT),
                         _rec("ingest.held", NOW, source="ssmix2", counts={"Patient": 3})])  # fmt: skip
    assert (st["done"], st["state"], st["total"], st["coverage"]) == (False, "held", 3, None)
