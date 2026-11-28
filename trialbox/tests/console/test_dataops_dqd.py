# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""Lane N (HOLISTIC-3 §1.2 row 17; H3-NLP §3.1): the steward's night page names each data quality check that did
not pass after the night's OMOP load, in the OHDSI Data Quality Dashboard's words (check, table and field, rows),
with a known gap's reason; the night's API answers the same rows. Counts and check names only. Synthetic data."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from console import i18n_dataops
from datacore.dataops import DataOps
from fastapi.testclient import TestClient
from tb_common.audit import AuditLog

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import PW, _user

AT = "2026-11-11T02:00:00+09:00"
FAIL = {
    "checkName": "plausibleAfterBirth",
    "cdmTableName": "condition_occurrence",
    "cdmFieldName": "condition_start_date",
    "numViolatedRows": 3,
    "numDenominatorRows": 1200,
    "status": "fail",
    "notes": "",
}
KNOWN = {
    "checkName": "standardConceptRecordCompleteness",
    "cdmTableName": "condition_occurrence",
    "cdmFieldName": "condition_concept_id",
    "numViolatedRows": 1200,
    "numDenominatorRows": 1200,
    "status": "known",
    "notes": "no SNOMED CT on the box",
}


def _night(b: dict[str, Any], omop: Any) -> int:
    ops = DataOps()
    try:
        detail = {"counts": {"Observation": 10}, **({"omop": omop} if omop is not None else {})}
        batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"), "ingest.done", source="csv",
                                    snapshot="2026-11-10", passed=True, held=False, by="adapter", at=AT,
                                    actor="adapter", detail=detail)  # fmt: skip
        return batch.id
    finally:
        ops.close()


@pytest.fixture(autouse=True)
def _orch(box: dict[str, Any]) -> None:
    from tests.console.dataops_orch import attach

    attach(box["backend"], box["audit"])


def _steward(b: dict[str, Any]) -> Any:
    _user(b, "stwq", "steward")
    return login(b["app"], "stwq", PW)


def _api(b: dict[str, Any]) -> TestClient:
    c = TestClient(b["app"])
    r = c.post("/api/v1/session", json={"username": "stwq", "password": PW})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c


def test_the_nights_page_names_each_check_that_did_not_pass_in_the_dashboards_words(box: dict[str, Any]) -> None:
    bid = _night(box, {"state": "loaded", "dqd": {"checks": 60, "fail": 1, "known": 1, "failed": [FAIL, KNOWN]}})
    c, _ = _steward(box)
    page = c.get(f"/data-ops/batches/{bid}").text
    m = re.search(r'<section class="card" data-testid="batch-dqd">(.*?)</section>', page, re.S)
    assert m, "no data quality section on the night's page"
    sec = m.group(1)
    rows = re.findall(r'<tr data-testid="dqd" data-check="([^"]+)" data-status="([^"]+)">', sec)
    assert rows == [("plausibleAfterBirth", "fail"), ("standardConceptRecordCompleteness", "known")]
    assert "condition_occurrence.condition_start_date" in sec and "3 / 1,200" in sec
    assert "no SNOMED CT on the box" in sec
    assert i18n_dataops.EN["dataops.dqd.title"] in sec

    api = _api(box).get(f"/api/v1/data/batches/{bid}").json()
    assert api["data_quality"] == {"checks": 60, "fail": 1, "known": 1, "failed": [FAIL, KNOWN]}


def test_the_nights_row_keeps_only_the_state_and_the_data_quality_fields(box: dict[str, Any]) -> None:
    extra = {**FAIL, "sample": "a cell"}
    omop = {"state": "loaded", "error": "a message", "dqd": {"checks": 60, "fail": 1, "known": 0, "failed": [extra]}}
    bid = _night(box, omop)
    ops = DataOps()
    try:
        b = ops.batch(bid)
        assert b is not None
        kept = b.detail["omop"]
    finally:
        ops.close()
    assert kept == {"state": "loaded", "dqd": {"checks": 60, "fail": 1, "known": 0, "failed": [FAIL]}}


def test_a_night_without_the_checks_shows_no_section_and_a_malformed_record_is_not_shown(box: dict[str, Any]) -> None:
    c, _ = _steward(box)
    api = _api(box)
    for omop in (None, {"state": "loaded"}, {"state": "loaded", "dqd": {"checks": "x", "failed": "y"}}):
        bid = _night(box, omop)
        assert 'data-testid="batch-dqd"' not in c.get(f"/data-ops/batches/{bid}").text
        assert api.get(f"/api/v1/data/batches/{bid}").json()["data_quality"] is None
