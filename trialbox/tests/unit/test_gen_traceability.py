"""tools/gen_traceability.py (TB-PLAN-05 §7.4): the matrix is derived from the plan's tables and the plan is consistent."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from tools import gen_traceability as gt

SAMPLE = """
### WS-01 Hardening

| ID | Item | Acceptance | Depends on | Owner | Size | Trace | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WS-01.1 | a | b | — | agent | 2 S, 1.5 R | URS-PI-01, RSK-01; TST-E2E-01 | G1 |
| WS-01.2 | c | d | — | agent | 1 S | URS-PI-01, URS-ADM-01, RSK-02; TST-SEC-01 | G2 |

### Totals

| Workstream | Agent sessions | Owner and reviewer hours |
| --- | --- | --- |
| WS-01 old | 9 | 9 |
| **All** | **9 agent sessions** | **9 owner and reviewer hours**, plus the engineer |

| ID | Requirement | FS | Plan |
| --- | --- | --- | --- |
| URS-PI-01 | r1 | FS-06 | WS-99.9 |
| URS-ADM-01 | r2 | FS-13 | WS-01.2 |

| ID | Hazard | Harm |
| --- | --- | --- |
| RSK-01 | h | x |
| RSK-02 | h | x |

| ID | Level | What |
| --- | --- | --- |
| TST-E2E-01 | E | e |
| TST-SEC-01 | S | s |
"""


def test_rows_carry_fs_and_level_and_derive_the_plan_column() -> None:
    plan = gt.parse(SAMPLE)
    rows = gt.rows(plan)
    assert {r["requirement"] for r in rows} == {"URS-PI-01", "URS-ADM-01"}
    first = next(r for r in rows if r["plan_item"] == "WS-01.1")
    assert first["fs"] == "FS-06" and first["level"] == "E" and first["evidence"] == "gate: G1"
    assert gt.derive_urs_plan(plan)["URS-PI-01"] == ["WS-01.1", "WS-01.2"]
    assert not gt.orphans(plan)


def test_rewrite_replaces_the_plan_cells_and_the_totals() -> None:
    plan = gt.parse(SAMPLE)
    plan.engineer_hours = ", plus the engineer"
    new = gt.rewrite(SAMPLE, plan)
    assert "| URS-PI-01 | r1 | FS-06 | WS-01.1, WS-01.2 |" in new
    assert "| WS-01 Hardening | 3 | 1.5 |" in new
    assert "| **All** | **3 agent sessions** | **1.5 owner and reviewer hours**, plus the engineer |" in new
    assert "| WS-01 old |" not in new


def test_orphans_are_named() -> None:
    plan = gt.parse(SAMPLE.replace("| RSK-02 | h | x |\n", "").replace("| TST-SEC-01 | S | s |\n", ""))
    errs = gt.orphans(plan)
    assert "RSK used but undefined: RSK-02" in errs
    assert "TST used but undefined: TST-SEC-01" in errs


def test_the_committed_plan_and_matrix_are_consistent() -> None:
    assert gt.main(["--check"]) == 0


# ---------------------------------------------------------------------------------------------- commitments (T-641)
SRC = """# Pack

### A.1 Scope

| Topic | Control |
| --- | --- |
| Opt-out | removed within minutes |
| Audit | signed daily |

Mail carries pseudonyms only. Nothing leaves the hospital.

### A.2 End

Not a promise in scope.
"""
SOURCES = (("pack.md", "### A.1 Scope", "### A.2 End"),)


def _row(id_: str, quote: str, status: str = "amber", **kw: str) -> dict[str, str]:
    base = {f: "" for f in gt.COMMIT_FIELDS}
    base.update(id=id_, source="pack.md", quote=quote, status=status, card="T-1")
    base.update(kw)
    return base


def _root(tmp_path: Path) -> Path:
    (tmp_path / "pack.md").write_text(SRC, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_signed():\n    pass\n", encoding="utf-8")
    return tmp_path


def test_promise_units_are_table_rows_and_sentences_without_headers() -> None:
    assert gt.promise_units(SRC, "### A.1 Scope", "### A.2 End") == [
        "Opt-out | removed within minutes",
        "Audit | signed daily",
        "Mail carries pseudonyms only.",
        "Nothing leaves the hospital.",
    ]


def test_every_promise_needs_a_row(tmp_path: Path) -> None:
    root = _root(tmp_path)
    rows = [_row("A", "Opt-out |"), _row("B", "Audit | signed"), _row("C", "Mail carries"), _row("D", "Nothing leaves")]
    assert gt.commitment_errors(rows, SOURCES, root) == []
    errs = gt.commitment_errors(rows[:-1], SOURCES, root)
    assert errs == ["commitments: a promise in pack.md has no row: 'Nothing leaves the hospital.'"]


def test_a_row_must_quote_its_source_as_it_reads_now(tmp_path: Path) -> None:
    root = _root(tmp_path)
    rows = [_row("A", "Opt-out |"), _row("B", "Audit | signed"), _row("C", "Mail carries"), _row("D", "Nothing leaves")]
    (root / "pack.md").write_text(SRC.replace("Nothing leaves the hospital.", "Little leaves the hospital."), "utf-8")
    errs = gt.commitment_errors(rows, SOURCES, root)
    assert any(e.startswith("commitments: D: the quote is not in pack.md") for e in errs)
    assert any("has no row: 'Little leaves the hospital.'" in e for e in errs)


def test_green_needs_a_test_that_exists_and_red_needs_a_correction(tmp_path: Path) -> None:
    root = _root(tmp_path)
    good = _row("A", "Opt-out |", "green", code="x.py", test="tests/test_x.py::test_signed", card="")
    missing = _row("B", "Audit | signed", "green", code="x.py", test="tests/test_x.py::test_gone", card="")
    bare = _row("C", "Mail carries", "green", card="")
    red = _row("D", "Nothing leaves", "red")
    errs = gt.commitment_errors([good, missing, bare, red], SOURCES, root)
    assert errs == [
        "commitments: B: test 'tests/test_x.py::test_gone' not found",
        "commitments: C: green needs code and a test",
        "commitments: D: red needs the correction wording for the supplement",
    ]
    assert gt.commitment_errors([_row("A", "Opt-out |", "amber", card="")], (), root) == [
        "commitments: A: amber needs the card that finishes it"
    ]


def test_the_committed_register_has_the_22_irb_rows_and_no_problem() -> None:
    rows, errs = gt.read_commitments()
    assert errs == [] and gt.commitment_errors(rows) == []
    irb = [r["id"] for r in rows if re.fullmatch(r"IRB-(CGMH|JP)-\d\d", r["id"])]
    assert len(irb) == 22 and len(set(irb)) == 22


def test_the_generator_fails_when_a_promise_loses_its_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows, _ = gt.read_commitments()
    short = tmp_path / "commitments.csv"
    with short.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=gt.COMMIT_FIELDS)
        w.writeheader()
        w.writerows(r for r in rows if r["id"] != "IRB-CGMH-08")
    monkeypatch.setattr(gt, "COMMITMENTS", short)
    assert gt.main(["--check"]) == 1
