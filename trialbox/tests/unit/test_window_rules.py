"""The window rules (``ir_extract.window_rules``): the expected readings of public registry text, the adjudicated
rule-versus-model pairs, and the reconcile and lint steps that sit in ``postprocess``.

``gold_cases.jsonl``: lines with the reading written out by hand (value, unit, anchor, kind), and lines the rules must
not claim. ``adjudicated_pairs.jsonl``: lines where the rules and an extractor differed, judged blind by a third
reader; ``rules_ok`` is that verdict on the rules' side. Only public text; no ids."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.ir_extract.window_rules import (
    NEGATIVE,
    Reconciled,
    interval,
    lint,
    parse_window,
    parse_windows,
    reads_text,
    reconcile,
)

pytestmark = pytest.mark.nodb

FIX = Path(__file__).parent.parent / "fixtures" / "window_rules"


def _rows(name: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (FIX / name).read_text(encoding="utf-8").splitlines()]


def _sig(text: str) -> list[tuple[Any, ...]]:
    return [(r.win_val, r.win_unit, r.anchor, r.kind) for r in parse_windows(text)]


def _shown(text: str) -> list[str]:
    """The rule windows of a line as the pair fixtures show them: a sorted set of ``value unit @ anchor``."""
    ws = {(r.win_val, r.win_unit, r.anchor) for r in parse_windows(text) if r.kind == "window"}
    ws = {(int(v) if isinstance(v, float) and v.is_integer() else v, u, a) for v, u, a in ws}
    if not ws:
        return ["(no window)"]
    return [f"{'-' if v is None else v} {u or '-'} @ {a or '(no anchor)'}" for v, u, a in sorted(ws, key=json.dumps)]


GOLD = [r for r in _rows("gold_cases.jsonl") if "expected" in r]
ABSTAIN = [r for r in _rows("gold_cases.jsonl") if r.get("abstains")]
PAIRS = _rows("adjudicated_pairs.jsonl")
# judged "both defensible" by the third reader because a bare window before a clause that names its event may share
# that event; the rules now abstain on such a line rather than read it one way
SHARED_ANCHOR = {398}


@pytest.mark.parametrize("row", GOLD, ids=[str(r["gid"]) for r in GOLD])
def test_the_reading_written_out_by_hand(row: dict[str, Any]) -> None:
    want = [tuple(tuple(v) if isinstance(v, list) else v for v in e) for e in row["expected"]]
    assert _sig(row["text"]) == want


@pytest.mark.parametrize("row", ABSTAIN, ids=[str(r["gid"]) for r in ABSTAIN])
def test_a_line_the_rules_do_not_understand_is_not_claimed(row: dict[str, Any]) -> None:
    assert not all(r.high_confidence for r in parse_windows(row["text"]))


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("within 2-4 weeks before randomization", ((2, 4), "week", "randomization", "window")),
        ("between two and four weeks before randomization", ((2, 4), "week", "randomization", "window")),
        ("within 4 weeks before or after vaccination", (4, "week", "vaccination", "window")),
        ("within twenty-one days of screening", (21, "day", "screening", "window")),
        ("at least six months before randomization", (6, "month", "randomization", "window")),
        ("≥14 d since surgery", (14, "day", "surgery", "window")),
        ("within 48 hrs after first dose", (48, "hour", "first_dose", "window")),
        ("within 2 wk prior to enrollment", (2, "week", "enrollment", "window")),
        ("within 30 days before enrolment", (30, "day", "enrollment", "window")),
        ("in the past 3 mo", (3, "month", "screening", "window")),
        ("at screening", (None, "", "screening", "window")),
        ("during the study", (None, "", "study", "window")),
        ("at any time", (None, "", "any_time", "window")),
        ("prior to the first dose", (None, "", "first_dose", "window")),
        ("history of cancer", (None, "", "", "none")),
        ("Complete the initial 8 weeks of run-in therapy.", (8, "week", "", "duration")),
        ("Chronic use (more than 10 days) of medication.", (10, "day", "", "duration")),
        ("Estimated by 12-hour collection.", (12, "hour", "", "duration")),
        ("Completed the 9 months treatment arm.", (9, "month", "", "duration")),
        ("Diet and exercise control for at least 8 weeks before screening.", (8, "week", "", "duration")),
        ("Stable dose of aspirin for at least 30 days.", (30, "day", "", "duration")),
        ("within 30 days of the end of the study", (30, "day", "end_of_study", "window")),
    ],
)
def test_other_readings(text: str, want: tuple[Any, ...]) -> None:
    assert _sig(text) == [want]


def test_a_line_with_several_expressions_has_no_single_reading() -> None:
    assert parse_window(GOLD[[r["gid"] for r in GOLD].index(100)]["text"]).kind == "unparsed"


@pytest.mark.parametrize("row", PAIRS, ids=[str(r["gid"]) for r in PAIRS])
def test_adjudicated_pair(row: dict[str, Any]) -> None:
    results = parse_windows(row["text"])
    if row["rules_ok"]:
        assert sorted(_shown(row["text"])) == sorted(row["rules"])
        if row["gid"] not in SHARED_ANCHOR:
            assert all(r.high_confidence for r in results)
        else:  # W12 of review 2: the abstention is asserted, and the model's windows stand
            assert not all(r.high_confidence for r in results)
            logic = {"op": "and", "args": [_atom(from_days=-180, to_days=0), _atom(from_days=-60, to_days=0)]}
            assert reconcile(row["text"], logic) == Reconciled(
                {"op": "and", "args": [_atom(from_days=-180, to_days=0), _atom(from_days=-60, to_days=0)]}, []
            )
    else:  # read wrongly by an earlier version of the rules (an anchor cut short, a shared or index-disease anchor)
        assert not all(r.high_confidence for r in results)


def test_the_rules_were_right_on_83_of_the_87_adjudicated_pairs() -> None:
    ok = [r for r in PAIRS if r["rules_ok"]]
    assert len(PAIRS) == 87
    assert len(ok) == 83
    assert all(sorted(_shown(r["text"])) == sorted(r["rules"]) for r in ok)


# ------------------------------------------------------------------------------------------------------- the intervals
@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("within 30 days before screening", (-30, 0)),
        ("within 2-4 weeks before randomization", (-28, -14)),
        ("within 48 hours after first dose", None),  # no whole-day form for hours
        ("at least 6 months before randomization", (None, -180)),
        ("at least 6 months after randomization", None),  # an open future end has no form in the IR window
        ("exactly 30 days before screening", None),
        ("in the past 3 months", (-90, 0)),
        ("within 28 days of screening", None),  # which side of the anchor is not said
        ("within 5 hours before screening", None),  # no whole-day form
    ],
)
def test_interval_in_days(text: str, want: tuple[int | None, int | None] | None) -> None:
    (r,) = (x for x in parse_windows(text) if x.kind == "window")
    assert interval(r) == want


# ------------------------------------------------------------------------------------------------------- reconcile
def _atom(**w: Any) -> dict[str, Any]:
    a: dict[str, Any] = {"domain": "medication", "valueset": "NONE", "quantifier": "any"}
    if w:
        a["window"] = w
    return a


def test_a_window_the_line_does_not_say_is_left_alone_by_default() -> None:
    """The stand-in extractions put a recency window on every "latest" lab: not dropped until it is ruled."""
    logic = _atom(from_days=-365, to_days=0)
    out = reconcile("Body mass index (BMI) of 27 kg/m2 or more at screening.", logic)
    assert out.flags == []
    assert out.logic["window"] == {"from_days": -365, "to_days": 0}


def test_a_window_the_line_does_not_say_is_removed_when_asked() -> None:
    out = reconcile("Normal liver function tests", _atom(from_days=-45, to_days=0), drop_unstated=True)
    assert out.flags == ["window_not_in_text"]
    assert "window" not in out.logic


def test_a_time_word_the_rules_did_not_read_leaves_the_models_window() -> None:
    logic = _atom(from_days=-365, to_days=0)
    out = reconcile("Surgery in the preceding year", logic, drop_unstated=True)
    assert out.flags == []
    assert out.logic["window"] == {"from_days": -365, "to_days": 0}


def test_several_windowed_atoms_are_never_overridden_by_one_window() -> None:
    both = {"op": "and", "args": [_atom(from_days=-14, to_days=0), _atom(from_days=-90, to_days=0)]}
    out = reconcile("Chemotherapy within 30 days before screening, stable for 3 months", both)
    assert out.flags == ["window_disagrees"]
    assert [a["window"]["from_days"] for a in out.logic["args"]] == [-14, -90]


def test_a_duration_is_not_a_window() -> None:
    out = reconcile("Stable dose of aspirin for at least 3 months", _atom(from_days=-90, to_days=0), drop_unstated=True)
    assert out.flags == ["window_not_in_text"]
    assert "window" not in out.logic


def test_agreeing_windows_are_left_alone() -> None:
    logic = _atom(from_days=-30, to_days=0, anchor="index")
    out = reconcile("Chemotherapy within 30 days before screening", logic)
    assert out.flags == []
    assert out.logic["window"] == {"from_days": -30, "to_days": 0, "anchor": "index"}


def test_the_rule_wins_over_a_different_model_window() -> None:
    out = reconcile("Chemotherapy in the past 30 days", _atom(from_days=-14, to_days=0))
    assert out.flags == ["window_rules_override"]
    assert out.logic["window"] == {"from_days": -30, "to_days": 0, "anchor": "index"}


def test_twelve_months_and_a_year_are_one_window() -> None:
    out = reconcile("Chemotherapy within the 12 months before screening", _atom(from_days=-365, to_days=0))
    assert out.flags == []
    assert out.logic["window"] == {"from_days": -365, "to_days": 0}
    out = reconcile("Chemotherapy in the past 12 months", _atom(from_days=-300, to_days=0))
    assert out.flags == ["window_rules_override"]
    assert out.logic["window"] == {"anchor": "index", "from_days": -360, "to_days": 0}


def test_an_age_or_a_course_in_a_window_is_not_the_rules_to_change() -> None:
    demographic = {"domain": "demographic"}
    out = reconcile("Participation in another study within 30 days before screening", demographic)
    assert out.flags == [] and "window" not in out.logic
    course = {**_atom(from_days=-365, to_days=0), "duration": {"min_days": 90, "gap_days": 30}}
    out = reconcile("Methotrexate for at least 3 months before screening", course)
    assert out.flags == []
    assert out.logic["window"] == {"from_days": -365, "to_days": 0}


def test_a_window_the_model_missed_is_added_on_a_single_atom() -> None:
    out = reconcile("Chemotherapy in the past 30 days", _atom())
    assert out.flags == ["window_rules_override"]
    assert out.logic["window"] == {"from_days": -30, "to_days": 0, "anchor": "index"}


def test_a_missed_window_on_several_atoms_is_flagged_not_guessed() -> None:
    both = {"op": "and", "args": [_atom(), _atom()]}
    out = reconcile("Chemotherapy or radiotherapy within 30 days before screening", both)
    assert out.flags == ["window_unattached"]
    assert all("window" not in a for a in out.logic["args"])


def test_a_direction_the_line_does_not_give_is_flagged_not_overridden() -> None:
    out = reconcile("Chemotherapy within 28 days of screening", _atom(from_days=-14, to_days=0))
    assert out.flags == ["window_disagrees"]
    assert out.logic["window"] == {"from_days": -14, "to_days": 0}


def test_registration_is_the_entry_into_the_study_as_randomization_is() -> None:
    out = reconcile("Chemotherapy within 30 days before registration", _atom(from_days=-14, to_days=0))
    assert out.flags == ["window_anchor_unsupported"]  # W02 of review 2: never written as the index date
    assert out.hold is not None and "enrollment" in out.hold
    assert out.logic["window"] == {"from_days": -14, "to_days": 0}


def test_a_window_from_the_study_dosing_is_held_for_a_person() -> None:
    out = reconcile("Radiotherapy within 30 days of last dose", _atom(from_days=-30, to_days=0))
    assert out.flags == ["window_anchor_unsupported"]
    assert out.hold is not None
    assert "last dose" in out.hold


def test_two_windows_are_compared_not_attached() -> None:
    text = "Surgery within 3 months and cancer within 1 year before screening"
    fine = reconcile(text, {"op": "and", "args": [_atom(from_days=-90, to_days=0), _atom(from_days=-365, to_days=0)]})
    off = reconcile(text, {"op": "and", "args": [_atom(from_days=-90, to_days=0), _atom(from_days=-30, to_days=0)]})
    assert fine.flags == []
    assert off.flags == ["window_disagrees"]


def test_a_line_the_rules_do_not_understand_leaves_the_model_alone() -> None:
    logic = _atom(from_days=-14, to_days=0)
    out = reconcile("Recently treated with a stable regimen, per the investigator", logic)
    assert out.flags == []
    assert out.logic["window"] == {"from_days": -14, "to_days": 0}


def test_a_line_in_a_script_the_rules_do_not_read_is_left_alone() -> None:
    assert not reads_text("六個月內曾使用降尿酸藥物。")
    out = reconcile("六個月內曾使用降尿酸藥物。", _atom(from_days=-180, to_days=0))
    assert out.flags == []
    assert out.logic["window"] == {"from_days": -180, "to_days": 0}


# ------------------------------------------------------------------------------------------------------------- lint
def test_lint_names_a_window_the_line_never_says() -> None:
    why = lint("Normal liver function tests", _atom(from_days=-45, to_days=0))
    assert why is not None
    assert "Normal liver function tests" in why


def test_lint_accepts_a_window_the_line_says_in_any_script() -> None:
    assert lint("Chemotherapy in the last 3 months", _atom(from_days=-90, to_days=0)) is None
    assert lint("六個月內曾使用降尿酸藥物。", _atom(from_days=-180, to_days=0)) is None


# ------------------------------------------------------------------------------------- the first review's defects
def test_a_window_from_another_event_is_flagged_not_taken_for_the_index_date() -> None:
    out = reconcile("Chemotherapy within 30 days after surgery", _atom(from_days=0, to_days=30))
    assert out.flags == ["window_anchor_event"]
    assert out.logic["window"] == {"from_days": 0, "to_days": 30}
    surgery = {"domain": "procedure", "concept": "Surgery", "quantifier": "any"}
    # the atom is the named event itself: the window counted from the index date is the line's, compared by length
    assert reconcile("At least 14 days since surgery", {**surgery, "window": {"to_days": -14}}).flags == []
    off = reconcile("At least 14 days since surgery", {**surgery, "window": {"to_days": -30}})
    assert off.flags == ["window_disagrees"]
    assert off.logic["window"] == {"to_days": -30}  # a named event's side is not the index date's: never written
    other = {**surgery, "concept": "Surgical resection", "window": {"from_days": -180, "to_days": 0}}
    assert reconcile("Resection within 6 months prior to the index procedure", other).flags == ["window_anchor_event"]


def test_several_windows_are_compared_with_their_side_of_the_anchor() -> None:
    text = "Surgery within 3 months before screening and chemotherapy within 1 year before screening"
    forward = {"op": "and", "args": [_atom(from_days=0, to_days=90), _atom(from_days=0, to_days=365)]}
    assert reconcile(text, forward).flags == ["window_disagrees"]
    back = {"op": "and", "args": [_atom(from_days=-90, to_days=0), _atom(from_days=-365, to_days=0)]}
    assert reconcile(text, back).flags == []


def test_a_window_is_never_written_on_one_of_several_atoms() -> None:
    both = {"op": "and", "args": [_atom(), _atom(from_days=-365, to_days=0)]}
    out = reconcile("Chemotherapy within 30 days before screening and radiotherapy in the preceding year", both)
    assert out.logic["args"][1]["window"] == {"from_days": -365, "to_days": 0}
    assert "window_rules_override" not in out.flags


def test_an_exact_offset_is_not_within() -> None:
    out = reconcile("Chemotherapy exactly 30 days before screening", _atom(from_days=-30, to_days=-30))
    assert out.flags == []
    assert out.logic["window"] == {"from_days": -30, "to_days": -30}


def test_an_unbounded_window_from_the_first_dose_holds_a_criterion_the_model_gave_a_window() -> None:
    out = reconcile("Chemotherapy prior to the first dose", _atom(from_days=-30, to_days=0))
    assert out.flags == ["window_anchor_unsupported"]
    assert out.hold is not None
    assert reconcile("Chemotherapy prior to the first dose", _atom()).hold is None  # no window given: any time


def test_an_open_future_window_is_flagged_not_written() -> None:
    out = reconcile("Chemotherapy at least 30 days after screening", _atom())
    assert out.flags == ["window_unattached"]
    assert "window" not in out.logic


def test_hours_have_no_whole_day_form() -> None:
    out = reconcile("Chemotherapy within 96 hours before screening", _atom(from_days=-2, to_days=0))
    assert out.flags == ["window_disagrees"]  # W11 of review 2: compared in hours, 96 is not 48; never written
    assert out.logic["window"] == {"from_days": -2, "to_days": 0}


def test_a_comparison_such_as_at_least_is_no_event() -> None:
    (r,) = (
        x for x in parse_windows("Most recent serum urate in the last year at least 7.0 mg/dL.") if x.kind == "window"
    )
    assert (r.anchor, r.high_confidence) == ("screening", True)


# ------------------------------------------------------------------------------------ the second review's defects
MOVE_OUT = "Do not agree to join the experiment, plan to move out or go out within 1 month."


def test_a_bare_within_has_no_side_of_the_anchor() -> None:
    """W01: "within 1 month" with no before, after, last, past or next says no side; the rules never pick one."""
    (r,) = (x for x in parse_windows(MOVE_OUT) if x.kind == "window")
    assert (r.relation, interval(r)) == ("", None)
    out = reconcile(MOVE_OUT, _atom(from_days=0, to_days=30))
    assert out.flags == [] and out.logic["window"] == {"from_days": 0, "to_days": 30}
    out = reconcile(MOVE_OUT, _atom())
    assert out.flags == ["window_unattached"] and "window" not in out.logic
    (nxt,) = (x for x in parse_windows("Planned surgery within the next 6 months") if x.kind == "window")
    (last,) = (x for x in parse_windows("Surgery within the last 6 months") if x.kind == "window")
    (ago,) = (x for x in parse_windows("Surgery within 6 months ago") if x.kind == "window")
    assert (interval(nxt), interval(last), interval(ago)) == ((0, 180), (-180, 0), (-180, 0))


@pytest.mark.parametrize("event", ["screening", "randomization", "enrollment", "informed consent"])
def test_a_window_from_a_named_study_date_is_never_written_as_the_index_date(event: str) -> None:
    """W02: "before randomization" counts from a date that is not the run's; the IR window of an extraction counts
    from the run's date only, so a window the rules would write goes to a person instead (the model's agreeing
    window is left as it is)."""
    text = f"Chemotherapy within 7 days before {event}"
    for logic in (_atom(), _atom(from_days=-30, to_days=0)):
        given = json.loads(json.dumps(logic))
        out = reconcile(text, logic)
        assert out.flags == ["window_anchor_unsupported"]
        assert out.hold is not None and event.rsplit(maxsplit=1)[-1] in out.hold
        assert out.logic == given
    assert reconcile(text, _atom(from_days=-7, to_days=0)).flags == []


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("no more than 30 days before screening", (-30, 0)),
        ("not more than 30 days before screening", (-30, 0)),
        ("up to 30 days before screening", (-30, 0)),
        ("less than 30 days before screening", (-29, 0)),
        ("more than 30 days before screening", (None, -31)),
        ("30 days or more before screening", (None, -30)),
        ("no less than 30 days before screening", (None, -30)),
        ("at least 30 days before screening", (None, -30)),
    ],
)
def test_a_comparator_is_read_whole_and_its_bound_kept(text: str, want: tuple[int | None, int | None]) -> None:
    """W03: "no more than" is not "more than"; a strict bound is one day inside the inclusive one."""
    (r,) = (x for x in parse_windows(text) if x.kind == "window")
    assert interval(r) == want


def test_a_course_up_to_a_named_date_is_not_a_minimum_distance() -> None:
    """W04 (fixture 248): "no antidiabetic drugs for at least 12 weeks prior to informed consent" is 12 drug-free
    weeks up to consent, not a drug 12 weeks before it; the rules write nothing and compare the side."""
    (text,) = (r["text"] for r in GOLD if r["gid"] == 248)
    (r,) = (x for x in parse_windows(text) if x.kind == "window")
    assert (r.win_val, r.win_unit, r.anchor, r.relation, r.bound) == (12, "week", "consent", "prior to", "course")
    assert interval(r) is None
    out = reconcile(text, _atom())
    assert out.flags == ["window_unattached"] and "window" not in out.logic
    out = reconcile(text, _atom(to_days=-84))
    assert out.flags == ["window_disagrees"] and out.logic["window"] == {"to_days": -84}
    assert reconcile(text, _atom(from_days=-84, to_days=0)).flags == []


@pytest.mark.parametrize("text", ["Treatment -7 days before screening", "Treatment −7 days before screening"])
def test_a_negative_amount_goes_to_a_person(text: str) -> None:
    """W05 (D-914): a signed negative amount has no sure reading; it is never read as the positive one."""
    assert not all(r.high_confidence for r in parse_windows(text))
    for logic in (_atom(), _atom(from_days=-7, to_days=0)):
        given = json.loads(json.dumps(logic))
        out = reconcile(text, logic)
        assert out.flags == ["window_negative"] and out.hold is not None
        assert out.logic == given


def test_a_spaced_dash_is_a_range_not_a_sign() -> None:
    assert all(r.reason != NEGATIVE for r in parse_windows("aged 6 months - 17 years"))
    assert all(r.reason != NEGATIVE for r in parse_windows("Chemotherapy within 2 - 4 weeks before screening"))


def test_alternative_anchors_are_not_cut_to_the_first() -> None:
    """W06: "before screening or first dose" names two dates; one window cannot say which, so a person reads it."""
    text = "Chemotherapy within 7 days before screening or first dose"
    assert not all(r.high_confidence for r in parse_windows(text))
    out = reconcile(text, _atom(from_days=-7, to_days=0))
    assert out.flags == ["window_anchor_alternatives"] and out.hold is not None


def test_an_unbounded_first_dose_clause_is_read_beside_a_numeric_one() -> None:
    """W07: the month does not hide "surgery prior to the first dose"."""
    text = "Chemotherapy in the past month and surgery prior to the first dose"
    assert any(r.anchor == "first_dose" and r.relation == "unbounded" for r in parse_windows(text))
    first = "Prior to the first dose and within 30 days of screening"  # the clause before the number too
    assert any(r.anchor == "first_dose" and r.relation == "unbounded" for r in parse_windows(first))
    both = {"op": "and", "args": [_atom(from_days=-30, to_days=0), _atom(from_days=-90, to_days=0)]}
    out = reconcile(text, both)
    assert out.flags == ["window_anchor_unsupported"] and out.hold is not None


def test_an_atom_with_a_duration_still_counts_as_an_owner() -> None:
    """W08: with a course atom beside it, the stroke atom is not the window's only possible owner."""
    course = {**_atom(), "duration": {"min_days": 7}}
    logic = {"op": "and", "args": [course, _atom()]}
    out = reconcile("Chemotherapy for 7 days within the past month and history of stroke", logic)
    assert out.flags == ["window_unattached"]
    assert all("window" not in a for a in out.logic["args"])


