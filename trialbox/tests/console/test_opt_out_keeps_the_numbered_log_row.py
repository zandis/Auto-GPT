"""NEW-LIFE-5 (D-762, the deep review's LIFE-005): an opt-out keeps the numbered screening-log row.

The screening log and its XLSX dropped every patient on the opt-out register, also one who had consented and
enrolled: a screening number vanished from the log (GZQO-0003 between 0002 and 0004) with no row and no reason, the
enrolled subject was missing from the enrolment log and the monitor could not open their sheet. The trial record of a
consented or enrolled subject stays (D-441). Now a patient who was given a screening number keeps the row: number,
dates, status and "opted out of further research use on <date>", with no pseudonym and nothing of the contact
work (mark, outcomes, referral). A patient never numbered stays off every list (D-147, D-273). Synthetic data only."""

from __future__ import annotations

import io
from typing import Any

from console.sitestore import StudySettings
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_sdv import NO, PIDS, PW, _grant, sb  # noqa: F401 - the fixture is used by name

NEVER = "p-0005-never"  # opted out before any screening number: on no list


def _numbered_gone(b: dict[str, Any]) -> str:
    h = b["app"].state.helpers
    h.optout.add(NEVER, "paper", "", "stw", "2026-11-04T00:00:00+00:00")
    h.store.first_seen("GZQO")  # the store is open
    return str(b["nos"][PIDS["gone"]])


def test_the_log_page_keeps_the_numbered_row_of_an_opted_out_subject(sb: dict[str, Any]) -> None:  # noqa: F811
    no = _numbered_gone(sb)
    pi, _ = login(sb["app"], "drsato", PW)
    page = pi.get("/studies/GZQO/screening-log")
    assert page.status_code == 200, page.text[-300:]
    row = page.text[page.text.index(f'data-testid="log-{no}"') :][:1500]
    assert 'data-testid="log-opted-out"' in row and "2026-11-03" in row  # the day of the opt-out
    assert "2026-11-02" in row  # its consent and enrolment day stay
    assert PIDS["gone"] not in page.text and PIDS["gone"][:8] not in page.text  # no pseudonym
    assert NEVER not in page.text and NEVER[:8] not in page.text  # never numbered: on no list
    for other in (NO, str(sb["nos"][PIDS["cand"]]), str(sb["nos"][PIDS["fail"]])):
        assert f'data-testid="log-{other}"' in page.text  # the numbers run on without a gap


def test_the_xlsx_keeps_the_row_with_the_opt_out_day_and_no_pseudonym(sb: dict[str, Any]) -> None:  # noqa: F811
    no = _numbered_gone(sb)
    pi, _ = login(sb["app"], "drsato", PW)
    r = pi.get("/studies/GZQO/screening-log.xlsx")
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["screening log"]
    head = [c.value for c in ws[1]]
    rows = [dict(zip(head, [c.value for c in line], strict=True)) for line in ws.iter_rows(min_row=2)]
    mine = [x for x in rows if x["screening_no"] == no]
    assert len(mine) == 1
    assert mine[0]["opted_out"] == "2026-11-03" and not mine[0]["pseudonym"]
    assert mine[0]["consent_date"] == "2026-11-02" and mine[0]["enrolment_date"] == "2026-11-02"
    assert not mine[0]["pi_mark"] and not mine[0]["referral_route"]  # nothing of the contact work
    assert all(not x["opted_out"] for x in rows if x["screening_no"] != no)
    flat = repr([[c.value for c in line] for s in wb.worksheets for line in s.iter_rows()])
    assert PIDS["gone"] not in flat and NEVER not in flat


def test_the_api_twin_keeps_the_numbered_row_without_its_pseudonym(sb: dict[str, Any]) -> None:  # noqa: F811
    no = _numbered_gone(sb)
    api = TestClient(sb["app"])
    tok = api.post("/api/v1/session", json={"username": "drsato", "password": PW}).json()["token"]
    api.headers["Authorization"] = f"Bearer {tok}"
    body = api.get("/api/v1/studies/GZQO/screening-log").json()
    mine = [x for x in body if x["screening_no"] == no]
    assert len(mine) == 1 and mine[0]["pid"] == "" and mine[0]["opted_out"] == "2026-11-03"
    assert not mine[0]["referral_route"] and not mine[0]["referral_outcome"]
    assert all(x["pid"] and not x["opted_out"] for x in body if x["screening_no"] != no)
    assert NEVER not in repr(body)


def test_a_numbered_patient_opted_out_before_a_mark_stays_off_the_pre_screen_log(sb: dict[str, Any]) -> None:  # noqa: F811
    """The pre-screen log lists investigator marks by pseudonym; an opted-out patient's marks leave it (D-147). The
    numbered row is on the screening log above, so no number is lost."""
    h = sb["app"].state.helpers
    h.store.assign_screening_no("GZQO", NEVER, StudySettings(), "2026-11-01T00:00:00+00:00")
    _numbered_gone(sb)
    pi, _ = login(sb["app"], "drsato", PW)
    wb = load_workbook(io.BytesIO(pi.get("/studies/GZQO/screening-log.xlsx").content))
    pre = repr([[c.value for c in line] for line in wb["pre-screen log"].iter_rows()])
    assert NEVER not in pre and PIDS["gone"] not in pre


def test_the_monitor_opens_an_enrolled_subject_who_opted_out(sb: dict[str, Any]) -> None:  # noqa: F811
    """The monitor's list and sheet follow the same rule: an enrolled subject is a trial subject (D-441); the sheet
    says the opt-out, never the pseudonym."""
    no = _numbered_gone(sb)
    _grant(sb)
    mon, _ = login(sb["app"], "mon1", PW)
    page = mon.get(f"/studies/GZQO/monitor/{no}")
    assert page.status_code == 200, page.text[-300:]
    assert 'data-testid="sdv-opted-out"' in page.text and "2026-11-03" in page.text
    assert PIDS["gone"] not in page.text
    listing = mon.get("/studies/GZQO/monitor")
    assert no in listing.text and PIDS["gone"] not in listing.text
