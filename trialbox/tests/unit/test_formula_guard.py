"""NEW-CSV-1 (D-549): typed text never becomes a formula in a file the console hands to a person.

A spreadsheet runs a cell that begins with ``=``, ``+``, ``-`` or ``@`` as a formula (CWE-1236). The audit report
and the copy-assist sheet wrote such a cell with a leading quote; the feedback export did not, and the workbooks
(the screening log, the registry export) stored a text that begins with ``=`` as a formula."""

from __future__ import annotations

import ast
import csv
import io
from pathlib import Path

import pytest
from console import feedback
from openpyxl import Workbook, load_workbook
from tb_common import sheets

ROOT = Path(__file__).resolve().parents[2]
BAD = ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\t=1+1", "\r=1+1", '=HYPERLINK("http://example.test","x")']
# the review: what a spreadsheet may still read as a formula although the first character is another: blanks or an
# invisible character before the sign, and the full-width signs a Japanese or Chinese keyboard types
SLY = [
    " =1+1",
    "\n=1+1",
    "\u3000=1+1",
    "\u200b=1+1",
    "\ufeff=1+1",
    "\uff1d1+1",
    "\uff0b1+1",
    "\uff0d1+1",
    "\uff20SUM(1)",
]

pytestmark = pytest.mark.nodb


def _entry(n: int, comment: str) -> feedback.Entry:
    return feedback.Entry(id=n, at="2026-11-13T00:00:00+00:00", path="/home", lang="en", role="coordinator",
                          account=f"user{n}", flag=None, rating=None, comment=comment)  # fmt: skip


def test_a_feedback_comment_is_never_a_formula_in_the_export() -> None:
    text = feedback.export_csv([_entry(i, c) for i, c in enumerate(BAD, 1)])
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == len(BAD)
    for row, typed in zip(rows, BAD, strict=True):
        for col, cell in row.items():
            assert not cell.startswith(sheets.FORMULA_START), (col, cell)
        assert row["comment"] == "'" + typed  # the words are all there, behind the quote
        assert typed in row["body"]  # the issue text keeps the comment; it begins with "Page:"


def test_plain_cells_are_left_as_they_are() -> None:
    row = next(csv.DictReader(io.StringIO(feedback.export_csv([_entry(1, "the list was slow on Monday")]))))
    assert row["comment"] == "the list was slow on Monday" and row["rating"] == "" and row["id"] == "1"
    assert sheets.csv_cell(None) == "" and sheets.csv_cell(12) == "12" and sheets.csv_cell("a=b") == "a=b"
    assert [sheets.csv_cell(b) for b in BAD] == ["'" + b for b in BAD]
    assert [sheets.csv_cell(b) for b in SLY] == ["'" + b for b in SLY]
    for plain in ("a - b", "1 + 1 = 2", "  two blanks then words", "\u3000name", "x@y.test"):
        assert sheets.csv_cell(plain) == plain


def test_a_workbook_keeps_typed_text_as_text() -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["reason", *BAD, 3, None])
    assert ws.cell(1, 2).data_type == "f"  # what the library does with a text that begins with =
    assert sheets.no_formulas(wb) == 2  # the two that begin with =; the others were text already
    buf = io.BytesIO()
    wb.save(buf)
    back = load_workbook(io.BytesIO(buf.getvalue())).active
    assert back is not None
    cells = list(next(back.iter_rows()))
    assert [c.value for c in cells[1 : 1 + len(BAD)]] == BAD  # every character as typed
    assert all(c.data_type != "f" for c in cells)
    assert cells[1].value == "=1+1" and cells[1 + len(BAD)].value == 3


def test_the_data_export_workbook_and_the_enrolment_report_keep_typed_text_as_text() -> None:
    """The review: two more files the console serves. An EDC text value and a withdrawal reason are typed."""
    from orchestrator import lifecycle_api

    typed = '=HYPERLINK("http://example.test","open")'
    rep = {"counts": dict.fromkeys(lifecycle_api.lc.STATES, 0), "ever": dict.fromkeys(lifecycle_api.lc.STATES, 0),
           "months": [], "screen_fail_reasons": {typed: 1, "+other": 2},
           "withdrawals": [{"record": "S-001", "day": "2026-11-01", "reason": typed}]}  # fmt: skip
    files = lifecycle_api.report_files(rep, "GZQO", "2026-11-13T00:00:00+00:00")
    for row in csv.reader(io.StringIO(files["csv"])):
        assert not [c for c in row if c.startswith(sheets.FORMULA_START)], row
    wb = load_workbook(io.BytesIO(files["xlsx"]))
    cells = [c for ws in wb.worksheets for r in ws.iter_rows() for c in r]
    assert not [c.coordinate for c in cells if c.data_type == "f"] and sum(c.value == typed for c in cells) == 2
    text = (ROOT / "services/datacore/export.py").read_text(encoding="utf-8")
    assert "sheets.no_formulas(wb)" in text.split("def xlsx(")[1]  # the EDC data workbook; its own test runs it


def test_every_csv_the_console_writes_is_guarded() -> None:
    """The review: the workbook scan saw no CSV. A console module that writes one uses the shared cell, or is one
    of the two that had the same rule of their own before this card."""
    own_rule = {"audit_page.py", "copy_assist_page.py"}
    for f in sorted((ROOT / "services" / "console").glob("*.py")):
        text = f.read_text(encoding="utf-8")
        if "csv.writer(" in text or "csv.DictWriter(" in text:
            assert "sheets.csv_cell(" in text or f.name in own_rule, f.name


#: a module that makes a workbook: the guard, or why none is needed. Read once, by a person.
WORKBOOKS = {
    "services/console/screening_log.py": "guard",
    "services/orchestrator/candidates.py": "guard",
    "services/orchestrator/lifecycle_api.py": "guard",  # the enrolment report
    "services/datacore/export.py": "guard",  # the EDC data workbook (lane E's file: one line)
}
#: makers of a workbook or a CSV outside this card (the orchestrator's reports, the data core's exports, site
#: set-up's templates): reported to the integrator on 2026-11-13, by reading; not judged here
NOT_THIS_CARD = {
    "services/deliverables/render.py", "services/orchestrator/reports/feasibility_xlsx.py",
    "services/orchestrator/reports/nav_xlsx.py", "services/orchestrator/reports/trial_sim_xlsx.py",
    "services/orchestrator/reports/candidate_xlsx.py", "services/sitesetup/help.py",
    "services/criteria_compiler/review.py",
}  # fmt: skip


def _makes_a_workbook(f: Path) -> bool:
    tree = ast.parse(f.read_text(encoding="utf-8"))
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "Workbook"
               for n in ast.walk(tree))  # fmt: skip


def test_every_workbook_the_console_and_the_registry_make_is_guarded_and_a_new_maker_is_named() -> None:
    found = {str(f.relative_to(ROOT)) for f in (ROOT / "services").rglob("*.py") if _makes_a_workbook(f)}
    assert found == set(WORKBOOKS) | NOT_THIS_CARD, sorted(found ^ (set(WORKBOOKS) | NOT_THIS_CARD))
    for rel in WORKBOOKS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert text.count("no_formulas(") >= text.count(".save("), rel  # each workbook saved is guarded first
