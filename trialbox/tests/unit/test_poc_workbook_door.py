"""PoC upload door (lane H item 1): one .xlsx workbook with nine Japanese-headed sheets loads through the adapter.

* The committed template workbook equals what ``tools/poc_workbook.py`` writes (so the binary is never hand-edited).
* The template loads end to end: canonical rows, FHIR resources, and the OMOP rows of the scores and the findings.
* A formula cell is a refused row (a warning, not a stop); a sheet over the row limit is refused whole; a missing
  sheet is reported as missing; a birth of year and month stays year and month; Japanese headers map by ``rename``.

All data is synthetic (case numbers ``SYN-...``, made-up names).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from adapter.mapping.engine import Mapping
from adapter.ndjson import read_all, read_type, snapshot_dir
from adapter.pipeline import COMPLETENESS, AdapterConfig, make_source, run_ingest
from adapter.sources.xlsx.source import XlsxSource
from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "services/adapter/mapping/poc/poc_workbook.yaml"
TEMPLATE = ROOT / "services/adapter/mapping/poc/poc_workbook_template.xlsx"
SNAP = "2026-11-01"
SHEETS = ("患者", "受診", "病名", "処方", "検査", "スコア", "所見", "画像レポート", "記録")
TABLE_OF = {
    "患者": "patient", "受診": "encounter", "病名": "diagnosis", "処方": "medication", "検査": "lab",
    "スコア": "score", "所見": "finding", "画像レポート": "report", "記録": "note",
}  # fmt: skip


@pytest.fixture(autouse=True)
def _site_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    """The workbook mapping states no zone: it reads the site's own (TB_TZ)."""
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")


def _cfg(tmp: Path) -> AdapterConfig:
    sec = tmp / "secrets"
    sec.mkdir(parents=True, exist_ok=True)
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    return AdapterConfig(
        lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=MAPPING, site_id="T", audit_dir=tmp / "audit",
        tz="Asia/Tokyo",
    )  # fmt: skip


def _night(tmp: Path, book: Path) -> Any:
    cfg = _cfg(tmp)
    rep = run_ingest(cfg, "xlsx", str(book), snapshot=SNAP, load_fhir=False, rebuild_lake=False, validate=False)
    return cfg, rep


def _tables(cfg: AdapterConfig) -> dict[str, dict[str, Any]]:
    """The run report's per-table counts (``completeness.json`` beside the snapshot)."""
    got = json.loads((snapshot_dir(cfg.lake_dir, SNAP) / COMPLETENESS).read_text(encoding="utf-8"))
    return dict(got["tables"])


def _copy(tmp: Path) -> Path:
    dest = tmp / "book.xlsx"
    shutil.copy(TEMPLATE, dest)
    return dest


def test_committed_template_is_what_the_generator_writes() -> None:
    from tools import poc_workbook

    assert TEMPLATE.read_bytes() == poc_workbook.build()


def test_template_has_nine_japanese_sheets_one_synthetic_row_each() -> None:
    wb = load_workbook(TEMPLATE, read_only=True, data_only=False)
    assert tuple(wb.sheetnames) == SHEETS
    for name in SHEETS:
        rows = list(wb[name].iter_rows(values_only=True))
        assert len(rows) == 2, name  # the header and ONE example row
        header = rows[0]
        case = rows[1][header.index("症例番号")]
        assert str(case).startswith("SYN-"), name  # every row carries a case number marked synthetic


def test_japanese_headers_map_by_rename() -> None:
    m = Mapping.load(MAPPING)
    src = make_source("xlsx", str(TEMPLATE))
    for sheet, table in TABLE_OF.items():
        spec = m.tables[table]
        assert spec["source"] == sheet
        row = next(iter(src.rows(table, sheet, None, None)))
        canon = m.normalize(table, row)
        assert set(spec["rename"].values()) <= set(canon), table
    patient = m.normalize("patient", next(iter(src.rows("patient", "患者", None, None))))
    assert patient["mrn"].startswith("SYN-") and patient["sex"] == "M"


