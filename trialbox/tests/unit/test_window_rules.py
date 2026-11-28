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
RIGHT = [r for r in PAIRS if r["rules_ok"]]
WRONG = [r for r in PAIRS if not r["rules_ok"]]


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


@pytest.mark.parametrize("row", RIGHT, ids=[str(r["gid"]) for r in RIGHT])
def test_adjudicated_pair(row: dict[str, Any]) -> None:
    assert sorted(_shown(row["text"])) == sorted(row["rules"])


#: the safe outcome of each line the third reader judged the rules wrong on: the rules claim nothing (``abstain``: an
#: anchor that is another tumour, a clause, or holds a second anchor) or the criterion goes to a person (``hold``: the
#: other window counts from randomization)
SAFE = {87: "abstain", 358: "abstain", 408: "hold", 425: "abstain"}


@pytest.mark.parametrize("row", WRONG, ids=[str(r["gid"]) for r in WRONG])
def test_a_reading_the_third_reader_judged_wrong_is_never_acted_on(row: dict[str, Any]) -> None:
    logic = _atom(from_days=-30, to_days=0)
    out = reconcile(row["text"], logic)
    assert out.logic["window"] == {"from_days": -30, "to_days": 0}
    if SAFE[row["gid"]] == "abstain":
        assert not all(r.high_confidence for r in parse_windows(row["text"]))
        assert out.flags == [] and out.hold is None
    else:
        assert out.flags == ["window_anchor_unsupported"] and out.hold is not None


def test_every_wrong_reading_has_its_safe_outcome() -> None:
    assert sorted(SAFE) == sorted(r["gid"] for r in WRONG)


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
        ("within 48 hours after first dose", (0, 2)),
        ("at least 6 months before randomization", (None, -180)),
        ("at least 6 months after randomization", (180, None)),
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
    out = reconcile("Chemotherapy within 30 days before screening", _atom(from_days=-14, to_days=0))
    assert out.flags == ["window_rules_override"]
    assert out.logic["window"] == {"from_days": -30, "to_days": 0, "anchor": "index"}


def test_twelve_months_and_a_year_are_one_window() -> None:
    out = reconcile("Chemotherapy within the 12 months before screening", _atom(from_days=-365, to_days=0))
    assert out.flags == []
    assert out.logic["window"] == {"from_days": -365, "to_days": 0}
    out = reconcile("Chemotherapy within the 12 months before screening", _atom(from_days=-300, to_days=0))
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
    out = reconcile("Chemotherapy within 30 days before screening", _atom())
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


def test_registration_is_held_as_randomization_is() -> None:
    """Registration is a date after the screening run: the window is not rewritten to one from screening (R1)."""
    out = reconcile("Chemotherapy within 30 days before registration", _atom(from_days=-14, to_days=0))
    assert out.flags == ["window_anchor_unsupported"]
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


# --------------------------------------------- review 1627.1, findings R1 to R8 (R4 in test_window_rules_postprocess)
def test_r1_a_window_before_randomization_is_held_not_counted_from_screening() -> None:
    for logic in (_atom(from_days=-7, to_days=0), _atom()):
        out = reconcile("Haemoglobin measured within 7 days before randomization", logic)
        assert out.flags == ["window_anchor_unsupported"]
        assert out.hold is not None and "randomization" in out.hold


@pytest.mark.parametrize("neg", ["no more than", "not more than", "no greater than"])
def test_r2_no_more_than_is_a_within(neg: str) -> None:
    (r,) = parse_windows(f"Surgery {neg} 30 days before screening")
    assert (r.bound, interval(r)) == ("within", (-30, 0))
    out = reconcile(f"Surgery {neg} 30 days before screening", _atom(to_days=-30))
    assert out.flags == ["window_rules_override"]
    assert out.logic["window"] == {"from_days": -30, "to_days": 0, "anchor": "index"}


def test_r2_more_than_stays_a_minimum_distance() -> None:
    (r,) = parse_windows("Surgery more than 30 days before screening")
    assert (r.bound, interval(r)) == ("at_least", (None, -30))


def test_r3_a_drug_free_period_is_not_an_exposure_older_than_it() -> None:
    text = "1 drug-naïve, defined as no antidiabetic drugs for at least 12 weeks prior to informed consent, or"
    (r,) = parse_windows(text)
    assert (r.win_val, r.win_unit, r.anchor, r.bound, interval(r)) == (12, "week", "consent", "period", (-84, 0))
    assert reconcile(text, _atom(to_days=-84)).hold is not None  # consent is not the screening date
    screening = "No antidiabetic drugs for at least 12 weeks prior to screening"
    for wrong in (_atom(to_days=-84), _atom()):  # the open-ended search, or none: a person reads it
        out = reconcile(screening, wrong)
        assert out.flags == ["window_anchor_unsupported"] and out.hold is not None
        assert out.logic.get("window") == wrong.get("window")
    out = reconcile(screening, _atom(from_days=-84, to_days=0))
    assert out.flags == [] and out.hold is None


def test_r5_one_window_is_not_written_over_the_atom_of_a_pair() -> None:
    pair = {"op": "or", "args": [_atom(from_days=-14, to_days=0), _atom()]}
    out = reconcile("Prior chemotherapy or radiotherapy in the past 30 days", pair)
    assert out.flags == ["window_disagrees"]
    assert out.logic["args"][0]["window"] == {"from_days": -14, "to_days": 0}
    assert "window" not in out.logic["args"][1]


def test_r6_a_planned_move_within_a_month_is_in_the_future() -> None:
    text = "Do not agree to join the experiment, plan to move out or go out within 1 month."
    (r,) = parse_windows(text)
    assert (r.win_val, r.win_unit, r.anchor, r.relation) == (1, "month", "screening", "after")
    out = reconcile(text, _atom(from_days=-30, to_days=0))
    assert out.flags == ["window_anchor_unsupported"]
    assert out.hold is not None and "after screening" in out.hold
    assert out.logic["window"] == {"from_days": -30, "to_days": 0}


def test_r6_a_window_counted_from_another_tumour_is_not_read() -> None:
    text = "Synchronous or metachronous (within 5 years) malignancy"
    assert not all(r.high_confidence for r in parse_windows(text))


def test_r7_an_index_window_does_not_stand_in_for_one_before_surgery() -> None:
    out = reconcile("Anticoagulant use within seven days before surgery", _atom(from_days=-7, to_days=0))
    assert out.flags == ["window_anchor_unsupported"]
    assert out.hold is not None and "surgery" in out.hold


def test_r8_prior_to_the_first_dose_with_no_number_is_held() -> None:
    out = reconcile("Systemic corticosteroids prior to the first dose of study drug", _atom(from_days=-30, to_days=0))
    assert out.flags == ["window_anchor_unsupported"]
    assert out.hold is not None and "first dose" in out.hold
