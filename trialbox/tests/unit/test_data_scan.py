"""The data-handling scan (D-203, WS-13.10, TST-SEC-10): every pattern finds its planted positive, the look-alikes stay
clean, hits are masked, archives and logs are scanned, data files outside their folders are refused, and the
allowlist needs a reason for every entry."""

from __future__ import annotations

import gzip
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
import yaml

from tools import data_scan as ds

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "data_scan"
NO_ALLOW = ds.Allow({}, [])
PATTERN_IDS = [p["id"] for p in yaml.safe_load(ds.PATTERNS.read_text(encoding="utf-8"))["patterns"]]


def _lines(path: Path) -> list[str]:
    return [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]


@pytest.fixture(scope="module")
def patterns() -> list[ds.Pattern]:
    return ds.load_patterns(exits=True)  # every pattern, the exits' too (D-747): each finds its planted positive


@pytest.mark.parametrize("pid", PATTERN_IDS)
def test_each_pattern_finds_its_planted_positive(pid: str, patterns: list[ds.Pattern]) -> None:
    planted = FIX / "positives" / f"{pid}.txt"
    assert planted.exists(), f"pattern {pid} has no planted positive"
    assert planted.read_text(encoding="utf-8").startswith("# PLANTED TEST POSITIVE")
    lines = _lines(planted)
    assert lines
    for line in lines:
        found = {h.pattern for h in ds.scan_text(line, "x", patterns, NO_ALLOW)}
        assert pid in found, f"{pid} missed a planted line ({ds.mask(line)})"


def test_every_planted_file_names_a_pattern() -> None:
    assert {p.stem for p in (FIX / "positives").glob("*.txt")} == set(PATTERN_IDS)


def test_the_look_alikes_are_clean(patterns: list[ds.Pattern]) -> None:
    """A pseudonym, LOINC codes, a ULID, an ISO date alone, CJK words beside a date, a wrong check digit, a timestamp,
    decimals, hex ids: none is a hit, without any allowlist."""
    for line in _lines(FIX / "negatives" / "clean.txt"):
        assert ds.scan_text(line, "x", patterns, NO_ALLOW) == [], line


def test_evasions_are_normalised(patterns: list[ds.Pattern]) -> None:
    for line, pid in [
        ("身分證 K23\u200b1415908", "tw_id"),  # a zero-width space inside
        ("病歷號 ３１４１５９２６", "chart_number"),  # full-width digits
        ("病歷號 3141 5926", "chart_number"),  # split by a space
        ("電話 080‒2468−1357", "jp_phone"),  # a figure dash and a minus sign
        ("ヤマダ タロウ 1960年1月2日生", "kana_name_dob"),  # a name in katakana
    ]:
        assert pid in {h.pattern for h in ds.scan_text(line, "x", patterns, NO_ALLOW)}, line


def test_check_digits() -> None:
    assert ds.tw_id_ok("A123456789") and not ds.tw_id_ok("A123456788")
    assert ds.tw_id_ok("K231415908") and ds.tw_id_ok("H827182807")  # 2nd digit 8: the new resident certificate
    assert ds.my_number_ok("123456789018") and not ds.my_number_ok("123456789019")
    assert ds.luhn_ok("01130012") and not ds.luhn_ok("01130013")


def test_a_hit_shows_the_first_and_last_two_characters_only(patterns: list[ds.Pattern]) -> None:
    [hit] = ds.scan_text("身分證字號 K231415908", "f.txt", patterns, NO_ALLOW)
    assert hit.shown == "K2******08"
    assert "K231415908" not in str(hit) and str(hit).startswith("f.txt:1: tw_id: ")
    assert ds.mask("黃美玲") == "黃**"


