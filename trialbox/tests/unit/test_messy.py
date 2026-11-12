"""TB-PLAN-04 step 5b (D-132): messy sheets, fix what is safe and ask the rest (``sitesetup.messy``, pure)."""

from __future__ import annotations

import pytest
from sitesetup import messy as m


@pytest.mark.parametrize(
    ("raw", "iso", "kind"),
    [
        ("2026-03-04", "2026-03-04", None),
        ("2026/3/4", "2026-03-04", "format"),
        ("2026年3月4日", "2026-03-04", "format"),
        ("20260304", "2026-03-04", "format"),
        ("令和5年4月1日", "2023-04-01", "era"),
        ("令和元年5月1日", "2019-05-01", "era"),
        ("R5.4.1", "2023-04-01", "era"),
        ("H31.4.30", "2019-04-30", "era"),
        ("平成元年1月8日", "1989-01-08", "era"),
        ("昭和45年3月2日", "1970-03-02", "era"),
        ("S45.3.2", "1970-03-02", "era"),
        ("民國112年3月15日", "2023-03-15", "minguo"),
        ("民國112/3/15", "2023-03-15", "minguo"),
        ("112/03/15", "2023-03-15", "minguo"),
        ("1120315", "2023-03-15", "roc7"),
        ("２０２６／３／４", "2026-03-04", "format"),
        ("令和５年４月１日", "2023-04-01", "era"),
        ("45237", "2023-11-07", "excel_serial"),
        ("25/03/2026", "2026-03-25", "dmy"),
        ("03/25/2026", "2026-03-25", "mdy"),
        ("04/04/2026", "2026-04-04", "format"),
        ("", None, None),
    ],
)
def test_dates_that_are_safe_to_fix(raw: str, iso: str | None, kind: str | None) -> None:
    p = m.parse_date(raw)
    assert (p.iso, p.kind, p.problem) == (iso, kind, None)


@pytest.mark.parametrize(
    ("raw", "problem"),
    [
        ("03/04/2026", "date_order"),  # 3 April or 4 March: never guessed
        ("3.4.26", "two_digit_year"),
        ("平成31年5月10日", "era_boundary"),  # the era had changed on 1 May 2019
        ("令和元年4月1日", "era_boundary"),
        ("2026-02-30", "date_unreadable"),
        ("next week", "date_unreadable"),
    ],
)
def test_ambiguous_dates_are_not_read(raw: str, problem: str) -> None:
    p = m.parse_date(raw)
    assert p.iso is None and p.problem == problem


def test_the_answer_reads_the_slashed_date() -> None:
    assert m.parse_date("03/04/2026", "dmy").iso == "2026-04-03"
    assert m.parse_date("03/04/2026", "mdy").iso == "2026-03-04"
    assert m.parse_date("平成31年5月10日").suggestion == "2019-05-10"
    assert m.infer_order(["03/04/2026", "25/12/2025"]) == "dmy"
    assert m.infer_order(["03/04/2026", "12/25/2025"]) == "mdy"
    assert m.infer_order(["03/04/2026"]) is None


def test_width_numbers_and_units() -> None:
    assert m.half_width("ＡＢＣ１２３　ｘ") == "ABC123 x"
    assert m.half_width("痛風ｶﾙﾃ") == "痛風ｶﾙﾃ"  # kana untouched
    assert m.parse_number("７．８") == (7.8, "")
    assert m.parse_number("8.4 mg/dl") == (8.4, "mg/dL")
    assert m.parse_number("<0.5") == (None, "")
    assert m.convert("urate", 500, "µmol/L") == (8.41, "mg/dL", True)
    assert m.convert("urate", 500, "umol/l") == (8.41, "mg/dL", True)
    assert m.convert("urate", 8.4, "mg/dL") == (8.4, "mg/dL", False)
    assert m.convert("hba1c", 53, "mmol/mol") == (7.0, "%", True)
    assert m.convert("urate", 8.4, "g/L") is None  # not a unit TrialBox knows for urate: asked
    assert m.unit_suggestion("urate", 8.4) == "mg/dL" and m.unit_suggestion("urate", 480) == "drop"
    assert m.analyte_of("尿酸値（mg/dL）") == "urate" and m.unit_in("尿酸値（mg/dL）") == "mg/dL"
    assert m.analyte_of("HbA1c") == "hba1c" and m.analyte_of("体重") == "weight"


