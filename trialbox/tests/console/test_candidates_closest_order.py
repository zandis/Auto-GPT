"""The candidate list's second order, the coded-answered count and the evidence for and against (MATCH-ARCH 1(e), 1(f);
build item 6). The order is ``tb_common.rank_key`` (tested over an exhaustive domain in ``tests/unit/test_rank_key.py``);
here: the page offers it beside the next-visit order, drops nobody, shows counts and no number that reads as a chance,
and the criteria view splits what speaks for eligibility from what speaks against it."""

from __future__ import annotations

import json
import re
from typing import Any

from console import studies as st

from tests.console import test_console_app as _app
from tests.console.test_console_app import _done_screen, _ulid, name_pi
from tests.console.test_role_pages import _user

box = _app.box  # the console fixture, registered by name for pytest

P1, P2, P3, P4 = "1" * 32, "2" * 32, "3" * 32, "4" * 32
QUOTE = "two flares this spring"


def _row(pid: str, tier: str, visit: str | None, criteria: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "pid": pid,
        "tier": tier,
        "next_appointment": visit,
        "practitioner_id": "DR-LIN",
        "department": "RHEU",
        "criteria": criteria,
        "actions": [],
        "n_unknown": sum(c["verdict"] == "unknown" for c in criteria),
    }


def _c(cid: str, verdict: str, reason: str | None = None, **ev: Any) -> dict[str, Any]:
    return {"id": cid, "verdict": verdict, "evidence": {"resource_refs": [], "reason": reason, **ev}}


def _rows() -> list[dict[str, Any]]:
    inc1, inc2, inc5 = "GZQO-INC-01", "GZQO-INC-02", "GZQO-INC-05"  # structured, structured, note
    return [
        # the earliest visit, three open criteria
        _row(
            P1,
            "review",
            "2026-10-06T09:30:00+08:00",
            [_c(inc1, "unknown", "data_gap"), _c(inc2, "unknown", "data_gap"), _c(inc5, "unknown", "no_notes")],
        ),
        # one open criterion the notes could answer
        _row(
            P2,
            "review",
            "2026-10-08T09:30:00+08:00",
            [_c(inc1, "pass", "coded"), _c(inc2, "pass", "coded"), _c(inc5, "unknown", "not_mentioned")],
        ),
        # nothing open, no visit booked: last by the visit order, first by closeness
        _row(
            P3,
            "high",
            None,
            [
                _c(inc1, "pass", "coded"),
                _c(inc2, "pass", "coded"),
                _c(
                    inc5,
                    "pass",
                    "note",
                    quote=QUOTE,
                    quote_date="2026-04-02",
                    confidence=0.9,
                    opinions=[
                        {"role": "judge", "verdict": "pass", "quote": QUOTE, "quote_date": "2026-04-02"},
                        {
                            "role": "verifier",
                            "verdict": "fail",
                            "quote": "no flares since March",
                            "quote_date": "2026-05-10",
                        },
                    ],
                ),
            ],
        ),
        # one open criterion the site's data cannot answer: nearer than P1, behind P2
        _row(
            P4,
            "review",
            "2026-10-07T09:30:00+08:00",
            [_c(inc1, "pass", "coded"), _c(inc2, "pass", "coded"), _c(inc5, "unknown", "no_notes")],
        ),
    ]


#: the approved criteria the page reads (the box's backend has no ruleset folder): two coded inclusions and one note
CRITERIA = [
    {"id": "GZQO-INC-01", "kind": "inclusion", "class": "structured", "label": "Age", "text": "Adult"},
    {"id": "GZQO-INC-02", "kind": "inclusion", "class": "structured", "label": "Gout", "text": "Gout"},
    {"id": "GZQO-INC-05", "kind": "inclusion", "class": "note", "label": "Flares", "text": "Two flares"},
]


