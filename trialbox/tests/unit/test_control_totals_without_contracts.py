"""P-25 (E2E R1): the export's ``control_totals.json`` was read only when data contracts were configured; the installed
box has none, so a feed cut short passed reconciliation unchecked and the gate said "no control totals shipped"
although the file was in the feed.

The totals are now reconciled whenever the file is shipped, counted as the rows stream past (no row kept in memory).
The class (RC5): a control the site shipped is read whenever its file exists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapter.pipeline import run_ingest

from tests.unit.test_dataflow_lake_p0 import _cfg, _csv, _row


def _totals(feed: Path, rows: int, patients: int | None = None) -> None:
    t: dict[str, Any] = {"rows": rows}
    if patients is not None:
        t |= {"distinct_patients": patients, "patient_column": "mrn"}
    (feed / "control_totals.json").write_text(json.dumps({"tables": {"diagnosis": t}}), encoding="utf-8")


def test_a_feed_short_of_its_control_totals_is_held_without_contracts(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)  # no contracts folder: the installed box's configuration
    _csv(tmp_path / "feed", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")])
    _totals(tmp_path / "feed", rows=3)  # the export says three rows; two arrived (a cut file)
    rep = run_ingest(cfg, "csv", str(tmp_path / "feed"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.held and not rep.passed
    assert any("control totals" in e and "export 3, read 2" in e for e in rep.errors or []), rep.errors


def test_totals_that_hold_let_the_night_pass(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _csv(tmp_path / "feed", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")])
    _totals(tmp_path / "feed", rows=2, patients=1)
    rep = run_ingest(cfg, "csv", str(tmp_path / "feed"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed, rep.errors


def test_a_wrong_patient_count_is_held_too(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _csv(tmp_path / "feed", [_row("D1", "2026-09-01"), _row("D2", "2026-09-02")])
    _totals(tmp_path / "feed", rows=2, patients=2)  # both rows are one patient's
    rep = run_ingest(cfg, "csv", str(tmp_path / "feed"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.held and any("control totals" in e for e in rep.errors or [])
