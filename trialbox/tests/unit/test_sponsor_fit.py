"""T-302d (D-435): the sponsor's layout, the screening log in the sponsor's columns, and the sponsor's weekly sheet
driving a lifecycle step a person confirms. Synthetic sponsor words and subjects only."""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from datacore import sponsor as sp
from datacore.lifecycle import Lifecycle
from datacore.store import DataCore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.lifecycle_api import LifeHost
from orchestrator.sponsor_api import router
from tb_common.audit import AuditLog

STUDY = "GZQO"
TODAY = date(2026, 11, 11)
AT = "2026-11-11T09:00:00+08:00"
LAYOUT: dict[str, Any] = {
    "sponsor": "Synthetic Pharma",
    "log": [
        {"from": "screening_no", "heading": "Subject ID"},
        {"from": "status", "heading": "Subject Status",
         "values": {"screen_fail": "Screen Failed", "enrolled": "Randomized"}},
        {"from": "consent_date", "heading": "ICF Signed", "date": "%d-%b-%Y"},
        {"from": "criterion_not_met", "heading": "Failed Criterion"},
    ],
    "weekly": {"subject": "Subject", "status": "Status", "date": "Status Date", "date_format": "%d-%b-%Y",
               "reason": "Reason", "statuses": {"Screened": "approached", "Consented": "consented",
                                                "Screen Failed": "screen_fail", "Enrolled": "enrolled"},
               "reasons": {"Not eligible": "not_eligible", "Declined": "declined"}},
}  # fmt: skip


def _row(**kv: str) -> list[str]:
    return [kv.get(c, "") for c in sp.LOG_COLUMNS]


def _sheet(*lines: str, head: str = "Subject,Status,Status Date,Reason") -> bytes:
    return ("\n".join([head, *lines]) + "\n").encode("utf-8")


def _subjects(dc: DataCore) -> Lifecycle:
    life = Lifecycle(dc)
    for rec, pid in (("S-001", "a" * 32), ("S-002", "b" * 32), ("S-003", "c" * 32)):
        life.ensure(STUDY, rec, pid, "crc", AT)
    life.step(STUDY, "S-002", "approached", by="crc", at=AT, on_day="2026-11-02")
    return life


# ------------------------------------------------------------------ the layout
@pytest.mark.parametrize("bad,code", [
    ({"log": [{"from": "chart_no", "heading": "MRN"}]}, "sponsor.column"),
    ({"log": [{"from": "status", "heading": "A"}, {"from": "reason", "heading": "A"}]}, "sponsor.layout"),
    ({"log": [{"from": "consent_date", "heading": "ICF", "date": "%s"}]}, "sponsor.date_format"),
    ({"log": [{"from": "status", "heading": "S", "date": "%Y-%m-%d"}]}, "sponsor.date_format"),
    ({"weekly": {**LAYOUT["weekly"], "statuses": {"Done": "finished"}}}, "sponsor.state"),
    ({"weekly": {**LAYOUT["weekly"], "reasons": {"Other": "9"}}}, "sponsor.reason"),
    ([], "sponsor.layout"),
])  # fmt: skip
def test_a_layout_naming_what_trialbox_does_not_have_is_refused(bad: Any, code: str) -> None:
    with pytest.raises(sp.SponsorError) as e:
        sp.check_layout(bad)
    assert e.value.code == code


def test_the_layout_is_kept_as_versions(tmp_path: Path) -> None:
    dc = DataCore()
    lay = sp.Layouts(dc)
    assert lay.get(STUDY) is None
    lay.put(STUDY, {"log": [{"from": "status", "heading": "Status"}]}, "crc", AT)
    cur = lay.put(STUDY, LAYOUT, "pi", AT)
    assert cur["layout"]["log"][0] == {"from": "screening_no", "heading": "Subject ID"} and cur["by"] == "pi"
    assert [h["by_user"] for h in lay.history(STUDY)] == ["crc", "pi"]