def _install(b: dict[str, Any], jid: str) -> None:
    b["backend"].criteria = lambda rs: CRITERIA if rs == "GZQO" else []
    key = next(k for k in b["backend"].objects if k.startswith(f"outputs/{jid}/candidate_list_"))
    cl = json.loads(b["backend"].objects[key])
    cl["rows"] = _rows()
    b["backend"].objects[key] = json.dumps(cl).encode()


def _order(page: str) -> list[str]:
    return [m[:1] for m in re.findall(r'data-testid="cand-([0-9a-f]{8})"', page)]


def test_the_list_offers_closest_to_eligible_beside_the_next_visit_and_drops_nobody(box: dict[str, Any]) -> None:
    jid = _ulid(971)
    _done_screen(box["backend"], jid)
    _install(box, jid)
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    visit = pi.get("/studies/GZQO/candidates").text
    closest = pi.get("/studies/GZQO/candidates?order=closest").text
    assert _order(visit) == ["1", "4", "2", "3"]  # the next visit, none last: as before
    assert _order(closest) == ["3", "2", "4", "1"]  # high first, then fewest open, then the gap that is easier to close
    assert sorted(_order(visit)) == sorted(_order(closest)) == ["1", "2", "3", "4"]  # the same patients, each once
    assert 'data-testid="order-closest" aria-current="page"' in closest and 'data-testid="order-visit"' in visit
    assert "not a chance of enrolling" in closest  # the order says what it is: a reading order, not a probability
    # an unknown order is the next-visit order, and the order survives the filters and the pager
    assert _order(pi.get("/studies/GZQO/candidates?order=likelihood").text) == _order(visit)
    assert "order=closest" in closest and 'href="?show=unknown&amp;order=closest"' in closest


def test_the_row_header_counts_the_records_answers_and_the_open_criteria(box: dict[str, Any]) -> None:
    jid = _ulid(971)
    _done_screen(box["backend"], jid)
    _install(box, jid)
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    page = pi.get("/studies/GZQO/candidates").text

    def cell(testid: str) -> str:
        m = re.search(rf'data-testid="{testid}">([^<]*)<', page)
        assert m, testid
        return m.group(1).strip()

    # GZQO-INC-01 and -02 are coded: P1 has neither answered, the others both; INC-05 is a note, so it is not counted
    assert [cell(f"cand-coded-{p[:8]}") for p in (P1, P2, P3, P4)] == ["0 of 2", "2 of 2", "2 of 2", "2 of 2"]
    one = pi.get(f"/studies/GZQO/candidates/{P1}?purpose=eligibility").text
    assert re.search(r'data-testid="coded-count">0 of 2<', one)  # the same count on the candidate's own page


def test_the_candidate_page_splits_the_evidence_into_for_and_against_and_marks_a_conflict(box: dict[str, Any]) -> None:
    jid = _ulid(971)
    _done_screen(box["backend"], jid)
    _install(box, jid)
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    page = pi.get(f"/studies/GZQO/candidates/{P3}?purpose=eligibility").text
    sec = page[page.index('data-testid="for-against"') :]
    sec = sec[: sec.index("</section>")]
    at = sec.index('data-testid="evfa-GZQO-INC-05-against"')
    for_side, against_side = sec[:at], sec[at:]
    assert QUOTE in for_side and "no flares since March" not in for_side
    assert "no flares since March" in against_side and QUOTE not in against_side
    assert 'data-testid="evfa-conflict-GZQO-INC-05"' in sec  # the models disagree: marked, and a person looks
    # the criteria the records answered with no record or quote to show have no entry
    assert 'data-testid="evfa-GZQO-INC-01"' not in sec
    # a patient whose criteria carry no evidence at all has no such section
    bare = pi.get(f"/studies/GZQO/candidates/{P1}?purpose=eligibility").text
    assert 'data-testid="for-against"' not in bare


# ---------------------------------------------------------------------------------------------- the view-model, alone
META = {
    "S1": st.CriterionMeta("S1", "inclusion", "structured", "Age"),
    "S2": st.CriterionMeta("S2", "exclusion", "structured", "Pregnancy"),
    "N1": st.CriterionMeta("N1", "inclusion", "note", "Flares"),
}