@pytest.mark.parametrize("pair", [(-30, 0), (0, 30)])
def test_an_exact_offset_is_compared_on_both_signed_ends(pair: tuple[int, int]) -> None:
    """W09: "exactly 30 days before" is day -30, not the month up to now nor the month ahead."""
    out = reconcile("Chemotherapy exactly 30 days before screening", _atom(from_days=pair[0], to_days=pair[1]))
    assert out.flags == ["window_disagrees"]
    assert out.logic["window"] == {"from_days": pair[0], "to_days": pair[1]}


def test_every_distinct_stated_window_is_carried_by_some_atom() -> None:
    """W10: two 30-day windows do not cover a line that states 30 and 90 days; nor do no windows at all."""
    text = "Surgery within 30 days before screening and chemotherapy within 90 days before screening"
    thirty = {"op": "and", "args": [_atom(from_days=-30, to_days=0), _atom(from_days=-30, to_days=0)]}
    assert reconcile(text, thirty).flags == ["window_unattached"]
    assert reconcile(text, {"op": "and", "args": [_atom(), _atom()]}).flags == ["window_unattached"]
    fine = {"op": "and", "args": [_atom(from_days=-30, to_days=0), _atom(from_days=-90, to_days=0)]}
    assert reconcile(text, fine).flags == []
    twice = "Surgery within 30 days before screening or chemotherapy within 30 days before screening"
    assert reconcile(twice, {"op": "or", "args": [_atom(from_days=-30, to_days=0), _atom()]}).flags == []


def test_an_hour_window_is_compared_in_hours() -> None:
    """W11: 96 hours is four days; an hour window on an atom without one is flagged, never written."""
    assert reconcile("Chemotherapy within 96 hours before screening", _atom(from_days=-4, to_days=0)).flags == []
    out = reconcile("Chemotherapy within 96 hours before screening", _atom())
    assert out.flags == ["window_unattached"] and "window" not in out.logic
