"""FU-DQD-NAMES: the data quality rows of the night's OMOP load are scrubbed of patient identifiers and typed
before they reach the night report, the audit event or the batch row. Synthetic identifiers only."""

from __future__ import annotations

import logging
import sys
import types
from typing import Any

import pytest
from datacore.dataops import omop_kept

CHART = "00123456"
NAME = "山田太郎"
DIRTY_NAME = f"plausible MRN {CHART}"
DIRTY_NOTE = f"患者 {NAME} さん"
ROW: dict[str, Any] = {
    "checkName": "plausibleAfterBirth",
    "cdmTableName": "condition_occurrence",
    "cdmFieldName": "condition_start_date",
    "numViolatedRows": 3,
    "numDenominatorRows": 1200,
    "status": "fail",
    "notes": "",
}


def _omop(*rows: Any, failed: Any = None) -> dict[str, Any]:
    return {
        "state": "loaded",
        "dqd": {"checks": 60, "fail": 1, "known": 0, "failed": list(rows) if failed is None else failed},
    }


def test_a_name_and_a_chart_number_in_a_check_row_do_not_stay() -> None:
    row = {**ROW, "checkName": DIRTY_NAME, "cdmFieldName": DIRTY_NAME, "cdmTableName": DIRTY_NAME, "notes": DIRTY_NOTE}
    got = omop_kept(_omop(row))["dqd"]["failed"][0]
    text = repr(got)
    assert CHART not in text and NAME not in text, text
    assert got["numViolatedRows"] == 3 and got["status"] == "fail"


def test_a_note_without_an_identifier_is_kept_as_written() -> None:
    row = {**ROW, "status": "known", "notes": "no SNOMED CT on the box"}
    assert omop_kept(_omop(row))["dqd"]["failed"] == [row]


def test_a_failed_that_is_not_a_list_is_dropped_with_a_counted_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="datacore.dataops"):
        got = omop_kept({"state": "loaded", "dqd": {"checks": 1, "fail": 0, "known": 0, "failed": f"{NAME} {CHART}"}})
    assert "failed" not in got["dqd"]
    assert any("1 data quality values were dropped" in r.getMessage() for r in caplog.records)
    assert NAME not in caplog.text and CHART not in caplog.text


def test_a_field_that_is_not_text_or_a_count_is_dropped_not_copied(caplog: pytest.LogCaptureFixture) -> None:
    row = {**ROW, "notes": {"who": NAME}, "checkName": ["x"], "numViolatedRows": "3", "numDenominatorRows": True}
    with caplog.at_level(logging.WARNING, logger="datacore.dataops"):
        got = omop_kept(_omop(row, "a text row", 7))["dqd"]["failed"]
    assert got == [{"cdmTableName": "condition_occurrence", "cdmFieldName": "condition_start_date", "status": "fail"}]
    assert any("6 data quality values were dropped" in r.getMessage() for r in caplog.records)
    assert NAME not in repr(got)


def test_the_night_report_rows_are_scrubbed_where_they_are_made(monkeypatch: pytest.MonkeyPatch) -> None:
    from adapter import dual_write

    dirty = {**ROW, "checkName": DIRTY_NAME, "notes": DIRTY_NOTE}
    fake = types.SimpleNamespace(
        run=lambda db: [dirty, {**ROW, "status": "pass"}], summary=lambda res: {"checks": 2, "fail": 1, "known": 0}
    )
    import omop

    monkeypatch.setattr(omop, "dqd", fake, raising=False)
    monkeypatch.setitem(sys.modules, "omop.dqd", fake)
    got = dual_write._dqd(object(), "2026-11-10")
    assert got is not None and len(got["failed"]) == 1
    assert CHART not in repr(got) and NAME not in repr(got)