def test_closeness_key_and_coded_complete_read_a_stored_row() -> None:
    row = {
        "pid": "p",
        "tier": "review",
        "visit_text": "2026-10-07 09:30",
        "criteria": [_c("S1", "pass", "coded"), _c("S2", "unknown", "data_gap"), _c("N1", "unknown", "no_notes")],
    }
    assert st.coded_complete(row, META) == (1, 2)
    tier, n_open, weight, minus_for, no_visit, visit, pid = st.closeness_key(row, META)
    assert (tier, n_open, weight, minus_for, no_visit, visit, pid) == (1, 2, 1 + 3, 0, False, "2026-10-07 09:30", "p")
    assert st.coded_complete({"criteria": []}, META) == (0, 2)


def test_coded_complete_counts_over_the_studys_criteria_and_each_answer_once() -> None:
    one = {"criteria": [_c("S1", "pass", "coded")]}  # S2 has no stored verdict: it is still one of the study's two
    assert st.coded_complete(one, META) == (1, 2)
    twice = {"criteria": [_c("S1", "pass", "coded"), _c("S1", "pass", "coded")]}
    assert st.coded_complete(twice, META) == (1, 2)


def test_evidence_sides_puts_each_quote_and_record_on_its_own_side() -> None:
    cv = {"lines": [{"date": "2026-09-12", "value": "29.4 kg/m²", "code": "39156-5"}], "more": 0, "none": False}
    # a coded answer: its records stand on the side of the answer, and no quote means no note on either side
    got = st.evidence_sides({"verdict": "pass", "evidence": {}}, cv, [])
    assert got["for"]["coded"] == cv["lines"] and got["against"] == {"coded": [], "notes": []}
    assert got["any"] and not got["conflict"]
    got = st.evidence_sides({"verdict": "fail", "evidence": {}}, cv, [])
    assert got["against"]["coded"] == cv["lines"] and got["for"]["coded"] == []
    # no answer: the records decide nothing and sit on no side
    got = st.evidence_sides({"verdict": "unknown", "evidence": {}}, cv, [])
    assert not got["any"] and not got["conflict"]
    # one quote, no opinions: the verdict's side; and a held-back "not met" is still shown against, it excludes nobody
    got = st.evidence_sides(
        {"verdict": "fail", "basis": "single", "evidence": {"quote": "q", "quote_date": "2026-01-01"}},
        {"lines": []},
        [],
    )
    assert got["against"]["notes"] == [{"quote": "q", "date": "2026-01-01", "role": ""}] and got["any"]
    # two opinions that differ: one on each side, newest first within a side, the conflict marked
    ops = [
        {"role": "judge", "verdict": "pass", "quote": "old", "quote_date": "2026-01-01"},
        {"role": "verifier", "verdict": "pass", "quote": "new", "quote_date": "2026-03-01"},
        {"role": "x", "verdict": "fail", "quote": "against", "quote_date": "2026-02-01"},
        {"role": "y", "verdict": "unknown", "quote": "neither"},
    ]
    got = st.evidence_sides({"verdict": "unknown", "evidence": {"quote": "q"}}, {"lines": []}, ops)
    assert [n["quote"] for n in got["for"]["notes"]] == ["new", "old"]
    assert [n["quote"] for n in got["against"]["notes"]] == ["against"] and got["conflict"]  # "neither" is on no side


def test_patient_rows_carry_the_sides_for_every_criterion() -> None:
    rows = st.patient_rows(
        [_c("S1", "pass", "coded"), _c("N1", "pass", "note", quote="q", quote_date="2026-01-01")], META
    )
    assert all("sides" in r and set(r["sides"]) >= {"for", "against", "any", "conflict"} for r in rows)
    assert rows[1]["sides"]["for"]["notes"][0]["quote"] == "q"