def test_archives_and_gzip_are_scanned_member_by_member(patterns: list[ds.Pattern]) -> None:
    line = "聯絡電話 0987-654-321\n".encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("bundle/logs/app.log")
        info.size = len(line)
        tf.addfile(info, io.BytesIO(line))
    hits = ds.scan_bytes(buf.getvalue(), "support-bundle.tgz", patterns, NO_ALLOW)
    assert [h.where for h in hits] == ["support-bundle.tgz!gunzip!bundle/logs/app.log"]
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr("logs/app.log", line)
    zipped = zbuf.getvalue()
    assert {h.pattern for h in ds.scan_bytes(zipped, "bundle.zip", patterns, NO_ALLOW)} == {"tw_phone"}
    assert ds.scan_bytes(gzip.compress(line), "x.ndjson.gz", patterns, NO_ALLOW)
    # by content, not by name: a zip inside a gzip, renamed
    assert {h.pattern for h in ds.scan_bytes(gzip.compress(zipped), "notes.txt", patterns, NO_ALLOW)} == {"tw_phone"}


def test_a_workbook_is_read_row_by_row_with_its_header(patterns: list[ds.Pattern]) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.create_sheet("export")
    ws.append(["病歷號", "姓名", "生日"])
    ws.append(["31415926", "黃美玲", "1957-04-21"])
    buf = io.BytesIO()
    wb.save(buf)
    found = {h.pattern for h in ds.scan_bytes(buf.getvalue(), "export.xlsx", patterns, NO_ALLOW)}
    assert {"chart_number", "cjk_name_dob"} <= found


def test_a_document_is_read_with_its_tables(patterns: list[ds.Pattern]) -> None:
    import docx

    d = docx.Document()
    d.add_paragraph("轉介單")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "MRN", "Phone"
    t.cell(1, 0).text, t.cell(1, 1).text = "31415926", "0987-654-321"
    buf = io.BytesIO()
    d.save(buf)
    found = {h.pattern for h in ds.scan_bytes(buf.getvalue(), "referral.docx", patterns, NO_ALLOW)}
    assert {"chart_number", "tw_phone"} <= found


def test_a_table_column_header_labels_its_values(patterns: list[ds.Pattern]) -> None:
    data = b"mrn,sex,phone\n31415926,F,0987-654-321\n"
    assert {"chart_number", "tw_phone"} <= {h.pattern for h in ds.scan_bytes(data, "x.csv", patterns, NO_ALLOW)}
    import pyarrow as pa
    import pyarrow.parquet as pq

    buf = io.BytesIO()
    pq.write_table(pa.table({"chart_no": ["31415926"], "name": ["黃美玲"], "dob": ["1957-04-21"]}), buf)
    found = {h.pattern for h in ds.scan_bytes(buf.getvalue(), "extract.parquet", patterns, NO_ALLOW)}
    assert {"chart_number", "cjk_name_dob"} <= found


def test_a_name_and_a_date_on_neighbouring_lines(patterns: list[ds.Pattern]) -> None:
    text = '{\n  "name": "黃美玲",\n  "gender": "female",\n  "birthDate": "1957-04-21"\n}\n'
    assert "cjk_name_dob" in {h.pattern for h in ds.scan_text(text, "x.json", patterns, NO_ALLOW)}


def test_legacy_encodings_and_utf16_are_read(patterns: list[ds.Pattern]) -> None:
    line = "病歷號 31415926 聯絡電話 0987-654-321\n"
    for data in (line.encode("big5"), (line + " ").encode("big5"), line.encode("cp932", errors="replace"),
                 line.encode("utf-16-le"), line.encode("utf-16")):  # fmt: skip
        found = {h.pattern for h in ds.scan_bytes(data, "x.txt", patterns, NO_ALLOW)}
        assert "tw_phone" in found, data[:20]


def test_an_unknown_binary_is_unscanned_and_a_known_one_is_skipped(patterns: list[ds.Pattern]) -> None:
    blob = b"\x00\x01\x02 MRN 31415926 \x00" * 50
    assert [h.pattern for h in ds.scan_bytes(blob, "dump.bin", patterns, NO_ALLOW)] == ["unscanned"]
    assert ds.scan_bytes(b"\x89PNG\r\n\x1a\n" + blob, "figure.png", patterns, NO_ALLOW) == []
    bad_zip = b"PK\x03\x04" + b"\x00" * 40
    assert [h.pattern for h in ds.scan_bytes(bad_zip, "x.zip", patterns, NO_ALLOW)] == ["unscanned"]


