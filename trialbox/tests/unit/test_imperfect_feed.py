"""H-34 (D-1100): the imperfect-feed generator and harness (``tools/imperfect_feed.py``).

The fast tests hold the generator (a clean export made up here, the same each time; every case builds its variant in
each of its formats and says why it skips the others), the page (its table is the tool's rendering of the committed
results) and the findings file (the register's ``--add-from`` form). The two last tests run the real adapter, as the
adapter's own tests do (a PostgreSQL of the suite): the clean export ingests through ``adapter run`` and its lake equals
what the generator says; a rejected date is counted and the night goes on; the same export twice does not double the
lake. They hold the harness, not a finding: a fix in the adapter changes the page, not these tests.
Synthetic data only; every feed is made in the test's own folder."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools import findings_register
from tools import imperfect_feed as imf

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs/plan/measurements/imperfect-feed-2026-11-18.md"
RECORD = ROOT / "docs/plan/measurements/imperfect-feed-2026-11-18"
RESULTS = RECORD / "results.json"
FINDINGS = RECORD / "findings.json"


@pytest.mark.nodb
def test_the_clean_export_is_made_up_here_and_the_same_each_time() -> None:
    one, two = imf.clean_export(), imf.clean_export()
    assert one == two
    assert set(one) == set(imf.TABLES)
    assert len(one["patient"]) == imf.N_PATIENTS
    for table, rows in one.items():
        assert rows, table  # the first night needs every table (NEW-DIN-8)
        assert all(set(r) == set(imf.COLUMNS[table]) for r in rows), table
        keys = [r[imf.KEYS[table]] for r in rows]
        assert len(keys) == len(set(keys)), table
    assert all(re.fullmatch(r"\d{8}", r["mrn"]) for r in one["patient"])  # the rehearsal's chart-number rule
    assert all(r["id_no"] == "" and r["phone"] == "" for r in one["patient"])  # no identifier is made, even a fake one


@pytest.mark.nodb
def test_each_fact_the_lake_keeps_is_one_tuple_so_a_doubled_or_changed_row_shows() -> None:
    truth = imf.truth_tuples("csv", b"k" * 32, imf.clean_export())
    assert truth and max(truth.values()) == 1
    rows = sum(len(imf.clean_export()[t]) for t in ("patient", "encounter", "diagnosis", "lab", "medication", "note"))
    assert sum(truth.values()) == rows


@pytest.mark.nodb
def test_every_case_applies_to_a_format_or_says_why_not() -> None:
    ids = [c.id for c in imf.CASES]
    assert len(ids) == len(set(ids))
    assert {c.family for c in imf.CASES} == set(imf.FAMILIES)
    for c in imf.CASES:
        assert set(c.formats) <= set(imf.FORMATS), c.id
        assert set(c.formats) | set(c.not_applicable) == set(imf.FORMATS), c.id
        assert not set(c.formats) & set(c.not_applicable), c.id
        assert c.expected and c.words, c.id


def _files(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.mark.nodb
@pytest.mark.parametrize("fmt", ["csv", "cgrd_sql", "fhir_bulk"])
def test_each_case_builds_a_variant_that_differs_from_the_clean_export(fmt: str, tmp_path: Path) -> None:
    clean = imf.clean_export()
    imf.write_feed(fmt, clean, tmp_path / "clean", tmp_path)
    before = _files(tmp_path / "clean")
    for case in (c for c in imf.CASES if fmt in c.formats):
        feed = case.build(fmt, clean, tmp_path / case.id, tmp_path)
        assert feed.path, case.id
        if case.nights == 1:  # the same export twice is the same bytes by design
            assert _files(tmp_path / case.id) != before, case.id
    assert clean == imf.clean_export()  # no case changed the clean export it was given


@pytest.mark.nodb
def test_the_ssmix2_cases_build_on_the_exporters_storage(tmp_path: Path) -> None:
    clean = imf.clean_export(8)
    for case in (c for c in imf.CASES if "ssmix2" in c.formats and c.nights == 1):
        if case.id.startswith(("two-charts", "cut-mid")):  # they need the full 50 (patient 50, a second chart)
            continue
        feed = case.build("ssmix2", clean, tmp_path / case.id, tmp_path)
        assert Path(feed.path).is_dir(), case.id


@pytest.mark.nodb
def test_the_hkscs_character_is_one_big5_cannot_write() -> None:
    ch = imf.hkscs_char()
    assert ch.encode("big5hkscs")
    with pytest.raises(UnicodeEncodeError):
        ch.encode("cp950")


@pytest.mark.nodb
def test_the_page_table_is_the_tools_rendering_of_the_committed_results() -> None:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert imf.table_markdown(results) in PAGE.read_text(encoding="utf-8")
    ran = {(r["case"], r["fmt"]) for r in results["runs"]}
    want = {(c.id, f) for c in imf.CASES for f in c.formats}
    assert ran == want  # every case in every format it applies to, no more
    assert set(results["not_built"]) == set(imf.NOT_BUILT)


@pytest.mark.nodb
def test_the_results_hold_no_scratch_path_and_no_chart_number() -> None:
    text = RESULTS.read_text(encoding="utf-8")
    assert "/root/" not in text and "/tmp/" not in text and "/var/tmp/" not in text
    assert not re.search(rf"\b{imf.MRN_BASE // 10000}\d{{4}}\b", text)


@pytest.mark.nodb
def test_the_findings_file_is_in_the_registers_add_from_form() -> None:
    doc = json.loads(FINDINGS.read_text(encoding="utf-8"))
    assert doc["card"] == "H34" and doc["source"] == str(PAGE.relative_to(ROOT))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    ran = {f"{r['case']}/{r['fmt']}" for r in results["runs"]}
    page = PAGE.read_text(encoding="utf-8")
    ids = [f["id"] for f in doc["findings"]]
    assert len(ids) == len(set(ids))
    for f in doc["findings"]:
        assert re.fullmatch(r"H34-\d{2}", f["id"]), f["id"]
        assert f["severity"] in ("High", "Medium", "Low"), f["id"]
        assert f["lane"] in findings_register.LANES, f["id"]
        assert f["basis"] == "shown" and f["state"] == "open", f["id"]
        assert f["claim"] and "\n" not in f["claim"] and "|" not in f["claim"], f["id"]
        assert f["runs"] and set(f["runs"]) <= ran, f["id"]  # each finding names the runs that show it
        assert f"| {f['id']} |" in page, f["id"]


def test_the_harness_runs_the_real_adapter(tmp_path: Path, db_url: str) -> None:
    """The clean export through ``adapter run`` equals the generator's truth; a date the mapping cannot read is one
    rejected row, counted with its reason, and the night is published with every good row; the same export the next
    night does not double the lake."""
    out = imf.run_all(tmp_path, ["csv"], ["date-zero", "twice-same-name"], workers=2)
    clean = out["clean"]["csv"]
    assert clean["exit"] == 0 and clean["equal_to_truth"], clean
    runs = {r["case"]: r for r in out["runs"]}
    date_zero = runs["date-zero"]
    assert date_zero["counted"]["diagnosis"]["rejected"] == {"MappingError: unparseable date <value>": 1}
    assert date_zero["served"] and date_zero["good_kept"] == "all" and date_zero["wrong_total"] == 0
    assert date_zero["feas"].startswith("ran")
    twice = runs["twice-same-name"]
    assert twice["served"] and twice["doubled"] == 0 and twice["wrong_total"] == 0 and twice["good_kept"] == "all"