# ------------------------------------------------------------------ the screening log in the sponsor's columns
def test_the_log_exports_with_the_sponsors_columns_words_and_dates() -> None:
    rows = [_row(screening_no="S-001", pseudonym="a" * 32, status="screen_fail", consent_date="2026-11-03",
                 criterion_not_met="GZQO-EXC-06 (v3.0.0)"),
            _row(screening_no="S-002", status="enrolled", consent_date="")]  # fmt: skip
    heads, body = sp.log_table(sp.check_layout(LAYOUT), rows)
    assert heads == ["Subject ID", "Subject Status", "ICF Signed", "Failed Criterion"]
    assert body == [["S-001", "Screen Failed", "03-Nov-2026", "GZQO-EXC-06 (v3.0.0)"],
                    ["S-002", "Randomized", "", ""]]  # fmt: skip
    assert all("a" * 32 not in line for line in body)  # only the columns the sponsor names
    with pytest.raises(sp.SponsorError):
        sp.log_table({"log": []}, rows)


# ------------------------------------------------------------------ the weekly sheet
def test_the_weekly_sheet_drives_a_lifecycle_step_a_person_confirms(tmp_path: Path) -> None:
    """TB-ASSESS-01 T-302 acceptance: the weekly CSV drives a lifecycle step (here only once a person confirms)."""
    dc = DataCore()
    life = _subjects(dc)
    lay = sp.check_layout(LAYOUT)
    data = _sheet("S-001,Screened,02-Nov-2026,", "S-002,Screen Failed,05-Nov-2026,Not eligible",
                  "S-003,Enrolled,06-Nov-2026,", "S-404,Screened,01-Nov-2026,", "s-002,Screen Failed,05-Nov-2026,"
                  "Not eligible")  # fmt: skip
    sha, rows = sp.read_weekly(data, lay)
    assert len(rows) == 4  # the same answer twice is one row
    props = {p["record"]: p for p in sp.proposals(dc, STUDY, rows, TODAY)}
    assert props["S-001"]["kind"] == "step" and props["S-001"]["to"] == "approached"
    assert props["S-002"]["kind"] == "step" and props["S-002"]["reason"] == "not_eligible"
    assert props["S-003"]["kind"] == "held" and props["S-003"]["why"] == "order"  # candidate -> enrolled
    assert props["S-404"]["kind"] == "unknown"
    assert life.subject(STUDY, "S-002")["state"] == "approached"  # type: ignore[index]  # nothing written yet
    sub = sp.confirm(dc, STUDY, sha, rows, "S-002", by="crc", at=AT, today=TODAY)
    assert sub["state"] == "screen_fail" and sub["since"] == "2026-11-05" and sub["reason"] == "not_eligible"
    step = life.steps(STUDY, "S-002")[-1]
    assert step["source"] == "sponsor_weekly" and sha[:16] in step["note"] and step["who"] == "crc"
    again = {p["record"]: p for p in sp.proposals(dc, STUDY, rows, TODAY)}
    assert again["S-002"]["kind"] == "same"
    with pytest.raises(Exception) as e:
        sp.confirm(dc, STUDY, sha, rows, "S-003", by="crc", at=AT, today=TODAY)
    assert getattr(e.value, "why", "") == "order"


def test_screen_failure_without_a_reason_and_a_future_day_are_held(tmp_path: Path) -> None:
    dc = DataCore()
    _subjects(dc)
    _, rows = sp.read_weekly(_sheet("S-002,Screen Failed,05-Nov-2026,", "S-001,Screened,30-Nov-2026,"),
                             sp.check_layout(LAYOUT))  # fmt: skip
    props = {p["record"]: p for p in sp.proposals(dc, STUDY, rows, TODAY)}
    assert props["S-002"]["why"] == "reason" and props["S-001"]["why"] == "future"


