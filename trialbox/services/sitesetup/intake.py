"""Sheets and dumps into facts (D-131, D-132): a PI's Excel list or an IT department's CSV export.

:func:`read_grid` reads the file as the site saved it: XLSX (merged cells and all) or CSV in UTF-8, Shift_JIS or
Big5. :func:`sheet_facts` turns :func:`sitesetup.messy.clean`'s records into facts keyed by the pseudonym: the
chart number is turned into the pseudonym with the site key at once and never stored, name and phone columns are
dropped (listed), and every code of the site's own (a diagnosis code, a lab code, a lab column, a drug code, a
diagnosis written as words) becomes a local code for the once-per-site mapping. A sheet's facts are ``coded``: the
site's own records, used as is (D-131).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from tb_common import chartno, encoding

from sitesetup import mapping, messy


class IntakeError(ValueError):
    def __init__(self, code: str, message: str, column: str = "") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.column = column  # the column the refusal is about, as the sheet's header writes it (FIT-U09)


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def read_grid(name: str, data: bytes) -> tuple[messy.Grid, list[tuple[int, int, int, int]]]:
    """``(rows of strings, merged ranges)`` of the first sheet of an XLSX, or of a CSV."""
    if name.lower().endswith((".xlsx", ".xlsm")) or data[:2] == b"PK":
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(data), data_only=True)
        except Exception as exc:
            raise IntakeError("SHEET-READ", "this Excel file cannot be read") from exc
        ws = wb.worksheets[0]
        merged = [(r.min_row - 1, r.min_col - 1, r.max_row - 1, r.max_col - 1) for r in ws.merged_cells.ranges]
        grid = [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
        return grid, merged
    try:  # D-215: one detector for UTF-8, Shift_JIS and Big5; a file it cannot tell is refused, never guessed
        text, _ = encoding.decode(data)
    except encoding.EncodingRefused as exc:
        raise IntakeError("SHEET-READ", str(exc)) from exc
    return [list(r) for r in csv.reader(io.StringIO(text))], []


def _numeric_cells(data: bytes, col: int, header_row: int) -> bool:
    """Whether column ``col`` (0-based) of the first sheet of an XLSX holds a number cell below the header row
    (``header_row`` 1-based, counted as :func:`read_grid` counts): Excel stored a number there, so the leading zeros
    it had are gone."""
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(data), data_only=True).worksheets[0]
    for i, row in enumerate(ws.iter_rows(values_only=True)):  # the rows exactly as :func:`read_grid` reads them
        v = row[col] if i >= header_row and col < len(row) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
    return False


def refuse_chart_column(name: str, data: bytes, cleaned: messy.Cleaned, pattern: str | None = None) -> None:
    """FIT-U09 (T-629, D-415): a chart-number column that Excel turned into numbers is refused, naming the column,
    before anything of the sheet is stored. An XLSX column with a number cell is refused (Excel kept no zeros); in a
    CSV, where cells have no type, a value written as Excel writes a number, or one that matches the site's pattern
    only with leading zeros put back, is (``tb_common.chartno.column_refusal``). A wrong chart number is never guessed:
    the coordinator saves the column as text and uploads again."""
    key_col = next((h for h, r in cleaned.roles.items() if r == "chart_no"), None)
    if key_col is None or key_col not in cleaned.head:
        return
    idx = cleaned.head.index(key_col)
    xlsx = name.lower().endswith((".xlsx", ".xlsm")) or data[:2] == b"PK"
    why = "excel_number" if xlsx and _numeric_cells(data, idx, cleaned.header_row) else None
    why = why or chartno.column_refusal((r.key for r in cleaned.records), pattern)
    if why:
        raise IntakeError(
            "SHEET-CHARTNO",
            f"the chart-number column {key_col!r} holds numbers ({why}): the leading zeros are lost; save it as text",
            key_col,
        )


def sheet_facts(
    cleaned: messy.Cleaned, pseudonymise: Callable[[str], str]
) -> tuple[list[dict[str, str]], list[tuple[str, str, str, str]], list[str]]:
    """``(facts, local codes (domain, system, code, display), pseudonyms)`` of one cleaned sheet."""
    roles = cleaned.roles
    by_role: dict[str, list[str]] = {}
    for h, r in roles.items():
        by_role.setdefault(r, []).append(h)
    facts: list[dict[str, str]] = []
    locals_: dict[tuple[str, str, str], str] = {}
    pids: list[str] = []

    def local(domain: str, kind: str, code: str, display: str) -> tuple[str, str]:
        system = mapping.local_system(kind)
        code = mapping.norm_code(code)
        locals_.setdefault((domain, system, code), display[:200])
        return system, code

    for rec in cleaned.records:
        pid = pseudonymise(messy.half_width(rec.key).strip())
        if pid not in pids:
            pids.append(pid)
        v = rec.values
        day = next((v[h] for h in by_role.get("date", []) if v.get(h)), "")
        for h in by_role.get("birth_date", []):
            if v.get(h):
                facts.append(
                    {"pid": pid, "domain": "demographic", "code": "birth_date", "value": v[h], "status": "coded"}
                )
        for h in by_role.get("sex", []):
            if v.get(h):
                facts.append({"pid": pid, "domain": "demographic", "code": "sex", "value": v[h], "status": "coded"})
        text = next((v[h] for h in by_role.get("diagnosis", []) if v.get(h)), "")
        codes = [v[h] for h in by_role.get("diagnosis_code", []) if v.get(h)]
        if codes:
            for c in codes:
                sy, cd = local("condition", "dx-code", c, text)
                facts.append(
                    {
                        "pid": pid,
                        "domain": "condition",
                        "term": text,
                        "local_system": sy,
                        "local_code": cd,
                        "day": day,
                        "status": "coded",
                    }
                )
        elif text:
            sy, cd = local("condition", "dx-text", text, text)
            facts.append(
                {
                    "pid": pid,
                    "domain": "condition",
                    "term": text,
                    "local_system": sy,
                    "local_code": cd,
                    "day": day,
                    "status": "coded",
                }
            )
        lab_code = next((v[h] for h in by_role.get("lab_code", []) if v.get(h)), "")
        for h in by_role.get("lab", []):
            if not v.get(h):
                continue
            if lab_code:
                sy, cd = local("observation", "lab-code", lab_code, rec.analytes.get(h) or h)
            else:
                sy, cd = local("observation", "lab-column", h, h)
            facts.append(
                {
                    "pid": pid,
                    "domain": "observation",
                    "term": rec.analytes.get(h) or h,
                    "local_system": sy,
                    "local_code": cd,
                    "value": v[h],
                    "unit": rec.units.get(h, ""),
                    "day": day,
                    "status": "coded",
                }
            )
        name = next((v[h] for h in by_role.get("drug_name", []) if v.get(h)), "")
        dcodes = [v[h] for h in by_role.get("drug_code", []) if v.get(h)]
        if dcodes:
            for c in dcodes:
                sy, cd = local("medication", "drug-code", c, name)
                facts.append(
                    {
                        "pid": pid,
                        "domain": "medication",
                        "term": name,
                        "local_system": sy,
                        "local_code": cd,
                        "day": day,
                        "status": "coded",
                    }
                )
        elif name:
            sy, cd = local("medication", "drug-name", name, name)
            facts.append(
                {
                    "pid": pid,
                    "domain": "medication",
                    "term": name,
                    "local_system": sy,
                    "local_code": cd,
                    "day": day,
                    "status": "coded",
                }
            )
    return facts, [(d, s, c, disp) for (d, s, c), disp in locals_.items()], pids


def preview_roles(grid: messy.Grid, merged: messy.Merged = ()) -> dict[str, str]:
    """The roles TrialBox would give each column (the page shows them before the import; a person can change any)."""
    c = messy.clean(grid, merged)
    return {h: c.roles.get(h, "dropped" if h in c.dropped else "held") for h in c.head}
