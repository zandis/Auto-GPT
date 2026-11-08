"""Trial lifecycle v1 (TB-PLAN-04 step 5, D-134): the subject state machine, derivation from the data core's answers,
the schedule of events (TrialBox's own and REDCap's arms and events), visit windows on a given day in the site's
zone, AEs on numbered events, the enrolment report, and the S21 write-back folded into the data core."""

from __future__ import annotations

import base64
import csv
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from datacore import lifecycle as lc
from datacore.builtin import builtin_questionnaires
from datacore.lifecycle import Lifecycle, LifeError, Visit
from datacore.store import DataCore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from orchestrator.candidates import CandidateRegistry
from orchestrator.datacore_api import DataService
from orchestrator.datacore_api import router as dc_router
from orchestrator.db import JobDB
from orchestrator.lifecycle_api import registry_path
from orchestrator.lifecycle_api import router as life_router
from rc_sim.app import create_app
from tb_common.audit import AuditLog

from tests.rc_kit import LINK_A, PIDS, TOKEN_A, sim_edit, study_service
from tests.unit.test_datacore import rc_client

AT = "2026-11-08T09:00:00+09:00"
RS = "GZQO"
SCHED = [Visit("v1", 7, 2, 2), Visit("v2", 28, 3, 3), Visit("v3", 84, 7, 7)]


@pytest.fixture
def life() -> Any:
    dc = DataCore()
    for q in builtin_questionnaires(RS):
        dc.put_form(RS, q, "builtin", AT)
    yield Lifecycle(dc)
    dc.close()


def _put(life: Lifecycle, rec: str, values: dict[str, str], event: str = "") -> None:
    for f, v in values.items():
        life.dc.write(RS, rec, event, f, v, "crc", AT, "trialbox")


# ---------------------------------------------------------------------------------------------- the state machine
def test_legal_steps_illegal_refused_with_a_plain_reason_and_undo(life: Lifecycle) -> None:
    life.ensure(RS, "GZQO-0001", "ab" * 16, "crc", AT)
    assert (life.subject(RS, "GZQO-0001") or {})["state"] == "candidate"
    with pytest.raises(LifeError) as e:
        life.step(RS, "GZQO-0001", "enrolled", by="crc", at=AT)
    assert e.value.why == "order" and e.value.detail["allowed"] == "approached, screen_fail"
    with pytest.raises(LifeError) as e:
        life.step(RS, "GZQO-0001", "screen_fail", by="crc", at=AT)
    assert e.value.why == "reason"
    with pytest.raises(LifeError) as e:
        life.step(RS, "GZQO-0001", "approached", by="crc", at=AT, on_day="2026-11-09", today=date(2026, 11, 8))
    assert e.value.why == "future"
    for to in ("approached", "consented", "enrolled", "on_study"):
        life.step(RS, "GZQO-0001", to, by="crc", at=AT, on_day="2026-11-05")
    life.step(RS, "GZQO-0001", "withdrawn", by="crc", at=AT, reason="1", note="moved away")
    with pytest.raises(LifeError) as e:
        life.step(RS, "GZQO-0001", "completed", by="crc", at=AT)
    assert e.value.why == "final"
    assert life.undo(RS, "GZQO-0001", by="crc", at=AT)["state"] == "on_study"  # a mistake put right
    life.step(RS, "GZQO-0001", "completed", by="crc", at=AT)
    trail = [(s["old"], s["new"], s["source"]) for s in life.steps(RS, "GZQO-0001")]
    assert trail[0] == (None, "candidate", "screening") and trail[-3:] == [
        ("on_study", "withdrawn", "manual"),
        ("withdrawn", "on_study", "undo"),
        ("on_study", "completed", "manual"),
    ]
    assert lc.can_step("candidate", "nope") == "unknown" and lc.can_step("enrolled", "enrolled") == "same"