def test_a_data_file_outside_its_folders_is_refused() -> None:
    hits = ds.run([ROOT / "services" / "planted_by_test.csv", ROOT / "tests" / "fixtures" / "x" / "ok.csv"], ROOT)
    kinds = {(h.where, h.pattern) for h in hits}
    assert ("services/planted_by_test.csv", "data_file") in kinds
    assert not any(p == "data_file" and w.startswith("tests/") for w, p in kinds)


def test_the_hook_s_root_relative_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-commit hook runs from the repository root and passes trialbox/... names: the data-file rule and the
    path allowlist still see paths from trialbox/ (review H5)."""
    monkeypatch.chdir(ROOT.parent)
    planted = Path(ROOT.name) / "tests" / "fixtures" / "data_scan" / "positives" / "tw_id.txt"
    assert ds.main([str(planted)]) == 0  # allowlisted by its path from trialbox/
    csv_in_services = ROOT / "services" / "zz_hook_test.csv"
    csv_in_services.write_text("code,label\nA1,x\n", encoding="utf-8")
    try:
        assert ds.main([str(Path(ROOT.name) / "services" / "zz_hook_test.csv")]) == 2
    finally:
        csv_in_services.unlink()


def test_the_allowlist_needs_a_reason(tmp_path: Path) -> None:
    allow = tmp_path / "allow.txt"
    allow.write_text("value | tw_id | K231415908 |\n", encoding="utf-8")
    with pytest.raises(ds.ConfigError, match="reason"):
        ds.load_allow(allow)
    allow.write_text("value | tw_id | K231415908 | ok\n", encoding="utf-8")
    with pytest.raises(ds.ConfigError, match="reason"):
        ds.load_allow(allow)
    allow.write_text("value | no_such | K231415908 | a fake id of a generator\n", encoding="utf-8")
    with pytest.raises(ds.ConfigError, match="unknown pattern"):
        ds.load_allow(allow)
    allow.write_text("glob | * | x | a fake id of a generator\n", encoding="utf-8")
    with pytest.raises(ds.ConfigError, match="kind"):
        ds.load_allow(allow)
    allow.write_text(
        "# a comment\n\nvalue | tw_id | K231415908 | the fictional ID of a planted test\n", encoding="utf-8"
    )
    a = ds.load_allow(allow)
    assert ds.scan_text("K231415908", "x", ds.load_patterns(), a) == []


def test_the_repository_allowlist_loads_and_every_entry_has_a_reason() -> None:
    a = ds.load_allow()
    assert a.paths and a.values


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "tools.data_scan", *args], cwd=ROOT, capture_output=True, text=True,
                          check=False)  # fmt: skip


def test_cli_exit_codes_and_masked_output(tmp_path: Path) -> None:
    clean = _cli(str(FIX / "negatives"))
    assert clean.returncode == 0, clean.stdout
    planted = tmp_path / "copy.txt"  # outside the repository: no path allowlist applies
    planted.write_text((FIX / "positives" / "tw_id.txt").read_text(encoding="utf-8"), encoding="utf-8")
    hit = _cli(str(planted))
    assert hit.returncode == 2
    assert "tw_id" in hit.stdout and "K231415908" not in hit.stdout
    log = tmp_path / "make-test.log"
    log.write_text("PASSED tests/unit/x.py\n患者 黃美玲 1957-04-21 生\n", encoding="utf-8")
    logged = _cli("--log", str(log))
    assert logged.returncode == 2 and "cjk_name_dob" in logged.stdout and "黃美玲" not in logged.stdout


def test_a_broken_pattern_file_is_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = tmp_path / "p.yaml"
    bad.write_text("patterns:\n  - id: x\n    regex: '(['\n", encoding="utf-8")
    with pytest.raises(ds.ConfigError):
        ds.load_patterns(bad)
    monkeypatch.setattr(ds, "PATTERNS", bad)
    monkeypatch.setattr(ds.load_patterns, "__defaults__", (bad,))
    assert ds.main([str(FIX / "negatives")]) == 1


def test_the_hook_and_the_ci_job_run_the_scan() -> None:
    hook = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    entries = [h for r in hook["repos"] for h in r["hooks"]]
    assert any("data_scan" in h["entry"] for h in entries)
    assert "data-scan:" in (ROOT / "Makefile").read_text(encoding="utf-8")
