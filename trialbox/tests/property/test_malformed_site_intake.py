"""Card 10G-43 (OT-5): the site intake on malformed sheets (``sitesetup.intake``, as ``SetupService.add_sheet`` and
``reread`` call it: ``read_grid``, ``messy.clean``, ``refuse_chart_column``, then ``sheet_facts``).

A sheet is read, or refused with :class:`intake.IntakeError` (the setup route turns it into a 4xx). Inputs: CSV
bytes in the character sets the detector reads, damaged and real XLSX files (made here with openpyxl: merged cells,
dates, numbers, formulas, empty sheets), with generated column roles. Synthetic only: no sheet of a site is used.
"""

from __future__ import annotations

import contextlib
import io
from datetime import date, datetime

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from sitesetup import intake, messy

from tests.malformed_kit import MAX_INPUT, SETTINGS, Escaped, returns_or_refuses

_CSV_PIECES = [
    b"chart,birth,sex,dx,date\r\n", b"\xe7\x97\x85\xe6\xad\xb4\xe8\x99\x9f,\xe6\x80\xa7\xe5\x88\xa5\r\n", b",", b"\"",
    b"\"a,b\"", b"\r\n", b"\n", b"\x00", b"0001", b"1.0E+5", b"1960-01-01", b"1960/13/45", b"M", b"F", b"\xef\xbb\xbf",
    b"\x8eR\x93c", b"\xa4s\xa4j", b"\xff", b"=SUM(A1)", b"\t", b" ", b"E11.9", b"HbA1c", b"6.5", b"%",
]  # fmt: skip
#: a CSV without a CR inside a line: a bare CR in an unquoted cell is H10G43-05 (its own test below)
csvs = st.lists(st.sampled_from(_CSV_PIECES) | st.binary(max_size=3), max_size=60).map(
    lambda parts: b"".join(parts).replace(b"\r\n", b"\n").replace(b"\r", b"").replace(b"\n", b"\r\n")
)
_CELL = st.one_of(st.none(), st.integers(-(10**12), 10**12), st.floats(allow_nan=True, allow_infinity=True),
                  st.booleans(), st.text(max_size=10), st.dates(date(1900, 1, 1), date(2100, 1, 1)),
                  st.datetimes(datetime(1900, 1, 1), datetime(2100, 1, 1)),
                  st.sampled_from(["0001", "=1/0", "=A1", "#N/A", "1.0E+5", "chart", "性別"]))  # fmt: skip


@st.composite
def xlsxs(draw: st.DrawFn) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.worksheets[0]
    for row in draw(st.lists(st.lists(_CELL, max_size=6), max_size=6)):
        clean = []
        for v in row:  # openpyxl refuses control characters in a cell; the reader never sees such a file
            clean.append("".join(c for c in v if c >= " " or c in "\t\n") if isinstance(v, str) else v)
        ws.append(clean)
    for _ in range(draw(st.integers(0, 2))):
        r1, c1 = draw(st.integers(1, 6)), draw(st.integers(1, 6))
        r2, c2 = r1 + draw(st.integers(0, 3)), c1 + draw(st.integers(0, 3))
        with contextlib.suppress(ValueError):
            ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
    if draw(st.booleans()):
        wb.create_sheet("second")
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    if draw(st.integers(0, 4)) == 0:  # a damaged file
        i = draw(st.integers(0, 10**6)) % len(data)  # not drawn from len(data): a saved file's length varies
        data = data[:i] + bytes([data[i] ^ 0xFF]) + data[i + 1 :]
    return data


_ROLES = st.dictionaries(
    st.sampled_from(["chart", "birth", "sex", "dx", "date", "病歴號", "", "nope"]),
    st.sampled_from([*messy.ROLES, "bogus"]),
    max_size=4,
)


def _intake(name: str, data: bytes, roles: dict[str, str], pattern: str | None) -> None:
    grid, merged = intake.read_grid(name, data)
    cleaned = messy.clean(grid, merged, roles)
    intake.refuse_chart_column(name, data, cleaned, pattern)
    intake.sheet_facts(cleaned, lambda s: "P-" + s[:4])
    intake.preview_roles(grid, merged)


@SETTINGS
@given(
    st.one_of(
        st.tuples(st.just("sheet.csv"), csvs),
        st.tuples(st.sampled_from(["sheet.xlsx", "sheet.csv"]), xlsxs()),
        st.tuples(
            st.sampled_from(["sheet.csv", "sheet.xlsx", "x"]),
            st.binary(max_size=200).map(lambda b: b.replace(b"\r", b"")),
        ),
    ),
    _ROLES,
    st.sampled_from([None, r"^\d{8}$", r"^[A-Z]\d+$"]),
)
@example(("sheet.csv", b""), {}, None)
@example(("sheet.csv", b"PK"), {}, None)
@example(("sheet.csv", b"chart\r\n0001\r\n1.0E+5\r\n"), {"chart": "chart_no"}, r"^\d{4}$")
def test_intake_reads_or_refuses(sheet: tuple[str, bytes], roles: dict[str, str], pattern: str | None) -> None:
    name, data = sheet
    if len(data) > MAX_INPUT:
        return
    returns_or_refuses(lambda: _intake(name, data, roles, pattern), (intake.IntakeError,))


@SETTINGS
@given(st.just(b"a\rb\r\n"))
@example(b"chart\r\n" + b"a" * 131073 + b"\r\n")
@pytest.mark.xfail(strict=True, raises=Escaped, reason="H10G43-05: csv.Error leaves read_grid (a bare CR in an unquoted cell; a "
                                       "cell over the csv field limit), not IntakeError")  # fmt: skip
def test_h10g43_05_csv_errors_escape_the_intake(data: bytes) -> None:
    returns_or_refuses(lambda: _intake("sheet.csv", data, {}, None), (intake.IntakeError,))
