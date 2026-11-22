"""F-2 (H34-01, H34-03, H34-04): the CSV reader sets aside an export that is cut or has a row of the wrong width.

The imperfect-feed measurement of 2026-11-18 served a lab value cut short (no sample time) from a file cut inside its
last row, a note cut short from a file that ends inside a quoted field, and a row one field short with the missing
column taken as empty; nothing was counted and the night published. Each is now a file that is not a readable CSV:
quarantined as T-615b says (moved to ``quarantine/``, no row given, ``quarantine_reason`` names the file and the line,
never a cell's text), and the night is held. A clean export, a quoted field holding a line end, a last row with or
without its line end, a UTF-8 byte-order mark, a Big5 export and a header-only table are read as before.

All data is synthetic.
"""

from __future__ import annotations

from pathlib import Path

from adapter.ndjson import snapshot_dir
from adapter.pipeline import HELD, AdapterConfig, run_ingest
from adapter.sources.csv.source import QUARANTINE_DIR, CsvSource

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"

HEADER = b"lab_no,mrn,local_code,result_value,unit,sample_datetime\r\n"
ROWS = [
    b"L001,SYN-0001,CRE,1.18,mg/dL,2026-05-30 10:30:00\r\n",
    b"L002,SYN-0002,HBA1C,6.57,%,2026-05-22 11:00:00\r\n",
    b"L003,SYN-0003,GLU,104.25,mg/dL,2026-05-19 15:30:00\r\n",
]
CUT_VALUE = "6.5"  # the cut value: never in a reason


def _write(tmp: Path, data: bytes, name: str = "lab") -> CsvSource:
    (tmp / f"{name}.csv").write_bytes(data)
    return CsvSource(tmp)


def _set_aside(src: CsvSource, tmp: Path, name: str = "lab") -> str:
    rows = list(src.rows(name, name, None, None))
    why = src.quarantine_reason(name) or ""
    assert rows == [], "rows given from a file that is not a readable CSV"
    assert why.startswith(f"{name}.csv quarantined: not a readable CSV"), why
    assert (tmp / QUARANTINE_DIR / f"{name}.csv").is_file() and not (tmp / f"{name}.csv").exists()
    return why


def _read(src: CsvSource, name: str = "lab") -> list[dict[str, object]]:
    rows = list(src.rows(name, name, None, None))
    assert src.quarantine_reason(name) is None, src.quarantine_reason(name)
    return rows


# --- refused: H34-01, H34-03, H34-04 -------------------------------------------------------------------------------


def test_a_row_cut_inside_the_last_field_is_set_aside_not_served(tmp_path: Path) -> None:
    """H34-01: the file stops inside its last row (``6.57`` kept as ``6.5``, the unit and sample time gone)."""
    cut = HEADER + ROWS[0] + b"L002,SYN-0002,HBA1C,6.5"
    why = _set_aside(_write(tmp_path, cut), tmp_path)
    assert "the file ends inside its last row (line 3" in why, why
    assert CUT_VALUE not in why and "SYN-0002" not in why


def test_a_file_that_ends_inside_a_quoted_field_is_set_aside_not_served(tmp_path: Path) -> None:
    """H34-03: the last note is quoted (it holds a comma) and the file stops before its closing quote."""
    data = b'note_no,mrn,text\r\nN1,SYN-0001,stable\r\nN2,SYN-0002,"better today, walks'
    why = _set_aside(_write(tmp_path, data, "note"), tmp_path, "note")
    assert "line 3" in why, why
    assert "walks" not in why and "better" not in why


def test_a_row_one_field_short_is_set_aside_not_mapped_with_an_empty_column(tmp_path: Path) -> None:
    """H34-04: a row in the middle lacks its last field (the sample time); its line end is there."""
    short = ROWS[1].rsplit(b",", 1)[0] + b"\r\n"
    why = _set_aside(_write(tmp_path, HEADER + ROWS[0] + short + ROWS[2]), tmp_path)
    assert "line 3 has 5 fields where the header has 6" in why, why
    assert "SYN-0002" not in why


