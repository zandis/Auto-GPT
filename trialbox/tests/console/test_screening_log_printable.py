"""NEW-UX-3 (D-698, deep-review UX-003): the screening log a site prints is in the reader's language.

The screening-log workbook (the ICH E6 log a site prints or hands to the trial office and the monitor) was English
machine codes whatever the user's language, with dates as text, no column widths, no frozen header, no print titles,
and an "about" sheet in UTC. Its first sheet is now the log for people: headings and words in the reader's language,
dates as dates, laid out to print (landscape, one page wide, the header on every page). The machine-readable sheets
stay as they were, for the systems that read them. All data is synthetic."""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from console.i18n import translate
from openpyxl import load_workbook

from tests.console.test_amendment_rescreen import _screen
from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - the fixture is used by name
from tests.console.test_prescreen_log import PW, A, B, _csrf, _row


def _log(box: dict[str, Any], lang: str) -> Any:  # noqa: F811
    _screen(box, 9801, "3.0.0", [_row(A), _row(B)], 0)
    box["users"].create("pi", "investigator", PW, "pi@hospa.test")
    box["users"].create("crc", "coordinator", PW, "crc@hospa.test")
    name_pi(box, "pi")
    pi, _ = login(box["app"], "pi", PW)
    week = pi.get("/studies/GZQO/week").text
    r = pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(week), "mark": "approach"})
    assert r.status_code in (200, 303), r.text[:300]
    crc, ccsrf = login(box["app"], "crc", PW)
    assert crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": ccsrf, "outcome": "reached_booked"})
    crc.post("/lang", data={"csrf": ccsrf, "lang": lang, "back": "/"})
    return load_workbook(io.BytesIO(crc.get("/studies/GZQO/screening-log.xlsx").content))


def test_the_first_sheet_is_the_log_in_the_readers_language_laid_out_to_print(box: dict[str, Any]) -> None:  # noqa: F811
    wb = _log(box, "ja")
    ws = wb.worksheets[0]
    assert ws.title == translate("ja", "log.xlsx.sheet")
    head = [c.value for c in ws[1]]
    assert head[0] == translate("ja", "log.no") and translate("ja", "log.xlsx.col.pi_mark") in head
    row = [c.value for c in ws[2]]
    assert translate("ja", "mark.approach") in row and translate("ja", "outcome.reached_booked") in row
    assert "approach" not in row and "reached_booked" not in row  # no machine code a person reads
    assert any(isinstance(v, (date, datetime)) for v in row)  # dates are dates
    assert ws.freeze_panes == "A2" and ws.print_title_rows in ("1:1", "$1:$1")
    assert ws.page_setup.orientation == "landscape" and ws.page_setup.fitToWidth == 1
    assert ws.sheet_properties.pageSetUpPr.fitToPage
    assert all((ws.column_dimensions[c.column_letter].width or 0) >= 8 for c in ws[1])


def test_the_machine_sheets_stay_as_they_were(box: dict[str, Any]) -> None:  # noqa: F811
    wb = _log(box, "zh-TW")
    assert {"screening log", "pre-screen log", "about"} <= set(wb.sheetnames)
    assert next(wb["screening log"].iter_rows(values_only=True))[0] == "screening_no"


def test_the_about_sheet_says_the_time_in_the_sites_zone(box: dict[str, Any]) -> None:  # noqa: F811
    wb = _log(box, "en")
    made = next(r[1] for r in wb["about"].iter_rows(values_only=True) if r[0] == "made")
    assert not str(made).endswith("+00:00")  # the site's zone (Asia/Taipei in the test box), not UTC


def test_every_heading_has_its_words_in_three_languages() -> None:
    from console.i18n_step2 import EN, JA, ZH
    from datacore.sponsor import LOG_COLUMNS

    for cat in (EN, JA, ZH):
        assert "log.xlsx.sheet" in cat
        assert all(f"log.xlsx.col.{c}" in cat for c in LOG_COLUMNS if c != "screening_no")


# ------------------------------------------------------------------ the adversarial review
def test_the_machine_sheet_stays_the_one_a_workbook_opens_on(box: dict[str, Any]) -> None:  # noqa: F811
    """Review finding: a reader that takes the active sheet (a test, a sponsor's script) still gets the codes."""
    wb = _log(box, "ja")
    assert wb.active.title == "screening log"


def test_every_coded_column_a_person_reads_is_in_words_and_the_override_says_what_it_is() -> None:
    """Review findings: the referral columns, the decision reason and the IRB warnings overridden are words; the
    override column says the approach went ahead despite IRB warnings (never that the IRB approved an exception)."""
    from console.i18n import translate
    from console.screening_log import printable
    from datacore.sponsor import LOG_COLUMNS
    from openpyxl import Workbook

    row = dict.fromkeys(LOG_COLUMNS, "")
    row.update({"pi_mark": "approach", "pi_mark_reason": "stage", "referral_route": "typed",
                "referral_outcome": "agreed", "referral_reason": "patient_wish",
                "approach_irb_override": "irb_expired,icf_missing"})  # fmt: skip
    ws = printable(Workbook(), "ja", [[row[c] for c in LOG_COLUMNS]])
    got = dict(zip([c.value for c in ws[1]], [c.value for c in ws[2]], strict=True))
    head = translate("ja", "log.xlsx.col.approach_irb_override")
    assert "例外" not in head and got[head] == "、".join(
        translate("ja", f"team.irb.w.{w}") for w in ("irb_expired", "icf_missing"))  # fmt: skip
    for col, key in (
        ("pi_mark_reason", "reason.stage"),
        ("referral_route", "team.route.typed"),
        ("referral_outcome", "team.state.agreed"),
        ("referral_reason", "team.decline.patient_wish"),
    ):
        assert got[translate("ja", f"log.xlsx.col.{col}")] == translate("ja", key), col
    assert translate("ja", "log.xlsx.col.status") == translate("ja", "registry.status")


def test_a_column_of_japanese_text_is_wide_enough_to_read() -> None:
    """Review finding: a CJK character is about two widths wide."""
    from console.screening_log import printable
    from datacore.sponsor import LOG_COLUMNS
    from openpyxl import Workbook

    row = dict.fromkeys(LOG_COLUMNS, "")
    row["reason"] = "患者さんのご家族と相談"  # 11 characters
    ws = printable(Workbook(), "ja", [[row[c] for c in LOG_COLUMNS]])
    letter = ws.cell(row=1, column=LOG_COLUMNS.index("reason") + 1).column_letter
    assert (ws.column_dimensions[letter].width or 0) >= 22
