"""NEW-B-6 (D-527): a number the mapping cannot compute is a rejected row, not the end of the night.

The night caught ``ValueError`` only (STD-025). A lab value of thirty digits is a number ``Decimal`` reads and
cannot compute with at its precision: the mapper raises ``decimal.InvalidOperation``, an ``ArithmeticError``, and
the whole night ended on one row of one table."""

from __future__ import annotations

import csv
import json
import logging
import shutil
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import reject_key, run_ingest

from tests.unit.test_dataflow_lake_p0 import _cfg, _Lakes

LAB = ["lab_no", "enc_no", "mrn", "local_code", "item_name", "sample_datetime", "result_value", "unit",
       "result_status", "updated_at"]  # fmt: skip
LONG = "123456789012345678901234567890"  # thirty digits: stands for a feed value, never written outside the store


def _labs(path: Path, values: list[str], unit: str = "mg/dL") -> None:
    path.mkdir(parents=True, exist_ok=True)
    with (path / "lab.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LAB)
        w.writeheader()
        for n, value in enumerate(values):
            w.writerow({"lab_no": f"L{n}", "enc_no": "E1", "mrn": "10000001", "local_code": "CRE",
                        "item_name": "creatinine", "sample_datetime": "2026-09-01T08:00:00", "result_value": value,
                        "unit": unit, "result_status": "final", "updated_at": "2026-09-01"})  # fmt: skip


def test_a_thirty_digit_lab_value_is_one_rejected_row_and_the_night_goes_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _labs(tmp_path / "n1", ["0.9"] * 150 + [LONG])  # one bad row in 151: under the 1 % that holds a night
    with caplog.at_level(logging.DEBUG):
        rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.passed and not rep.held
    folder = snapshot_dir(cfg.lake_dir, "2026-10-01")
    assert len(list(read_type(folder, "Observation"))) == 150  # the table went on; the row is not in the snapshot
    comp = json.loads((folder / "completeness.json").read_text(encoding="utf-8"))
    assert comp["tables"]["lab"]["rejected"] == {"InvalidOperation: a number the mapping cannot compute": 1}
    written = json.dumps(comp) + "\n".join(rep.errors or []) + caplog.text
    written += (folder / "ingest_report.json").read_text(encoding="utf-8")
    assert LONG not in written and LONG[:8] not in written


@pytest.mark.nodb
def test_the_key_of_an_arithmetic_error_is_its_type_and_one_fixed_sentence() -> None:
    with pytest.raises(InvalidOperation) as got:
        _ = Decimal(LONG) % 1
    assert reject_key(got.value) == "InvalidOperation: a number the mapping cannot compute"
    assert reject_key(ZeroDivisionError("division by zero")) == "ZeroDivisionError: a number the mapping cannot compute"
    assert reject_key(OverflowError("int too large to convert to float")) == (
        "OverflowError: a number the mapping cannot compute"
    )


def test_a_look_up_factor_that_is_not_a_number_ends_the_night_before_any_row(tmp_path: Path) -> None:
    """Review HIGH: the factor of a look-up row is parsed per lab row. With the catch widened, a factor typed
    wrongly would reject every row of that analyte each night under a key that blames the feed, and never hold
    the night while the analyte is under 1 % of the table. A fault of the mapping is found before the first row."""
    import dataclasses

    from adapter.pipeline import check_lookup_factors

    site = tmp_path / "site"
    shutil.copytree(Path(_cfg(tmp_path).mapping_path).parent, site)
    table = site / "lab_local_to_loinc.csv"
    text = table.read_text(encoding="utf-8")
    assert "mg/dL,1,laboratory" in text
    table.write_text(text.replace("mg/dL,1,laboratory", "mg/dL,1x,laboratory", 1), encoding="utf-8")
    cfg = dataclasses.replace(_cfg(tmp_path), mapping_path=site / Path(_cfg(tmp_path).mapping_path).name)
    _labs(tmp_path / "n1", ["0.9"] * 3)
    with pytest.raises(ValueError, match="look-up lab.*factor"):
        run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert not snapshot_dir(cfg.lake_dir, "2026-10-01").exists()
    from adapter.mapping.engine import Mapping

    check_lookup_factors(Mapping.load(_cfg(tmp_path).mapping_path))  # the shipped mapping: every factor is a number


def test_the_first_load_rejects_the_row_too(tmp_path: Path, db_url: str) -> None:
    """Review MED: the back-fill's row loop caught ValueError only, as the night's did."""
    from adapter.backfill import backfill

    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    _labs(tmp_path / "n1", ["0.9"] * 150 + [LONG])
    rep = backfill(cfg, "csv", str(tmp_path / "n1"), snapshot="2026-10-01", validate=False)
    assert rep.rejected == {"lab": 1}, (rep.state, rep.errors)
