"""Deep review 2026-11-13 (data), DATA-005: a CSV row whose field count differs from the header is not a record.

An export cut off mid-row (``L2,20000001,HBA1C,HbA1c,6`` where ``6.8,%,2026-09-01 ...`` was being written) was read
by ``csv.DictReader`` with ``None`` for the missing cells. The night passed; the lake held an undated HbA1c of 6 with
the mapping's default unit, and the OMOP load dated it the load night, so it became the newest HbA1c and flipped a
"latest HbA1c >= 7" criterion. Now the file is quarantined and the night held, as for an unreadable file (T-615b).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import run_ingest
from adapter.sources.csv.source import CsvSource

from tests.unit.test_dataflow_lake_p0 import _cfg

HEAD = "lab_no,mrn,local_code,item_name,result_value,unit,sample_datetime\r\n"
GOOD = "L1,20000001,HBA1C,HbA1c,9.1,%,2026-08-01 10:00:00\r\n"


@pytest.mark.parametrize(
    "last",
    [
        "L2,20000001,HBA1C,HbA1c,6",  # cut off: short
        "L2,20000001,HBA1C,HbA1c,6.8,%,2026-09-01 10:00:00,extra\r\n",  # a stray separator: long
    ],
)
def test_a_row_of_another_width_quarantines_the_file(tmp_path: Path, last: str) -> None:
    (tmp_path / "lab.csv").write_text(HEAD + GOOD + last, encoding="utf-8")
    src = CsvSource(tmp_path)
    assert list(src.rows("lab", "lab", None, None)) == []  # before: two rows, the second one cut
    why = src.quarantine_reason("lab") or ""
    assert "line 3" in why and "fields" in why, why


def test_blank_lines_and_quoted_newlines_are_not_short_rows(tmp_path: Path) -> None:
    body = HEAD + GOOD + "\r\n" + 'L3,20000001,NOTE,"two\r\nlines",1,%,2026-08-02 10:00:00\r\n'
    (tmp_path / "lab.csv").write_text(body, encoding="utf-8")
    src = CsvSource(tmp_path)
    assert len(list(src.rows("lab", "lab", None, None))) == 2
    assert src.quarantine_reason("lab") is None


def test_the_night_with_a_cut_off_lab_file_is_held(tmp_path: Path, db_url: str) -> None:
    cfg = _cfg(tmp_path)
    d = tmp_path / "full"
    d.mkdir()
    (d / "patient.csv").write_text(
        "mrn,name,id_no,birth_date,sex,death_date,phone\r\n20000001,Synth,X0,1970-01-01,F,,\r\n", encoding="utf-8"
    )
    (d / "lab.csv").write_text(HEAD + GOOD + "L2,20000001,HBA1C,HbA1c,6", encoding="utf-8")
    rep = run_ingest(cfg, "csv", str(d), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.held and not rep.passed, rep.errors  # before: passed, not held
    snap = snapshot_dir(cfg.lake_dir, "2026-10-01")
    assert not any(r.get("valueQuantity", {}).get("value") == 6 for r in read_type(snap, "Observation"))