def test_merged_cells_and_title_rows() -> None:
    grid = [["痛風外来 候補者リスト", "", ""], ["", "", ""], ["カルテ番号", "診断", "受診日"], ["001", "痛風", "2026-01-01"],
            ["002", "", "2026-01-02"]]  # fmt: skip
    out, fixes = m.unmerge(grid, [(3, 1, 4, 1)])
    assert out[4][1] == "痛風" and fixes[0].kind == "merged" and fixes[0].column == "B4:B5"
    assert m.find_header(out) == 2


def _messy() -> tuple[list[list[str]], list[tuple[int, int, int, int]]]:
    grid = [
        ["痛風外来 候補者リスト（2026年）", "", "", "", "", "", ""],
        ["カルテ番号", "氏名", "生年月日", "診断", "尿酸値", "単位", "受診日"],
        ["００１２３４５６", "山田 太郎", "昭和45年3月2日", "痛風", "７．８", "mg/dL", "03/04/2026"],
        ["00234567", "佐藤 花子", "民國60年5月6日", "", "500", "µmol/L", "25/03/2026"],
        ["", "鈴木", "1980-01-01", "痛風", "8.0", "mg/dL", "2026-02-01"],
        ["00345678", "田中", "H2.7.7", "高血圧", "6.1", "g/L", "2026-02-02"],
    ]
    return grid, [(2, 3, 3, 3)]  # the diagnosis cell merged over two rows


def test_clean_a_messy_sheet_fixes_what_is_safe() -> None:
    grid, merged = _messy()
    c = m.clean(grid, merged)
    assert c.header_row == 2 and c.dropped == ["氏名"]
    assert c.roles["カルテ番号"] == "chart_no" and c.roles["尿酸値"] == "lab" and c.roles["受診日"] == "date"
    kinds = {f.kind for f in c.fixes}
    assert {"header_row", "merged", "era", "minguo", "unit", "width"} <= kinds
    first = c.records[0]
    assert first.key == "00123456"  # full-width digits in the key made half-width (and never listed as a fix)
    assert first.values["生年月日"] == "1970-03-02" and first.values["尿酸値"] == "7.8"
    second = c.records[1]
    assert second.values["診断"] == "痛風"  # the merged cell, unmerged
    assert second.values["尿酸値"] == "8.41" and second.units["尿酸値"] == "mg/dL"
    assert second.values["生年月日"] == "1971-05-06" and second.values["受診日"] == "2026-03-25"  # 25 > 12: a day
    assert not any("山田" in f.before + f.after or "00123456" in f.before for f in c.fixes)


def test_clean_lists_the_rest_and_guesses_nothing() -> None:
    grid, merged = _messy()
    c = m.clean(grid, merged)
    keys = {k.key: k for k in c.checks}
    order = keys["date_order:受診日"]
    assert order.suggestion == "dmy"  # the column's own 25/03 says day first: suggested, not applied
    assert "受診日" not in c.records[0].values  # 03/04/2026 is left empty until a person answers
    unit = keys["unit:尿酸値|g/L"]
    assert unit.suggestion == "mg/dL" and "尿酸値" not in c.records[2].values
    assert "no_key:カルテ番号:5" in keys  # the row without a chart number (row 5 as Excel numbers it)
    # the person's answers re-run the same file
    answered = m.clean(
        grid, merged, answers={"date_order:受診日": "dmy", "unit:尿酸値|g/L": "drop", "no_key:カルテ番号:5": "drop"}
    )
    assert answered.records[0].values["受診日"] == "2026-04-03"
    assert not answered.checks
    assert "尿酸値" not in answered.records[2].values


def test_a_column_that_might_be_a_chart_number_is_held_back() -> None:
    grid = [["ID", "診断", "受診日"], ["12345678", "痛風", "2026-01-01"], ["23456789", "痛風", "2026-01-02"]]
    c = m.clean(grid)
    assert c.held == ["ID"] and [k.kind for k in c.checks] == ["chart_column", "no_key", "no_key"]
    assert c.checks[0].raw == "…"  # its values are never shown
    assert not c.records
    c2 = m.clean(grid, answers={"chart_column:ID": "chart_no"})
    assert [r.key for r in c2.records] == ["12345678", "23456789"] and not c2.checks
    c3 = m.clean(grid, roles={"ID": "chart_no"})
    assert len(c3.records) == 2


def test_summarise_groups_fixes() -> None:
    grid, merged = _messy()
    s = m.summarise(m.clean(grid, merged).fixes)
    era = next(x for x in s if x["kind"] == "era")
    assert era["column"] == "生年月日" and era["n"] == 2