def test_derived_from_the_forms_with_implied_steps_and_held(life: Lifecycle) -> None:
    life.ensure(RS, "GZQO-0002", "", "crc", AT)
    _put(life, "GZQO-0002", {"ic_date": "2026-10-01", "en_date": "2026-10-03", "en_eligible": "1"})
    _put(life, "GZQO-0002", {"vs_status": "1", "vs_date": "2026-10-10"}, "v1")
    out = life.derive(RS, "GZQO-0002", by="crc", at=AT, schedule=SCHED)
    assert [s["to"] for s in out["steps"]] == ["approached", "consented", "enrolled", "on_study"]
    steps = life.steps(RS, "GZQO-0002")
    assert steps[1]["note"].startswith("implied by form:tb_consent") and steps[2]["on_day"] == "2026-10-01"
    assert steps[4]["source"] == "form:tb_visit:v1" and steps[4]["on_day"] == "2026-10-10"
    assert life.derive(RS, "GZQO-0002", by="crc", at=AT, schedule=SCHED) == {"steps": [], "held": []}  # idempotent
    _put(life, "GZQO-0002", {"sl_eligible": "0", "sl_date": "2026-09-30", "sl_reason": "HbA1c"})
    held = life.derive(RS, "GZQO-0002", by="crc", at=AT, schedule=SCHED)["held"]
    assert held == [{"state": "screen_fail", "why": "order", "current": "on_study"}]  # never forced
    _put(life, "GZQO-0002", {"wd_date": "2026-10-20", "wd_reason": "3"})
    out = life.derive(RS, "GZQO-0002", by="crc", at=AT, schedule=SCHED)
    assert out["steps"][-1]["to"] == "withdrawn" and (life.subject(RS, "GZQO-0002") or {})["reason"] == "3"
    # a sponsor study: no TrialBox CRF, the screening log's status is the evidence
    life.ensure(RS, "GZQO-0003", "cd" * 16, "crc", AT)
    out = life.derive(RS, "GZQO-0003", by="crc", at=AT, registry="enrolled")
    assert [s["to"] for s in out["steps"]] == ["approached", "consented", "enrolled"]
    life.ensure(RS, "GZQO-0004", "", "crc", AT)
    life.derive(RS, "GZQO-0004", by="crc", at=AT, registry="declined")
    assert ((life.subject(RS, "GZQO-0004") or {})["state"], (life.subject(RS, "GZQO-0004") or {})["reason"]) == (
        "screen_fail",
        "declined",
    )


def test_visit_windows_on_a_given_day(life: Lifecycle) -> None:
    life.ensure(RS, "GZQO-0005", "", "crc", AT)
    _put(life, "GZQO-0005", {"ic_date": "2026-11-01", "en_date": "2026-11-02", "en_eligible": "1"})
    life.derive(RS, "GZQO-0005", by="crc", at=AT)

    def status(day: str) -> list[str]:
        return [v["status"] for v in life.visits(RS, "GZQO-0005", date.fromisoformat(day), SCHED)]

    v1 = life.visits(RS, "GZQO-0005", date(2026, 11, 3), SCHED)[0]
    assert (v1["due"], v1["start"], v1["end"]) == ("2026-11-09", "2026-11-07", "2026-11-11")
    assert status("2026-11-03") == ["due", "due", "due"]
    assert status("2026-11-07") == ["open", "due", "due"] and status("2026-11-11")[0] == "open"
    assert status("2026-11-12") == ["overdue", "due", "due"]
    over = life.visits(RS, "GZQO-0005", date(2026, 11, 14), SCHED)[0]
    assert over["days_late"] == 3
    wl = lc.worklist([{**r, "record": "GZQO-0005"} for r in life.visits(RS, "GZQO-0005", date(2026, 11, 9), SCHED)],
                     date(2026, 11, 9))  # fmt: skip
    assert [r["visit"] for r in wl["today"]] == ["v1"] and wl["overdue"] == [] and wl["week"] == []
    _put(life, "GZQO-0005", {"vs_status": "1", "vs_date": "2026-11-13"}, "v1")
    _put(life, "GZQO-0005", {"vs_status": "2", "vs_missed_reason": "ill"}, "v2")
    rows = life.visits(RS, "GZQO-0005", date(2026, 12, 20), SCHED)
    assert [r["status"] for r in rows] == ["done", "missed", "due"] and rows[0]["in_window"] is False
    _put(life, "GZQO-0005", {"wd_date": "2026-12-21", "wd_reason": "1"})
    life.derive(RS, "GZQO-0005", by="crc", at=AT, schedule=SCHED)
    assert status("2026-12-22") == ["done", "missed", "stopped"]


