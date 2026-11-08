"""The orchestrator's data-core API (TB-PLAN-04 step 3, D-123): forms, entry, REDCap attach and sync, conflicts,
a PI's sheet. TB-PLAN-04 §2: the WIP is merged only with API tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from datacore.store import DataCore
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.datacore_api import DataService, router
from rc_sim.app import create_app
from tb_common.audit import AuditLog

from tests.rc_kit import sim_edit
from tests.unit.test_datacore import dictionary_a, rc_client

STAMP = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)
KEY = b"0123456789abcdef0123456789abcdef"


def _api(tmp_path: Path, site_key: bytes | None = KEY) -> tuple[TestClient, AuditLog]:
    sim = create_app()
    audit = AuditLog(tmp_path / "audit")
    svc = DataService(DataCore(), audit, lambda: STAMP, lambda _ref: rc_client(sim)(),
                      (lambda: site_key) if site_key else None)  # fmt: skip
    app = FastAPI()
    app.include_router(router(lambda: svc))
    c = TestClient(app)
    r = c.post("/studies/GZQO/forms/dictionary", json={"csv": dictionary_a(), "record_field": "record_id", "by": "crc"})
    assert r.status_code == 200, r.text
    c.sim = sim
    return c, audit


def _events(audit: AuditLog) -> list[str]:
    return [json.loads(x)["event"] for f in sorted(audit.directory.glob("*.jsonl")) for x in f.read_text().splitlines()]


def test_forms_drop_identifier_fields_and_entry_checks_ownership(tmp_path: Path) -> None:
    c, audit = _api(tmp_path)
    forms = c.get("/studies/GZQO/forms").json()
    names = {i["linkId"] for q in forms for i in q.get("item", [])}
    assert "pt_name" not in names and "consent_date" in names
    r = c.put("/studies/GZQO/data/gzqo-0042", json={"values": {"tb_status": "2"}, "by": "crc"})
    assert r.status_code == 200 and r.json()["record"] == {"tb_status": "2"}
    assert c.put("/studies/GZQO/data/GZQO-0042", json={"values": {"nope": "1"}, "by": "crc"}).status_code >= 400
    assert c.get("/studies/bad id/forms").status_code in (400, 404)
    fields = ["consent_date", "enrolled", "subject_no", "tb_status", "tb_screen_date"]
    r = c.put("/studies/GZQO/sources/redcap", json={"token_ref": "gzqo", "field_map": {f: f for f in fields},
                                                     "owned": ["consent_date"], "by": "crc"})  # fmt: skip
    assert r.status_code == 200
    r = c.put("/studies/GZQO/data/GZQO-0042", json={"values": {"consent_date": "2026-11-01"}, "by": "crc"})
    assert r.status_code == 409 and "OWNED" in r.text  # REDCap's field is changed in REDCap, not here
    bad = c.put("/studies/GZQO/sources/redcap", json={"token_ref": "gzqo", "field_map": {"x": "unknown"},
                                                       "owned": ["unknown"], "by": "crc"})  # fmt: skip
    assert bad.status_code == 409
    assert {"data.entry", "data.source"} <= set(_events(audit))


def test_sync_conflicts_and_resolution_through_the_api(tmp_path: Path) -> None:
    c, audit = _api(tmp_path)
    c.put(
        "/studies/GZQO/data/GZQO-0901", json={"values": {"consent_date": "2026-10-19", "tb_status": "3"}, "by": "crc"}
    )
    fields = ["consent_date", "enrolled", "subject_no", "tb_status", "tb_screen_date"]
    c.put("/studies/GZQO/sources/redcap", json={"token_ref": "gzqo", "field_map": {f: f for f in fields},
                                                 "owned": ["consent_date", "enrolled", "subject_no"], "create": True,
                                                 "by": "crc"})  # fmt: skip
    assert c.post("/studies/GZQO/sync/nosuch", json={"by": "crc"}).status_code == 404
    r1 = c.post("/studies/GZQO/sync/redcap", json={"by": "crc"}).json()
    assert [x["field"] for x in r1["conflicts"]] == ["consent_date"]
    sim_edit(c.sim, 101, [{"record_id": "1", "tb_status": "5"}])
    r2 = c.post("/studies/GZQO/sync/redcap", json={"by": "crc"}).json()
    assert [(x["field"], x["theirs"]) for x in r2["conflicts"]] == [("tb_status", "5")]
    open_c = c.get("/studies/GZQO/conflicts").json()
    assert len(open_c) == 2
    for x in open_c:
        r = c.post(f"/studies/GZQO/conflicts/{x['id']}", json={"keep": "trialbox", "by": "pi"})
        assert r.status_code == 200, r.text
    assert c.get("/studies/GZQO/conflicts").json() == []
    assert len(c.get("/studies/GZQO/conflicts", params={"all": True}).json()) == 2  # the trail stays
    assert c.post("/studies/GZQO/sync/redcap", json={"by": "crc"}).json()["pushed"] >= 1
    assert {"data.sync", "data.resolve"} <= set(_events(audit))


@pytest.mark.parametrize("with_key", [True, False])
def test_sheet_import_needs_the_site_key_and_never_stores_a_chart_number(tmp_path: Path, with_key: bool) -> None:
    c, _ = _api(tmp_path, KEY if with_key else None)
    sheet = "カルテ番号,氏名,同意日\n00123,山田太郎,2026-11-01\n,佐藤,2026-11-02\n"
    body: dict[str, Any] = {"name": "pi", "csv": sheet, "columns": {"同意日": "consent_date"},
                            "mrn_column": "カルテ番号", "by": "crc"}  # fmt: skip
    r = c.post("/studies/GZQO/import/sheet", json=body)
    if not with_key:
        assert r.status_code == 409 and "DATA-KEY" in r.text
        return
    out = r.json()
    assert out["dropped"] == ["氏名"] and out["taken"] == 1 and len(out["refused"]) == 1
    dump = json.dumps(c.get("/studies/GZQO/data").json(), ensure_ascii=False)
    assert "00123" not in dump and "山田" not in dump
    body["columns"] = {"氏名": "consent_date"}
    assert c.post("/studies/GZQO/import/sheet", json=body).status_code >= 400  # an identifier column is never imported
