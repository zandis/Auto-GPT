"""NEW-B-7 (D-528): on a delta night, a row the mapping now leaves out takes its earlier record with it.

A booking's status changes to a code the map does not know. The mapping leaves the row out (D-587: never shown as
booked). On a delta night the snapshot is the night before merged with tonight's records: nothing was written for
the row and nothing was removed, so the lake went on showing the booking as ``booked`` until the next full load."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import pytest
from adapter.ndjson import TOMBSTONES, read_type, snapshot_dir
from adapter.pipeline import run_ingest

from tests.unit.test_dataflow_lake_p0 import _cfg, _Lakes

APPT = ["appt_no", "mrn", "staff_id", "dept_code", "appt_datetime", "duration_min", "status"]
VITAL = ["vital_no", "enc_no", "mrn", "measure_datetime", "height_cm", "weight_kg", "updated_at"]


def _write(path: Path, name: str, cols: list[str], rows: list[dict[str, str]]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with (path / f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def _appt(no: str, status: str) -> dict[str, str]:
    return {"appt_no": no, "mrn": "10000001", "staff_id": "S1", "dept_code": "MED",
            "appt_datetime": "2026-10-05T09:00:00", "duration_min": "15", "status": status}  # fmt: skip


def _status(lake_dir: Path, snap: str) -> dict[str, str]:
    return {r["id"]: r["status"] for r in read_type(snapshot_dir(lake_dir, snap), "Appointment")}


def test_a_booking_whose_status_became_unknown_is_not_shown_as_booked_after_a_delta_night(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _write(tmp_path / "full", "appointment", APPT, [_appt("A1", "B"), _appt("A2", "B")])
    run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False, validate=False)
    first = _status(cfg.lake_dir, "2026-10-01")
    assert sorted(first.values()) == ["booked", "booked"]
    # the next night: A1's status is a code the map does not know; A2 is cancelled
    _write(tmp_path / "delta", "appointment", APPT, [_appt("A1", "Z"), _appt("A2", "C")])
    with caplog.at_level(logging.INFO):
        rep = run_ingest(cfg, "csv", str(tmp_path / "delta"), since="2026-10-01", snapshot="2026-10-02",
                         load_fhir=False, validate=False)  # fmt: skip
    second = _status(cfg.lake_dir, "2026-10-02")
    assert sorted(second.values()) == ["cancelled"], second  # A1 is gone, never "booked" from the night before
    # the source did not delete it: it is not a tombstone, and OMOP will say "left the feed", not "deleted at the
    # source" (review MED-1)
    assert rep.tombstoned == 0 and not (snapshot_dir(cfg.lake_dir, "2026-10-02") / TOMBSTONES).exists()
    assert "records the feed's rows no longer give were removed: {'Appointment': 1}" in caplog.text


def test_a_row_that_still_maps_keeps_its_record_and_a_full_night_writes_no_tombstone(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _write(tmp_path / "full", "appointment", APPT, [_appt("A1", "B"), _appt("A2", "Z")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.tombstoned == 0 and not (snapshot_dir(cfg.lake_dir, "2026-10-01") / TOMBSTONES).exists()
    _write(tmp_path / "delta", "appointment", APPT, [_appt("A1", "A")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "delta"), since="2026-10-01", snapshot="2026-10-02",
                     load_fhir=False, validate=False)  # fmt: skip
    assert rep.tombstoned == 0 and sorted(_status(cfg.lake_dir, "2026-10-02").values()) == ["arrived"]


def test_a_measurement_taken_out_of_a_row_is_gone_and_the_rows_other_record_stays(tmp_path: Path) -> None:
    """One source row gives two records (height, weight), each under its own ``where``. The corrected row has no
    height any more: the height of the night before goes, the weight is replaced."""
    cfg = _cfg(tmp_path)

    def vital(height: str, weight: str) -> dict[str, str]:
        return {"vital_no": "V1", "enc_no": "E1", "mrn": "10000001", "measure_datetime": "2026-09-01T08:00:00",
                "height_cm": height, "weight_kg": weight, "updated_at": "2026-10-01"}  # fmt: skip

    def values(snap: str) -> list[float]:
        return sorted(r["valueQuantity"]["value"] for r in read_type(snapshot_dir(cfg.lake_dir, snap), "Observation"))

    _write(tmp_path / "full", "vital", VITAL, [vital("170", "60")])
    run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert values("2026-10-01") == [60, 170]
    _write(tmp_path / "delta", "vital", VITAL, [vital("", "61")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "delta"), since="2026-10-01", snapshot="2026-10-02",
                     load_fhir=False, validate=False)  # fmt: skip
    assert values("2026-10-02") == [61] and rep.tombstoned == 0


def test_a_rejected_row_removes_nothing_and_a_first_delta_night_has_nothing_to_remove(tmp_path: Path) -> None:
    """D-528, point 4: a row the box cannot read keeps the record of the night before (it is counted). And a delta
    night with no night before it (``since`` on an empty lake) removes nothing and writes no tombstone file."""
    cfg = _cfg(tmp_path)
    _write(tmp_path / "first", "appointment", APPT, [_appt("A0", "Z")])
    rep = run_ingest(cfg, "csv", str(tmp_path / "first"), since="2026-09-30", snapshot="2026-10-01",
                     load_fhir=False, validate=False)  # fmt: skip
    assert rep.tombstoned == 0 and not (snapshot_dir(cfg.lake_dir, "2026-10-01") / TOMBSTONES).exists()
    rows = [_appt(f"A{n}", "B") for n in range(1, 201)]
    _write(tmp_path / "full", "appointment", APPT, rows)
    run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-02", load_fhir=False, validate=False)
    bad = dict(_appt("A1", "C"), appt_datetime="not a time")  # one row of 200 the mapping cannot read
    _write(tmp_path / "delta", "appointment", APPT, [bad, *rows[1:]])
    rep = run_ingest(cfg, "csv", str(tmp_path / "delta"), since="2026-10-02", snapshot="2026-10-03",
                     load_fhir=False, validate=False)  # fmt: skip
    assert rep.passed and not rep.held
    assert sorted(_status(cfg.lake_dir, "2026-10-03").values()) == ["booked"] * 200  # A1 stays as it was


def test_the_last_of_two_rows_with_one_key_decides(tmp_path: Path) -> None:
    """Review LOW-2 (DATA-017: the last row wins): a booking sent twice in one night, first booked, then with a
    status the map does not know, is not shown as booked; the other order keeps it."""
    cfg = _cfg(tmp_path)
    _write(tmp_path / "full", "appointment", APPT, [_appt("A1", "B"), _appt("A2", "B")])
    run_ingest(cfg, "csv", str(tmp_path / "full"), snapshot="2026-10-01", load_fhir=False, validate=False)
    _write(tmp_path / "delta", "appointment", APPT,
           [_appt("A1", "A"), _appt("A1", "Z"), _appt("A2", "Z"), _appt("A2", "A")])  # fmt: skip
    run_ingest(cfg, "csv", str(tmp_path / "delta"), since="2026-10-01", snapshot="2026-10-02",
               load_fhir=False, validate=False)  # fmt: skip
    assert sorted(_status(cfg.lake_dir, "2026-10-02").values()) == ["arrived"]  # A2 only