def test_aes_on_numbered_events_and_the_report(life: Lifecycle) -> None:
    life.ensure(RS, "GZQO-0006", "", "crc", AT)
    assert life.next_event(RS, "GZQO-0006", "ae") == "ae1"
    _put(life, "GZQO-0006", {"ae_term": "頭痛", "ae_serious": "0"}, "ae1")
    _put(life, "GZQO-0006", {"ae_term": "肺炎", "ae_serious": "1"}, "ae2")
    assert life.next_event(RS, "GZQO-0006", "ae") == "ae3" and life.next_event(RS, "GZQO-0006", "dv") == "dv1"
    assert [e["ae_term"] for e in life.entries(RS, None, lc.AE_EVENT)] == ["頭痛", "肺炎"]
    life.ensure(RS, "GZQO-0007", "", "crc", AT)
    life.step(RS, "GZQO-0007", "screen_fail", by="crc", at=AT, on_day="2026-10-30", reason="declined")
    life.ensure(RS, "GZQO-0008", "", "crc", AT)
    for to in ("approached", "consented", "enrolled"):
        life.step(RS, "GZQO-0008", to, by="crc", at=AT, on_day="2026-11-02")
    life.step(RS, "GZQO-0008", "withdrawn", by="crc", at=AT, on_day="2026-11-04", reason="4")
    rep = lc.report(life.subjects(RS), life.steps(RS))
    assert rep["counts"]["candidate"] == 1 and rep["counts"]["screen_fail"] == 1 and rep["counts"]["withdrawn"] == 1
    assert rep["ever"]["enrolled"] == 1 and rep["screen_fail_reasons"] == {"declined": 1}
    assert rep["withdrawals"] == [{"record": "GZQO-0008", "day": "2026-11-04", "reason": "4"}]
    months = {m["month"]: m for m in rep["months"]}
    assert months["2026-10"]["screen_fail"] == 1 and months["2026-11"]["enrolled"] == 1
    assert rep["registry"] == {"candidate": 1, "screen_fail": 1, "withdrawn": 1}


def test_registry_path_uses_the_logs_own_transitions() -> None:
    assert registry_path(None, "contacted") == ["candidate", "contacted"]
    assert registry_path("candidate", "enrolled") == ["consented", "enrolled"]
    assert registry_path("enrolled", "enrolled") == []
    assert registry_path("enrolled", "withdrawn") == ["withdrawn"]


# ---------------------------------------------------------------------------------------------- the API
def _api(tmp_path: Path, now: datetime) -> tuple[TestClient, Any, CandidateRegistry, AuditLog]:
    sim = create_app()
    audit = AuditLog(tmp_path / "audit")
    reg = CandidateRegistry(JobDB(), audit, tmp_path)
    svc = DataService(DataCore(), audit, lambda: now, lambda _ref: rc_client(sim)(), None, reg)
    app = FastAPI()
    app.include_router(dc_router(lambda: svc))
    app.include_router(life_router(lambda: svc))
    c = TestClient(app)
    assert c.post(f"/studies/{RS}/forms/builtin", json={"by": "crc"}).status_code == 200
    return c, sim, reg, audit


