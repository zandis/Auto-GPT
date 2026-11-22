"""Card F-3 (rc1 checklist row 9): the masking sheet, ``docs/validation/masking-sheet.md``.

* The sheet's tables are the tool's rendering of the committed ``results.json``, and the committed results are what
  a fresh run on this checkout gives (the commit and the date aside): a number changed in either, a form dropped, or
  a row dropped from the sheet turns this red.
* Every rate on the sheet is its own cell's (masked and leaked per 1,000, or the probe count on a small cell),
  recomputed here, not by the tool.
* The results name the master commit, the blobs and the site pattern they ran with, add up, and hold no identifier:
  exactly the harness's forms and the shapes of their values.
* Every open masking row of the findings register is on the sheet, read from the register.
* V5-01's remainder (a kanji surname outside the masker's list directly before 様, 先生 or 殿): its probes are exactly
  these, its surnames are outside the masker's list, and it is a strict expected failure that turns red the day the
  masker masks it.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from tb_common.phi_guard import JP_SURNAMES

from tools import data_scan
from tools import masking_leaks as ml
from tools import masking_sheet as ms

pytestmark = pytest.mark.nodb

RES = ms.load()
SHEET = ms.SHEET_PATH.read_text(encoding="utf-8")
REGISTER = ms.ROOT / "docs/handover/findings-register.md"
REVIEW_ROWS = {"R22-21", "R22-23"}  # the plan 10 review's rows, not in the register
SHA = re.compile(r"[0-9a-f]{40}")
V5_01_TEXTS = [
    f"{pre}{fam}{given}{suffix}来院。"
    for pre in ("", "本日")
    for suffix in ("様", "先生", "殿")
    for fam, given in (("丸山", "陽子"), ("大塚", "翔太"), ("吉川", "美咲"), ("今井", "健一"))
]


def _body(name: str) -> str:
    m = ms.block(name).search(SHEET)
    assert m is not None, name
    return m.group(2)


def _table(name: str) -> list[list[str]]:
    """The rows of the generated table ``name`` (header and rule dropped), as stripped cells."""
    lines = [x for x in _body(name).splitlines() if x.startswith("| ")]
    return [[c.strip() for c in x.strip("|").split("|")] for x in lines[1:]]


def _rate(k: int, n: int) -> str:
    return f"{n} probes" if n < 20 else f"{round(1000 * k / n, 1)}"


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
    text = ms.RESULTS_PATH.read_text(encoding="utf-8")
    results.write_text(text.replace('"master": "', '"master": "0', 1), encoding="utf-8")
    assert ms.check(sheet, results) == ["run"]


def test_a_fresh_run_gives_the_committed_results() -> None:
    """The measurement again, in process (29 s on this box; the test fails at 60 s): every figure, form, shape, blob
    and the site pattern equal the committed results; only the run's commit and date may differ."""
    t0 = time.monotonic()
    fresh = ms.run(ml.engines())
    assert time.monotonic() - t0 < 60
    drop = ("commit", "date")
    assert {k: v for k, v in fresh.items() if k not in drop} == {k: v for k, v in RES.items() if k not in drop}


