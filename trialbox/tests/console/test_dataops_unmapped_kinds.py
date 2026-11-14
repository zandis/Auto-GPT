# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""NEW-B-39 (D-740): the batch row keeps the night's split by kind and the data-ops API answers it per table.
Synthetic data only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from datacore.dataops import DataOps
from fastapi.testclient import TestClient
from tb_common.audit import AuditLog

from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_dataops_page import _bearer

AT = "2026-11-11T02:00:00+09:00"
LAB = {"code_unknown": 1100, "unit_not_read": 90, "reference_data_not_reached": 10}


def _night(b: dict[str, Any], detail: dict[str, Any]) -> int:
    ops = DataOps()
    try:
        batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"), "ingest.done", source="csv",
                                    snapshot="2026-11-10", passed=True, held=False, by="adapter", at=AT,
                                    actor="adapter", detail={"counts": {"Observation": 10}, **detail})  # fmt: skip
        return batch.id
    finally:
        ops.close()


def test_the_api_answers_each_tables_split_beside_its_total(box: dict[str, Any]) -> None:
    bid = _night(box, {"unmapped": {"lab": 1200, "medication": 3},
                       "unmapped_kinds": {"lab": LAB, "medication": {"code_unknown": 3, "unit_not_read": 0,
                                                                     "reference_data_not_reached": 0}}})  # fmt: skip
    r = TestClient(box["app"]).get(f"/api/v1/data/batches/{bid}", headers=_bearer(box, "stwk", "steward"))
    assert r.status_code == 200, r.text[:200]
    assert r.json()["unmapped"] == [
        {"table": "lab", "rows": 1200, "kinds": LAB},
        {"table": "medication", "rows": 3,
         "kinds": {"code_unknown": 3, "unit_not_read": 0, "reference_data_not_reached": 0}},
    ]  # fmt: skip


def test_a_night_recorded_before_the_split_answers_its_total_alone(box: dict[str, Any]) -> None:
    bid = _night(box, {"unmapped": {"lab": 4}})
    r = TestClient(box["app"]).get(f"/api/v1/data/batches/{bid}", headers=_bearer(box, "stwl", "steward"))
    assert r.json()["unmapped"] == [{"table": "lab", "rows": 4}]