def test_api_path_mirror_refusal_today_and_report(tmp_path: Path) -> None:
    tokyo = datetime(2026, 11, 9, 0, 30, tzinfo=ZoneInfo("Asia/Tokyo"))  # 2026-11-08 15:30 UTC
    c, _sim, reg, audit = _api(tmp_path, tokyo)
    pid = "ef" * 16
    out = c.post(f"/studies/{RS}/subjects/refresh", json={"screening": {"gzqo-0042": pid}, "by": "crc"}).json()
    assert out["made"] == [{"record": "GZQO-0042", "from": None, "to": "candidate"}]
    r = c.post(f"/studies/{RS}/subjects/GZQO-0042/step", json={"to": "enrolled", "by": "crc"})
    assert r.status_code == 409 and r.json()["detail"]["why"] == "order"
    for form, vals in (("tb_consent", {"ic_date": "2026-11-02", "ic_version": "v1", "ic_copy": "1"}),
                       ("tb_enrolment", {"en_date": "2026-11-03", "en_eligible": "1"})):  # fmt: skip
        r = c.post(f"/studies/{RS}/entry/GZQO-0042", json={"form": form, "values": vals, "by": "crc"})
        assert r.status_code == 200, r.text
    assert r.json()["life"]["made"][-1]["to"] == "enrolled"
    assert {e.pid: e.status for e in reg.rows(RS)} == {pid: "enrolled"}  # the screening log follows
    sched = {
        "visits": [
            {"visit": "v1", "day": 7, "before": 2, "after": 2, "labels": {"ja": "1週目"}},
            {"visit": "v2", "day": 28, "before": 3, "after": 3},
        ],
        "by": "crc",
    }
    assert c.put(f"/studies/{RS}/schedule", json=sched).status_code == 200
    bad = c.put(f"/studies/{RS}/schedule", json={"visits": [{"visit": "ae1", "day": 1}], "by": "crc"})
    assert bad.status_code == 409 and bad.json()["detail"]["why"] == "visit"
    # the site's date: 00:30 in Tokyo is already the next day
    assert c.get(f"/studies/{RS}/visits").json()["today"] == "2026-11-09"
    assert c.get(f"/studies/{RS}/visits", params={"today": "2026-11-10"}).json()["list"]["today"][0]["visit"] == "v1"
    assert c.get(f"/studies/{RS}/visits", params={"today": "2026-11-13"}).json()["list"]["overdue"][0]["visit"] == "v1"
    r = c.post(
        f"/studies/{RS}/entry/GZQO-0042",
        json={"form": "tb_visit", "event": "v1", "by": "crc", "values": {"vs_status": "1", "vs_date": "2026-11-13"}},
    )
    assert r.json()["life"]["made"][-1]["to"] == "on_study"
    one = c.get(f"/studies/{RS}/subjects/GZQO-0042", params={"today": "2026-11-13"}).json()
    assert one["visits"][0]["status"] == "done" and one["subject"]["next"] == ["completed", "withdrawn"]
    assert one["next_ae"] == "ae1"
    r = c.post(f"/studies/{RS}/entry/GZQO-0042", json={"form": "tb_adverse_event", "event": "ae1", "by": "crc",
               "values": {"ae_term": "pneumonia", "ae_onset": "2026-11-12", "ae_serious": "1", "ae_serious_why": "3",
                          "ae_severity": "3", "ae_related": "9"}})  # fmt: skip
    assert r.status_code == 200, r.text
    assert [a["ae_term"] for a in c.get(f"/studies/{RS}/aes").json()["serious"]] == ["pneumonia"]
    r = c.post(f"/studies/{RS}/subjects/GZQO-0042/step", json={"to": "withdrawn", "reason": "3", "by": "crc"})
    assert r.status_code == 200 and {e.pid: e.status for e in reg.rows(RS)} == {pid: "withdrawn"}
    r = c.post(f"/studies/{RS}/subjects/GZQO-0042/step", json={"to": "on_study", "by": "crc"})
    assert r.status_code == 409 and r.json()["detail"]["why"] == "final"
    rep = c.get(f"/studies/{RS}/report").json()
    assert rep["counts"]["withdrawn"] == 1 and rep["ever"]["on_study"] == 1 and rep["registry"] == {"withdrawn": 1}
    x = c.get(f"/studies/{RS}/report/xlsx").json()
    wb = load_workbook(io.BytesIO(base64.b64decode(x["b64"])))
    assert wb.sheetnames == ["states", "months", "screen_fail", "withdrawals", "about"]
    rows = list(csv.reader(io.StringIO(c.get(f"/studies/{RS}/report/csv").json()["text"])))
    assert ["state", "now", "withdrawn", "1"] in rows and ["withdrawal", "GZQO-0042", "2026-11-09", "3"] in rows
    events = [
        json.loads(x)["event"] for f in sorted(audit.directory.glob("*.jsonl")) for x in f.read_text().splitlines()
    ]
    assert {"life.step", "life.refused", "life.schedule", "life.report"} <= set(events)
    # a schedule from REDCap's arms and events (project B, longitudinal)
    r = c.post(f"/studies/{RS}/schedule/redcap", json={"token_ref": "b", "by": "crc"})
    assert r.status_code == 409  # project A is a classic project: no events
    taipei = datetime(2026, 11, 8, 23, 30, tzinfo=ZoneInfo("Asia/Taipei"))  # the same instant: still the 8th
    c2, _sim, _reg, _audit = _api(tmp_path / "tw", taipei)
    assert c2.get(f"/studies/{RS}/visits").json()["today"] == "2026-11-08"
    assert tokyo.astimezone(UTC) == taipei.astimezone(UTC)


