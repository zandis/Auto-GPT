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

from tb_common import encoding

from sitesetup import mapping, messy


class IntakeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


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
