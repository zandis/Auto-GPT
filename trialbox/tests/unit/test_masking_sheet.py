"""Card F-3 (rc1 checklist row 9): the masking sheet, ``docs/validation/masking-sheet.md``.

* The sheet's tables are the tool's rendering of the committed ``results.json``: a number changed in either, or a row
  dropped from the sheet, turns this red.
* The results name the master commit they ran on, add up, and hold no identifier: only the harness's forms and the
  shapes of their values.
* Every open register row on masking is on the sheet.
* V5-01's remainder (a kanji surname outside the masker's list directly before 様, 先生 or 殿) is a strict expected
  failure: it turns red the day the masker masks it.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from tools import data_scan
from tools import masking_leaks as ml
from tools import masking_sheet as ms

pytestmark = pytest.mark.nodb

RES = ms.load()
SHEET = ms.SHEET_PATH.read_text(encoding="utf-8")
OPEN_ROWS = ("V5-01", "V5-02", "V5-03", "V5-13", *(f"J10C1-0{i}" for i in range(1, 6)), "R22-23", "R22-21")
CELL = ("probes", "masked", "partly", "leaked", "tripwire_missed")


def test_the_sheet_tables_are_the_rendering_of_the_committed_results() -> None:
    assert ms.check() == []


def test_check_sees_a_dropped_row_and_a_changed_number(tmp_path: Path) -> None:
    sheet, results = tmp_path / "sheet.md", tmp_path / "results.json"
    shutil.copy(ms.SHEET_PATH, sheet)
    shutil.copy(ms.RESULTS_PATH, results)
    assert ms.check(sheet, results) == []
    lines = SHEET.splitlines(keepends=True)
    i = next(n for n, line in enumerate(lines) if line.startswith("| name | kanji_様 |"))
    sheet.write_text("".join(lines[:i] + lines[i + 1 :]), encoding="utf-8")
    assert ms.check(sheet, results) == ["forms-ja"]
    shutil.copy(ms.SHEET_PATH, sheet)
    results.write_text(ms.RESULTS_PATH.read_text(encoding="utf-8").replace('"commit": "', '"commit": "0', 1), "utf-8")
    assert ms.check(sheet, results) == ["run"]


def test_the_results_name_the_master_commit_they_ran_on() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", RES["commit"])
    assert re.fullmatch(r"[0-9a-f]{40}", RES["masker_blob"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", RES["date"])
    assert RES["command"] == ms.COMMAND
    assert f"`{RES['commit']}`" in SHEET


def test_the_results_add_up() -> None:
    for row in RES["forms"]:
        for sc in ms.SCOPES:
            c = row.get(sc)
            if c is None:
                continue
            assert c["probes"] == c["masked"] + c["partly"] + c["leaked"] > 0, (row["form"], sc)
            assert c["leaked_per_1000"] == ms.per_thousand(c["leaked"], c["probes"]), (row["form"], sc)
        assert "in" in row or row["kind"] == "name", row["form"]
    assert RES["totals"] == ms.totals(RES["forms"])
    assert RES["v5_01"]["probes"] == len(ms.v5_01_probes()) == 24
    assert len(RES["v5_01"]["readable_shapes"]) == RES["v5_01"]["readable"]
    for lang, r in RES["r22_23"].items():
        cats = r["categories"].values()
        assert r["probes"] == sum(c["probes"] for c in cats) == ms.R22_23_PER * len(ms.R22_23[lang])
        assert r["missed"] == sum(c["missed"] for c in cats)
    assert set(RES["j10c1"]) == set(ms.J10C1_ROWS)


def _strings(x: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
    if isinstance(x, dict):
        return [s for k, v in x.items() for s in _strings(v, (*path, k))]
    if isinstance(x, list):
        return [s for v in x for s in _strings(v, path)]
    return [(path, x)] if isinstance(x, str) else []


def test_the_results_hold_no_identifier_outside_the_harness_set() -> None:
    """Every form is one of the harness's and its example is the shape of the harness's own value for it; no shape
    holds a digit; the data scan finds nothing in the results or the sheet."""
    forms = {(lang, form) for lang in ms.SHEET_LANGS for _k, form, _g in ml.forms(lang)}
    assert {(r["lang"], r["form"]) for r in RES["forms"]} <= forms
    assert all(r["example"] == ms.example(r["lang"], r["form"]) for r in RES["forms"])
    meta = {"card", "commit", "masker_blob", "date", "command", "entry_point"}
    digits = [(p, s) for p, s in _strings(RES) if p[0] not in meta and p[-1] != "form" and re.search("[0-9０-９]", s)]
    assert digits == []
    patterns, allow = data_scan.load_patterns(), data_scan.load_allow()
    for path in (ms.RESULTS_PATH, ms.SHEET_PATH):
        assert data_scan.scan_text(path.read_text(encoding="utf-8"), str(path), patterns, allow) == []


def test_every_open_masking_row_is_on_the_sheet_with_its_measure() -> None:
    m = ms.block("rows").search(SHEET)
    assert m is not None
    on_sheet = re.findall(r"^\| ([A-Z0-9]+-\d+) \|", m.group(2), re.M)
    assert sorted(on_sheet) == sorted(OPEN_ROWS)


def test_each_language_has_its_table_and_its_forms_known_to_pass() -> None:
    for lang in ms.SHEET_LANGS:
        for name in (f"forms-{lang}", f"pass-{lang}"):
            m = ms.block(name).search(SHEET)
            assert m is not None and m.group(2).count("\n| ") >= 1, name


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V5-01: a kanji surname outside the masker's list directly before 様, 先生 or 殿 stays readable",
)
def test_an_unlisted_kanji_surname_before_an_honorific_is_masked() -> None:
    eng = ml.engines()
    assert ms.v5_01_readable(eng.mask, eng.mask_char) == []