def test_schedule_from_redcap_arms_and_events(tmp_path: Path) -> None:
    from rc_bridge.client import RedcapClient

    from tests.rc_kit import TOKEN_B

    sim = create_app()

    def client(_ref: str) -> RedcapClient:
        rc = RedcapClient("https://rc.example/", TOKEN_B, http=TestClient(sim, base_url="http://rc"))
        rc.url = "/api/"
        return rc

    svc = DataService(DataCore(), AuditLog(tmp_path / "a"), lambda: datetime(2026, 11, 8, tzinfo=UTC), client)
    app = FastAPI()
    app.include_router(life_router(lambda: svc))
    c = TestClient(app)
    r = c.post("/studies/RB/schedule/redcap", json={"token_ref": "rb", "by": "crc"})
    assert r.status_code == 200, r.text
    assert [
        (v["visit"], v["day"], v["before"], v["after"]) for v in c.get("/studies/RB/schedule").json()["visits"]
    ] == [("screening_arm_1", 0, 0, 0), ("m12_arm_1", 365, 30, 30)]


# ---------------------------------------------------------------------------------------------- one writer per field
def test_s21_write_back_goes_through_the_data_core(tmp_path: Path) -> None:
    """The three screening fields are the data core's TrialBox-owned fields: a REDCap-side edit of one is a
    conflict (never overwritten), and a data-core REDCap source that maps them stops the S21 write (one writer)."""
    with study_service(tmp_path) as (svc, sim, _clock):
        svc.save_link("GZQO", {**LINK_A, "write_mode": "existing"}, "crc")
        screening = {"GZQO-0901": PIDS["GZQO-0901"]}
        issued = {"GZQO-0901": "2026-10-01T09:00:00+09:00"}
        w = svc.read("GZQO", screening, "crc", issued=issued)["write"]
        assert w["updated"] == 1 and svc.datacore().record("GZQO", "GZQO-0901")["tb_status"] == "4"
        hist = svc.datacore().history("GZQO", "GZQO-0901")
        assert {h["field"] for h in hist} >= {"tb_status", "tb_screen_date", "tb_status_date"}
        sim_edit(sim, 101, [{"record_id": "1", "tb_status": "6"}])  # someone types into TrialBox's field in REDCap
        w = svc.read("GZQO", screening, "crc", issued=issued)["write"]
        assert w["conflicts"] == 1 and w["updated"] == 0
        conflicts = svc.datacore().conflicts("GZQO")
        assert [(x["field"], x["trialbox"], x["theirs"], x["source"]) for x in conflicts] == [
            ("tb_status", "4", "6", "redcap-link")
        ]
        assert svc.lifecycle("GZQO", screening, "crc")["made"] == 0  # the subject already follows the log
        assert (Lifecycle(svc.datacore()).subject("GZQO", "GZQO-0901") or {})["state"] == "enrolled"
        svc.datacore().put_source("GZQO", "redcap", {"field_map": {"tb_status": "tb_status"}})
        w = svc.read("GZQO", screening, "crc", issued=issued)["write"]
        assert w["error"] == "RC-WRITE-OWNER"
    assert TOKEN_A