def test_template_loads_end_to_end_to_canonical_and_resources(tmp_path: Path) -> None:
    cfg, rep = _night(tmp_path, TEMPLATE)
    assert not rep.errors
    tables = _tables(cfg)
    for table in TABLE_OF.values():
        assert tables[table]["present"] is True and tables[table]["rows"] == 1, table
    feed = read_all(snapshot_dir(cfg.lake_dir, SNAP))
    for rtype in ("Patient", "Encounter", "Condition", "MedicationRequest", "DiagnosticReport", "DocumentReference"):
        assert len(feed[rtype]) == 1, rtype
    obs = feed["Observation"]
    assert len(obs) == 3  # a lab result, a score, a finding


def test_birth_of_year_and_month_stays_year_and_month(tmp_path: Path) -> None:
    cfg, _ = _night(tmp_path, TEMPLATE)
    (patient,) = read_type(snapshot_dir(cfg.lake_dir, SNAP), "Patient")
    assert patient["birthDate"] == "1948-05"


def test_a_formula_cell_is_a_refused_row_not_a_stop(tmp_path: Path) -> None:
    book = _copy(tmp_path)
    wb = load_workbook(book)
    ws = wb["検査"]
    header = [c.value for c in ws[1]]
    ws.cell(row=2, column=header.index("結果") + 1).value = "=1+1"
    wb.save(book)
    src = XlsxSource(book)
    assert list(src.rows("lab", "検査", None, None)) == []
    (why,) = src.refused_rows("検査")
    assert why[0] == 2 and "formula" in why[1]
    cfg, _ = _night(tmp_path, book)
    tables = _tables(cfg)
    assert tables["lab"]["rows"] == 0 and tables["lab"]["refused_rows"] == 1
    assert tables["patient"]["rows"] == 1  # the other sheets load


def test_a_missing_sheet_is_reported_as_missing(tmp_path: Path) -> None:
    book = _copy(tmp_path)
    wb = load_workbook(book)
    del wb["所見"]
    wb.save(book)
    cfg, _ = _night(tmp_path, book)
    tables = _tables(cfg)
    assert tables["finding"]["present"] is False and tables["finding"]["rows"] == 0
    assert tables["score"]["rows"] == 1


def test_a_sheet_over_the_row_limit_is_refused_with_a_reason(tmp_path: Path, monkeypatch: Any) -> None:
    from adapter.sources.xlsx import source as xs

    book = tmp_path / "big.xlsx"
    wb = Workbook()
    ws = wb.create_sheet("患者")
    wb.remove(wb["Sheet"])
    ws.append(["症例番号", "氏名", "生年月", "性別"])
    for i in range(5):
        ws.append([f"SYN-{i:04d}", "テスト", "1950-01", "女"])
    wb.save(book)
    monkeypatch.setattr(xs, "MAX_ROWS", 3)
    src = XlsxSource(book)
    assert list(src.rows("patient", "患者", None, None)) == []
    assert "limit" in (src.refused_sheet("患者") or "")


def test_a_date_cell_with_a_month_format_is_read_as_year_and_month(tmp_path: Path) -> None:
    from datetime import datetime

    book = tmp_path / "ym.xlsx"
    wb = Workbook()
    ws = wb.create_sheet("患者")
    wb.remove(wb["Sheet"])
    ws.append(["症例番号", "氏名", "生年月", "性別"])
    ws.append(["SYN-0009", "テスト", datetime(1948, 5, 1), "男"])
    ws["C2"].number_format = "yyyy-mm"
    wb.save(book)
    (row,) = list(make_source("xlsx", str(book)).rows("patient", "患者", None, None))
    assert row["生年月"] == "1948-05"


def test_scores_and_findings_reach_omop(tmp_path: Path, db_url: str) -> None:
    from omop import schema
    from omop.load import load_batch

    cfg, _ = _night(tmp_path, TEMPLATE)
    feed = read_all(snapshot_dir(cfg.lake_dir, SNAP))
    db = schema.connect(db_url)
    try:
        load_batch(db, "feed", SNAP, feed, tz="Asia/Tokyo")
        meas = db.fetchall("SELECT measurement_source_value, value_as_number FROM measurement")
        assert ("MMSE", 24.0) in [(r[0], float(r[1])) for r in meas if r[1] is not None]
        obs = db.fetchall("SELECT observation_source_value, value_source_value FROM observation")
        assert any(r[0] == "FIND-HIPPO-ATROPHY" and r[1] for r in obs)
        person = db.fetchall("SELECT year_of_birth, month_of_birth, day_of_birth FROM person")
        assert person == [(1948, 5, None)]
    finally:
        db.close()
