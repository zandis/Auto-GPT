"""F14 (D-810): a change-time column that holds no date is never the window of a delta night.

A source can write a placeholder (three letters) in a table's change-time column on every row. A delta night that
compares it with the night's start text by text keeps or drops rows by accident: letters sort after digits, a
compact date sorts before a dashed one. A row whose change time is not a date is now read every night (as one with
an empty change time is: a row read twice is merged by its key, a row skipped is a change lost), and counted per
table in the night's completeness with a warning. Synthetic rows only."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

import pytest
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import run_ingest
from adapter.sources.base import change_time_is_date
from adapter.sources.csv.source import CsvSource

from tests.unit.test_dataflow_lake_p0 import _cfg

DIAG = ["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status", "updated_at"]


def _feed(path: Path, rows: list[dict[str, str]]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    with (path / "diagnosis.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DIAG)
        w.writeheader()
        w.writerows(rows)
    return path


def _diag(no: str, updated: str) -> dict[str, str]:
    return {"diag_no": no, "enc_no": "E1", "mrn": "10000001", "icd10": "M10.9", "diag_date": "2026-09-01",
            "recorded_date": "2026-09-01", "status": "A", "updated_at": updated}  # fmt: skip


@pytest.mark.parametrize(("value", "is_date"), [
    ("2026-10-01", True), ("2026-10-01 08:30:00", True), ("2026/10/01", True), ("20261001", True),
    ("20261001083000", True), ("2026-10-01T08:30:00+08:00", True),
    ("XYZ", False), ("N/A", False), ("-", False), ("0", False), ("2026", False), ("10/01/2026", False),
])  # fmt: skip
def test_what_a_change_time_that_is_a_date_looks_like(value: str, is_date: bool) -> None:
    assert change_time_is_date(value) is is_date


def test_a_row_whose_change_time_is_not_a_date_is_read_and_counted(tmp_path: Path) -> None:
    d = _feed(tmp_path / "feed", [_diag("D1", "XYZ"), _diag("D2", "2026-09-30"), _diag("D3", "2026-10-02"),
                                  _diag("D4", "")])  # fmt: skip
    src = CsvSource(d)
    got = [r["diag_no"] for r in src.rows("diagnosis", "diagnosis", "updated_at", "2026-10-01")]
    assert got == ["D1", "D3", "D4"]
    assert src.change_time_not_a_date("diagnosis") == 1


def test_compact_change_times_are_compared_as_dates_not_as_text(tmp_path: Path) -> None:
    """``20260930`` sorted after ``2026-10-01`` as text and was read as changed; it is a day before."""
    d = _feed(tmp_path / "feed", [_diag("D1", "20260930"), _diag("D2", "20261002")])
    got = [r["diag_no"] for r in CsvSource(d).rows("diagnosis", "diagnosis", "updated_at", "2026-10-01")]
    assert got == ["D2"]


def test_the_delta_night_reports_the_rows_and_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    cfg = _cfg(tmp_path)
    feed = _feed(tmp_path / "feed", [_diag("D1", "XYZ"), _diag("D2", "XYZ")])
    run_ingest(cfg, "csv", str(feed), snapshot="2026-10-01", load_fhir=False, validate=False)
    with caplog.at_level(logging.WARNING):
        run_ingest(cfg, "csv", str(feed), since="2026-10-01", snapshot="2026-10-02", load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, "2026-10-02")
    assert len(list(read_type(folder, "Condition"))) == 2
    comp = json.loads((folder / "completeness.json").read_text(encoding="utf-8"))
    assert comp["tables"]["diagnosis"]["change_time_not_a_date"] == 2
    assert "diagnosis: 2 rows have a change time that is not a date" in caplog.text
    assert "XYZ" not in caplog.text  # a count, never the value