@pytest.mark.parametrize("data,code", [
    (_sheet("S-001,Screened,02-Nov-2026,", head="Subject,Status,Reason"), "sponsor.columns"),
    (_sheet("S-001,Finished,02-Nov-2026,"), "sponsor.status"),
    (_sheet("S-001,Screened,2026-11-02,"), "sponsor.date"),
    (_sheet("S-001,Screened,02-Nov-2026,Moved away"), "sponsor.reason"),
    (_sheet("S-001,Screened,02-Nov-2026,", "S-001,Consented,04-Nov-2026,"), "sponsor.duplicate"),
    (_sheet("=HYPERLINK(1),Screened,02-Nov-2026,"), "sponsor.subject"),
    ("Subject,Status,Status Date,Reason\nS-001,Screened,02-Nov-2026,�\n".encode(), "sponsor.encoding"),
])  # fmt: skip
def test_a_sheet_that_does_not_fit_the_layout_is_refused_whole(data: bytes, code: str) -> None:
    with pytest.raises(sp.SponsorError) as e:
        sp.read_weekly(data, sp.check_layout(LAYOUT))
    assert e.value.code == code


def test_a_sheet_in_big5_with_semicolons_and_size_limit() -> None:
    lay = sp.check_layout({**LAYOUT, "weekly": {**LAYOUT["weekly"], "subject": "受試者編號",
                                                "statuses": {"已篩選": "approached", "篩選失敗": "screen_fail"}}})  # fmt: skip
    data = "受試者編號;Status;Status Date;Reason\nS-001;已篩選;02-Nov-2026;\nS-002;篩選失敗;05-Nov-2026;Declined\n"
    _, rows = sp.read_weekly(data.encode("big5"), lay)
    assert [(r.record, r.state, r.reason) for r in rows] == [("S-001", "approached", ""),
                                                             ("S-002", "screen_fail", "declined")]  # fmt: skip
    with pytest.raises(sp.SponsorError) as e:
        sp.read_weekly(data.encode("utf-8"), lay, env={sp.MAX_BYTES_ENV: "10"})
    assert e.value.code == "sponsor.size"


# ------------------------------------------------------------------ the orchestrator routes
def test_the_routes_read_propose_and_confirm_all_or_nothing(tmp_path: Path) -> None:
    dc = DataCore()
    life = _subjects(dc)
    audit = AuditLog(tmp_path / "audit")
    host = LifeHost(dc, None, audit, lambda: datetime(2026, 11, 11, 1, 0, tzinfo=UTC))
    app = FastAPI()
    app.include_router(router(lambda: host))  # type: ignore[arg-type,return-value]
    c = TestClient(app)
    base = f"/studies/{STUDY}/sponsor"
    sheet = base64.b64encode(_sheet("S-001,Screened,02-Nov-2026,", "S-003,Enrolled,06-Nov-2026,")).decode()
    assert c.post(f"{base}/weekly", json={"data": sheet, "by": "crc"}).json()["detail"]["code"] == "sponsor.no_layout"
    assert c.put(f"{base}/layout", json={"layout": {"log": [{"from": "x", "heading": "y"}]}, "by": "crc"}
                 ).status_code == 400  # fmt: skip
    assert c.put(f"{base}/layout", json={"layout": LAYOUT, "by": "crc"}).status_code == 200
    assert c.get(f"{base}/layout").json()["current"]["layout"]["sponsor"] == "Synthetic Pharma"
    out = c.post(f"{base}/weekly", json={"data": sheet, "by": "crc", "name": "week45.csv"}).json()
    assert out["counts"] == {"same": 0, "step": 1, "held": 1, "unknown": 0}
    r = c.post(f"{base}/weekly/confirm", json={"data": sheet, "by": "crc", "records": ["S-001", "S-003"]})
    assert r.status_code == 409 and r.json()["detail"]["why"] == "order"
    assert life.subject(STUDY, "S-001")["state"] == "candidate"  # type: ignore[index]  # nothing taken
    r = c.post(f"{base}/weekly/confirm", json={"data": sheet, "by": "crc", "records": ["S-001"]})
    assert r.status_code == 200 and r.json()["done"][0]["subject"]["state"] == "approached"
    lines = [json.loads(x) for f in sorted((tmp_path / "audit").glob("*.jsonl"))
             for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]  # fmt: skip
    steps = [a for a in lines if a.get("event") == "life.step"]
    assert steps and steps[-1]["detail"]["source"] == "sponsor_weekly" and steps[-1]["detail"]["file"]
