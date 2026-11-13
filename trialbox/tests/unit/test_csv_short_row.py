"""Deep review 2026-11-13 (data), DATA-005: a CSV export cut off while writing its last line is not a record.

An export cut off mid-row (``L2,20000001,HBA1C,HbA1c,6`` where ``6.8,%,2026-09-01 ...`` was being written) was read
by ``csv.DictReader`` with ``None`` for the missing cells. The night passed; the lake held an undated HbA1c of 6 with
the mapping's default unit, and the OMOP load dated it the load night, so it became the newest HbA1c and flipped a
"latest HbA1c >= 7" criterion. Now a short last line with no line end quarantines the file and the night is held, as
for an unreadable file (T-615b). A short row that ends with its line end (an exporter that drops empty trailing
cells) and spaces-only or Ctrl-Z lines are read as before: other wrong-width rows are for STD-025's reject count.
"""

from __future__ import annotations

from pathlib import Path

from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import run_ingest
from adapter.sources.csv.source import CsvSource

from tests.unit.test_dataflow_lake_p0 import _cfg

HEAD = "lab_no,mrn,local_code,item_name,result_value,unit,sample_datetime\r\n"
GOOD = "L1,20000001,HBA1C,HbA1c,9.1,%,2026-08-01 10:00:00\r\n"
CUT = "L2,20000001,HBA1C,HbA1c,6"


def _rows(tmp_path: Path, body: str) -> tuple[list[dict[str, str]], str | None]:
    (tmp_path / "lab.csv").write_text(body, encoding="utf-8")
    src = CsvSource(tmp_path)
    return list(src.rows("lab", "lab", None, None)), src.quarantine_reason("lab")


def test_a_cut_off_last_line_quarantines_the_file(tmp_path: Path) -> None:
    rows, why = _rows(tmp_path, HEAD + GOOD + CUT)
    assert rows == []  # before: two rows, the second one cut
    assert why and "line 3 has 5 fields, the header 7" in why and "cut off" in why, why


def test_a_cut_off_line_before_a_dos_end_of_file_mark_is_cut_off_too(tmp_path: Path) -> None:
    rows, why = _rows(tmp_path, HEAD + GOOD + CUT + "\x1a")
    assert rows == [] and why


def test_short_rows_that_end_their_line_and_filler_lines_are_read_as_before(tmp_path: Path) -> None:
    body = HEAD + GOOD + "L2,20000001,HBA1C,HbA1c,6.8\r\n" + "   \r\n" + "\r\n" + "\x1a"
    rows, why = _rows(tmp_path, body)
    assert why is None
    assert [r["lab_no"] for r in rows] == ["L1", "L2"]  # the spaces-only and Ctrl-Z lines are no record


def test_quoted_newlines_and_a_last_line_without_a_line_end_are_fine(tmp_path: Path) -> None:
    body = HEAD + GOOD + 'L3,20000001,NOTE,"two\r\nlines",1,%,2026-08-02 10:00:00'
    rows, why = _rows(tmp_path, body)
    assert why is None and len(rows) == 2


def test_the_night_with_a_cut_off_lab_file_is_held(tmp_path: Path, db_url: str) -> None:
    cfg = _cfg(tmp_path)
    d = tmp_path / "full"
    d.mkdir()
    (d / "patient.csv").write_text(
        "mrn,name,id_no,birth_date,sex,death_date,phone\r\n20000001,Synth,X0,1970-01-01,F,,\r\n", encoding="utf-8"
    )
    (d / "lab.csv").write_text(HEAD + GOOD + CUT, encoding="utf-8")
    rep = run_ingest(cfg, "csv", str(d), snapshot="2026-10-01", load_fhir=False, validate=False)
    assert rep.held and not rep.passed, rep.errors  # before: passed, not held
    snap = snapshot_dir(cfg.lake_dir, "2026-10-01")
    assert not any(r.get("valueQuantity", {}).get("value") == 6 for r in read_type(snap, "Observation"))
