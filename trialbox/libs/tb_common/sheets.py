"""Cells of a file a person opens in a spreadsheet: typed text is never a formula (NEW-CSV-1, D-549; CWE-1236).

A spreadsheet runs a CSV cell that begins with ``=``, ``+``, ``-`` or ``@`` (and, after a tab or a carriage return,
what follows) as a formula: a comment, a reason or a note typed by one person runs on the machine of the person who
opens the export. :func:`csv_cell` writes such a cell with a leading quote, which a spreadsheet shows as text. In
a workbook only a text that begins with ``=`` is stored as a formula (by ``openpyxl``); :func:`no_formulas` turns
every such cell back into text, characters unchanged. TrialBox's own workbooks that hold typed text have no formula
of their own, so none is lost.

Standard library only (``openpyxl`` is the caller's).
"""

from __future__ import annotations

from typing import Any

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: Any) -> str:
    """``value`` as a CSV cell a spreadsheet will not run."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def no_formulas(workbook: Any) -> int:
    """Every formula cell of the workbook becomes a text cell with the same characters; how many were changed.
    Call it once, just before the workbook is saved."""
    changed = 0
    for ws in workbook.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.data_type == "f":
                    c.data_type = "s"
                    changed += 1
    return changed