def test_the_results_name_the_master_commit_and_what_the_run_depends_on() -> None:
    c = RES["commit"]
    assert SHA.fullmatch(c["master"])
    assert set(c["measured_files_differ"]) <= set(ms.MEASURED)
    assert "libs/tb_common/phi_guard.py" not in c["measured_files_differ"]
    assert list(RES["blobs"]) == list(ms.BLOBS) and all(SHA.fullmatch(b) for b in RES["blobs"].values())
    assert RES["site_mrn_regex"]
    assert RES["entry_point"] == ms.ENTRY_POINT and not re.search(r"\.py:\d", RES["entry_point"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", RES["date"])
    assert RES["command"] == ms.COMMAND
    assert f"`{c['master']}`" in SHEET and f"`{RES['site_mrn_regex']}`" in SHEET


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
    assert set(RES["j10c1"]) == {*ms.J10C1_ROWS, "J10C1-06"}


def test_every_rate_on_the_sheet_is_its_own_cells_rate() -> None:
    """Masked and leaked per 1,000 recomputed from the counts beside them; a cell under 20 probes shows its count."""
    for lang in ms.SHEET_LANGS:
        rows = [r for r in _table(f"forms-{lang}") if r[3] != "-"]
        assert len(rows) == sum(1 for r in RES["forms"] if r["lang"] == lang and "in" in r)
        for r in rows:
            n, masked, partly, leaked = (int(x) for x in r[3:7])
            assert n == masked + partly + leaked, r
            assert (r[7], r[8]) == (_rate(masked, n), _rate(leaked, n)), r
        for r in _table(f"pass-{lang}"):
            assert r[6] == _rate(int(r[3]), int(r[5])), r
    for r in _table("summary"):
        n, masked, partly, leaked = (int(x) for x in r[2:6])
        assert n == masked + partly + leaked and (r[6], r[7]) == (_rate(masked, n), _rate(leaked, n)), r
    for k, n, _r in re.findall(r"(\d+) of (\d+) [a-z ]+\(([\d.]+) per 1,000\)", SHEET):
        assert int(n) >= 20, (k, n)


def test_the_results_hold_exactly_the_harness_forms_and_no_identifier() -> None:
    """The forms are the harness's held forms, each once; each example is the shape of the harness's own value for
    it; no shape holds a digit; the data scan finds nothing in the results or the sheet."""
    held = [(lang, form) for lang in ms.SHEET_LANGS for _k, form, _g in ml.forms(lang) if form not in ml.NOT_HELD]
    assert [(r["lang"], r["form"]) for r in RES["forms"]] == sorted(
        held, key=lambda x: (ms.SHEET_LANGS.index(x[0]), ms.KIND_ORDER.index(_kind(*x)))
    )
    assert all(r["example"] == ms.example(r["lang"], r["form"]) for r in RES["forms"])
    meta = {"card", "commit", "blobs", "site_mrn_regex", "date", "command", "entry_point"}
    digits = [
        (p, s)
        for p, s in _strings(RES)
        if p[0] not in meta and p[-1] not in ("form", "kind") and re.search("[0-9０-９]", s)
    ]
    assert digits == []
    patterns, allow = data_scan.load_patterns(), data_scan.load_allow()
    for path in (ms.RESULTS_PATH, ms.SHEET_PATH):
        assert data_scan.scan_text(path.read_text(encoding="utf-8"), str(path), patterns, allow) == []


def _kind(lang: str, form: str) -> str:
    return next(k for k, f, _g in ml.forms(lang) if f == form)


def _strings(x: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
    if isinstance(x, dict):
        return [s for k, v in x.items() for s in _strings(v, (*path, k))]
    if isinstance(x, list):
        return [s for v in x for s in _strings(v, path)]
    return [(path, x)] if isinstance(x, str) else []


def test_every_open_masking_row_of_the_register_is_on_the_sheet() -> None:
    """The register's open V5 and J10C1 rows (cards V-5 and 10C-1, the masker's), read from the register, and the
    review's R22-21 and R22-23: each on the sheet once, with a figure; a row that leaked nothing says only that."""
    register = REGISTER.read_text(encoding="utf-8")
    open_rows = set(re.findall(r"^\| ((?:V5|J10C1)-\d+) \|.*\| open \|$", register, re.M))
    assert {"V5-01", "V5-13", "J10C1-01"} <= open_rows
    rows = _table("rows")
    assert sorted(r[0] for r in rows) == sorted(open_rows | REVIEW_ROWS)
    for row, _what, fig in rows:
        assert re.search(r"\d+ of \d+", fig), row
        if fig.startswith("0 of"):
            assert re.fullmatch(r"0 of \d+ leaked on this run(; \d+ partly masked)?", fig), row


def test_the_v5_01_probes_are_exactly_these() -> None:
    assert [t for t, _a, _b in ms.v5_01_probes()] == V5_01_TEXTS


def test_the_v5_01_surnames_are_harness_names_outside_the_masker_list() -> None:
    surnames = {fam for fam, _g in ms.V5_01_NAMES}
    assert surnames <= {f[0] for f in ml.JA_FAMILY}
    assert surnames.isdisjoint(JP_SURNAMES)
    for text, a, b in ms.v5_01_probes():
        assert text[a:b] in surnames, text


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V5-01: a kanji surname outside the masker's list directly before 様, 先生 or 殿 stays readable",
)
def test_an_unlisted_kanji_surname_before_an_honorific_is_masked() -> None:
    eng = ml.engines()
    assert ms.v5_01_readable(eng.mask, eng.mask_char) == []
