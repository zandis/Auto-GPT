"""NEW-UX-3b (D-699, the rest of deep-review UX-003): the enrolment workbook is read in the reader's language.

The enrolment workbook (states now and ever, months, screen-failure reasons, withdrawals) was machine words
(`candidate`, `screen_fail`, a withdrawal reason as `3`) whatever the user's language. It now opens on a sheet for
people: the same tables with the page's words, dates as dates, laid out to print. The machine sheets stay, `states`
first, for the systems that read them. All data is synthetic."""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from console.i18n import translate
from console.lifecycle_pages import printable_report
from openpyxl import Workbook, load_workbook


def _machine() -> bytes:
    wb = Workbook()
    ws: Any = wb.active
    ws.title = "states"
    ws.append(["state", "now", "ever"])
    ws.append(["candidate", 4, 9])
    ws.append(["screen_fail", 1, 2])
    mo = wb.create_sheet("months")
    mo.append(["month", "approached", "screen_fail"])
    mo.append(["2026-11", 3, 1])
    sf = wb.create_sheet("screen_fail")
    sf.append(["reason", "count"])
    sf.append(["declined", 1])
    wd = wb.create_sheet("withdrawals")
    wd.append(["record", "day", "reason"])
    wd.append(["GZQO-001", "2026-11-11", "3"])
    ab = wb.create_sheet("about")
    ab.append(["study", "GZQO"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_the_workbook_opens_on_the_report_in_the_readers_language() -> None:
    wb = load_workbook(io.BytesIO(printable_report(_machine(), "ja")))
    ws: Any = wb.active
    assert wb.sheetnames[0] == "states" and ws.title == translate("ja", "enrol.xlsx.sheet")
    cells = [c for row in ws.iter_rows(values_only=True) for c in row if c is not None]
    for key in ("life.state.candidate", "life.state.screen_fail", "life.reason.sf.declined", "life.reason.wd.3"):
        assert translate("ja", key) in cells, key
    assert not {"candidate", "screen_fail", "declined"} & {str(c) for c in cells}
    wd = [r for r in ws.iter_rows(values_only=True) if r and r[0] == "GZQO-001"]
    assert wd and wd[0][2] == translate("ja", "life.reason.wd.3")  # the reason in words, never "3"
    assert date(2026, 11, 11) in [c.date() if hasattr(c, "date") else c for c in cells]
    assert ws.page_setup.orientation == "portrait" and ws.page_setup.fitToWidth == 1
    assert ws.sheet_properties.pageSetUpPr.fitToPage


def test_the_machine_sheets_stay_as_they_were() -> None:
    wb = load_workbook(io.BytesIO(printable_report(_machine(), "zh-TW")))
    assert {"states", "months", "screen_fail", "withdrawals", "about"} <= set(wb.sheetnames)
    assert next(wb["states"].iter_rows(values_only=True)) == ("state", "now", "ever")


def test_a_file_that_is_not_the_report_is_given_back_as_it_was() -> None:
    assert printable_report(b"not a workbook", "ja") == b"not a workbook"


def test_every_word_of_the_sheet_is_in_three_languages() -> None:
    from console.i18n_life import EN, JA, ZH

    keys = {"enrol.xlsx.sheet", "enrol.xlsx.states", "enrol.xlsx.now", "enrol.xlsx.ever", "enrol.xlsx.months",
            "enrol.xlsx.month", "enrol.xlsx.screen_fail", "enrol.xlsx.reason", "enrol.xlsx.count",
            "enrol.xlsx.withdrawals", "enrol.xlsx.record", "enrol.xlsx.day"}  # fmt: skip
    for cat in (EN, JA, ZH):
        assert keys <= set(cat)


# ------------------------------------------------------------------ the adversarial review
def test_the_same_report_gives_the_same_bytes() -> None:
    """Review finding: the file stays byte-reproducible (the orchestrator's normalisation, SPEC 11.2)."""
    data = _machine()
    assert printable_report(data, "ja") == printable_report(data, "ja")


def test_the_printed_sheet_names_the_study_and_starts_on_its_first_row() -> None:
    wb = load_workbook(io.BytesIO(printable_report(_machine(), "en")))
    ws: Any = wb.active
    first = [c for c in next(ws.iter_rows(values_only=True)) if c is not None]
    assert first and "GZQO" in [str(c) for c in first]


def test_a_report_of_another_shape_is_handed_over_as_it_came() -> None:
    wb = Workbook()
    ws: Any = wb.active
    ws.title = "states"
    ws.append(["state"])
    ws.append([])  # a short row
    for n in ("months", "screen_fail", "withdrawals"):
        wb.create_sheet(n).append(["x"])
    wb["withdrawals"].append(["only one cell"])
    buf = io.BytesIO()
    wb.save(buf)
    assert printable_report(buf.getvalue(), "ja") == buf.getvalue()
