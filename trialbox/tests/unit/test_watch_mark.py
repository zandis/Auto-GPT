"""Lane K (HOLISTIC-3 §5.2, H3-PROD §2 row 2): the visit-week view and the watch mark.

A watch is a "Not now" mark that names the criterion it waits on. The patient stays off the weekly list until the
re-check date, or until a re-screen gives that criterion another answer than the one it had when the PI marked;
then the patient is back on the list with the criterion named. The four-mark vocabulary does not change (D-108).
The clinic list (visits in the next two weeks, in visit order) is not offered where the list carries no visit at
all: a site that exports no appointment view gets no empty visit list."""

from __future__ import annotations

from datetime import date

import pytest
from console import studies as st
from console.sitestore import Mark

pytestmark = pytest.mark.nodb

PID = "b" * 16
AT = "2026-12-01T07:00:00+00:00"
CID = "GZQO-INC-03"
TODAY = date(2026, 12, 1)


def _cl(verdict: str, visit: str | None = None) -> dict:
    return {"rows": [{"pid": PID, "tier": "review", "next_appointment": visit,
                      "criteria": [{"id": CID, "verdict": verdict}]}]}  # fmt: skip


def test_the_stored_reason_keeps_the_recheck_date_first_and_names_the_trigger() -> None:
    reason = st.not_now_reason(date(2027, 3, 1), CID, _cl("unknown")["rows"][0])
    assert reason == "2027-03-01 watch:GZQO-INC-03=unknown"
    assert st.recheck_due(Mark(PID, "not_now", reason, None, "pi", AT, "J1"), date(2027, 3, 1))
    assert st.watch_of(Mark(PID, "not_now", reason, None, "pi", AT, "J1")) == (CID, "unknown")
    assert st.not_now_reason(date(2027, 3, 1), "", _cl("unknown")["rows"][0]) == "2027-03-01"
    assert st.watch_of(Mark(PID, "not_now", "2027-03-01", None, "pi", AT, "J1")) is None


def test_a_trigger_that_is_not_a_criterion_of_the_row_is_refused() -> None:
    with pytest.raises(ValueError):
        st.not_now_reason(date(2027, 3, 1), "GZQO-INC-99", _cl("unknown")["rows"][0])


def test_the_watch_hides_the_patient_while_the_trigger_keeps_its_answer() -> None:
    mk = Mark(PID, "not_now", "2027-03-01 watch:GZQO-INC-03=unknown", None, "pi", AT, "J1")
    assert st.weekly_rows(_cl("unknown"), {}, {}, {PID: mk}, {}, "J2", today=TODAY) == []


def test_a_re_screen_that_changes_the_trigger_brings_the_patient_back_with_the_criterion_named() -> None:
    mk = Mark(PID, "not_now", "2027-03-01 watch:GZQO-INC-03=unknown", None, "pi", AT, "J1")
    rows = st.weekly_rows(_cl("pass"), {}, {}, {PID: mk}, {}, "J2", today=TODAY)
    assert [r["pid"] for r in rows] == [PID]
    assert rows[0]["watch"] == {"cid": CID, "was": "unknown", "now": "pass", "fired": True}
    assert st.in_worklist(rows[0], "review", TODAY)


def test_a_plain_not_now_row_carries_no_watch() -> None:
    mk = Mark(PID, "not_now", "2026-11-30", None, "pi", AT, "J1")
    rows = st.weekly_rows(_cl("unknown"), {}, {}, {PID: mk}, {}, "J2", today=TODAY)
    assert rows[0]["watch"] is None


def test_the_clinic_list_is_offered_only_where_the_list_carries_a_visit() -> None:
    none = st.weekly_rows(_cl("unknown"), {}, {}, {}, {}, "J2", today=TODAY)
    booked = st.weekly_rows(_cl("unknown", "2026-12-03T09:00:00+08:00"), {}, {}, {}, {}, "J2", today=TODAY)
    assert "clinic" not in st.worklists_for(none)
    assert st.worklists_for(booked) == st.WORKLISTS
    assert st.in_worklist(booked[0], "clinic", TODAY)


def test_the_answer_the_page_showed_is_the_baseline_not_a_later_run() -> None:
    """Review K1: a run lands between the PI's view (unknown) and the mark; the stored answer is the one shown."""
    row = _cl("pass")["rows"][0]
    assert st.not_now_reason(date(2027, 3, 1), f"{CID}=unknown", row) == "2027-03-01 watch:GZQO-INC-03=unknown"
    with pytest.raises(ValueError):
        st.not_now_reason(date(2027, 3, 1), f"{CID}=maybe", row)


def test_a_change_and_change_back_in_a_later_run_still_brings_the_patient_back() -> None:
    """Review K2: the run after the mark changed the criterion (``changed``) though the answer reads as before."""
    mk = Mark(PID, "not_now", "2027-03-01 watch:GZQO-INC-03=unknown", None, "pi", AT, "J1")
    cl = _cl("unknown")
    cl["rows"][0]["changed"] = [CID]
    assert st.weekly_rows(cl, {}, {}, {PID: mk}, {}, "J1", today=TODAY) == []  # the run the mark was made on
    assert [r["pid"] for r in st.weekly_rows(cl, {}, {}, {PID: mk}, {}, "J2", today=TODAY)] == [PID]