def test_a_row_one_field_more_is_set_aside_as_such(tmp_path: Path) -> None:
    """The same rule the other way (H34-18's case): a decimal comma makes one field more than the header."""
    extra = ROWS[1].replace(b",6.57,", b",6,57,")
    why = _set_aside(_write(tmp_path, HEADER + ROWS[0] + extra + ROWS[2]), tmp_path)
    assert "line 3 has 7 fields where the header has 6" in why, why
    assert "57" not in why


def test_a_cut_lab_export_holds_the_night_and_serves_no_cut_value(tmp_path: Path) -> None:
    """H34-01 through the adapter: the lab table is set aside, the night goes on with the others and is held."""
    feed = tmp_path / "feed"
    feed.mkdir()
    for f in SITE_A.glob("*.csv"):
        (feed / f.name).write_bytes(f.read_bytes())
    data = (feed / "lab.csv").read_bytes()
    last = data.rstrip(b"\r\n").rsplit(b"\n", 1)[1]
    value = last.split(b",")[4]
    (feed / "lab.csv").write_bytes(data[: data.rindex(last) + last.index(b"," + value + b",") + len(value)])
    sec = tmp_path / "secrets"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    cfg = AdapterConfig(
        lake_dir=tmp_path / "lake", secrets_dir=sec, mapping_path=MAPPING, site_id="T", audit_dir=tmp_path / "audit"
    )
    rep = run_ingest(cfg, "csv", str(feed), snapshot="2026-11-01", load_fhir=False, rebuild_lake=False, validate=False)
    assert rep.held and not rep.passed
    lab_errors = [e for e in rep.errors or [] if e.startswith("lab: lab.csv quarantined: not a readable CSV")]
    assert lab_errors and "the file ends inside its last row" in lab_errors[0], rep.errors
    assert (snapshot_dir(cfg.lake_dir, "2026-11-01") / HELD).is_file()


# --- read as before -------------------------------------------------------------------------------------------------


def test_a_clean_export_is_read_whole(tmp_path: Path) -> None:
    rows = _read(_write(tmp_path, HEADER + b"".join(ROWS)))
    assert [r["result_value"] for r in rows] == ["1.18", "6.57", "104.25"]


def test_a_complete_last_row_without_its_line_end_is_read(tmp_path: Path) -> None:
    rows = _read(_write(tmp_path, HEADER + b"".join(ROWS).rstrip(b"\r\n")))
    assert rows[-1]["sample_datetime"] == "2026-05-19 15:30:00"


def test_a_blank_line_after_the_last_row_is_no_row_and_no_cut(tmp_path: Path) -> None:
    rows = _read(_write(tmp_path, HEADER + b"".join(ROWS) + b"\r\n"))
    assert len(rows) == 3


def test_a_quoted_field_holding_a_line_end_is_one_field(tmp_path: Path) -> None:
    data = b'note_no,mrn,text\nN1,SYN-0001,"line one\nline two, still the note"\nN2,SYN-0002,short\n'
    rows = _read(_write(tmp_path, data, "note"), "note")
    assert [r["text"] for r in rows] == ["line one\nline two, still the note", "short"]


def test_a_utf8_byte_order_mark_is_not_part_of_the_first_column(tmp_path: Path) -> None:
    rows = _read(_write(tmp_path, b"\xef\xbb\xbf" + HEADER + b"".join(ROWS)))
    assert rows[0]["lab_no"] == "L001" and len(rows) == 3


def test_a_big5_export_is_read(tmp_path: Path) -> None:
    text = "note_no,mrn,text\r\n" + "".join(f"N{i},SYN-{i:04d},病人今日情況穩定，持續觀察。\r\n" for i in range(40))
    src = CsvSource(tmp_path, "big5")
    (tmp_path / "note.csv").write_bytes(text.encode("big5"))
    rows = _read(src, "note")
    assert len(rows) == 40 and rows[0]["text"] == "病人今日情況穩定，持續觀察。"


def test_a_table_with_only_its_header_is_empty_not_set_aside(tmp_path: Path) -> None:
    assert _read(_write(tmp_path, HEADER)) == []
    assert _read(_write(tmp_path, HEADER.rstrip(b"\r\n"), "note"), "note") == []
