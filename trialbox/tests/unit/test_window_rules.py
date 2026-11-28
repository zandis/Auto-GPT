"""The window rules (``ir_extract.window_rules``): the expected readings of public registry text, the adjudicated
rule-versus-model pairs, and the intervals the rules read. What ``advise`` says is in ``test_window_advisory``.

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
    advise,
    interval,
    parse_window,
    parse_windows,
    reads_text,
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
    # a row the fixture marks "abstains" (a bare window before a clause that names its event may share that event, so
    # the rules do not read it one way) is not confident and nothing is said about it; every other row is judged alike
    assert all(r.high_confidence for r in results) == (row["rules_ok"] and not row.get("abstains"))
    if row.get("abstains"):
        assert advise(row["text"], {"op": "and", "args": [_atom(from_days=-180), _atom(from_days=-60)]}) == []


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


def _atom(**w: Any) -> dict[str, Any]:
    a: dict[str, Any] = {"domain": "medication", "valueset": "NONE", "quantifier": "any"}
    if w:
        a["window"] = w
    return a


# ------------------------------------------------------------------------------------------------ boundaries and forms
def _win(text: str) -> Any:
    (r,) = (x for x in parse_windows(text) if x.kind == "window")
    return r


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("diagnosis <7 days ago", (-6, 0)),  # W06: strict, one day inside; no tolerance on an explicit day count
        ("diagnosed less than 7 days ago", (-6, 0)),
        ("diagnosis within 7 days before screening", (-7, 0)),
        ("diagnosis at least 7 days ago", (None, -7)),
        ("diagnosis more than 7 days ago", (None, -8)),
        ("diagnosis 7 days ago", None),  # W05: an offset, which an interval does not encode
    ],
)
def test_day_boundaries_are_exact(text: str, want: tuple[int | None, int | None] | None) -> None:
    assert interval(_win(text)) == want


def test_a_bare_ago_is_an_offset_not_a_lookback() -> None:
    assert _win("Surgery 30 days ago").bound == "exact"
    assert _win("Surgery at least 30 days ago").bound == "at_least"
    assert _win("Surgery in the past 30 days").bound == "within"
    assert _win("Surgery within 30 days before screening").bound == "within"


def test_a_bare_within_has_no_side_of_the_anchor() -> None:
    """ "within 1 month" with no before, after, last, past or next says no side; the rules never pick one."""
    r = _win("Do not agree to join the experiment, plan to move out or go out within 1 month.")
    assert (r.relation, interval(r)) == ("", None)
    assert interval(_win("Planned surgery within the next 6 months")) == (0, 180)
    assert interval(_win("Surgery within the last 6 months")) == (-180, 0)


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
    """ "no more than" is not "more than"; a strict bound is one day inside the inclusive one."""
    assert interval(_win(text)) == want


def test_a_course_up_to_a_named_date_is_not_a_minimum_distance() -> None:
    """ "no antidiabetic drugs for at least 12 weeks prior to informed consent" is 12 drug-free weeks up to consent, not
    a drug 12 weeks before it."""
    (text,) = (r["text"] for r in GOLD if r["gid"] == 248)
    r = _win(text)
    assert (r.win_val, r.win_unit, r.anchor, r.relation, r.bound) == (12, "week", "consent", "prior to", "course")
    assert interval(r) is None


@pytest.mark.parametrize("text", ["Treatment -7 days before screening", "Treatment \u22127 days before screening"])
def test_a_negative_amount_is_not_confident(text: str) -> None:
    """A signed negative amount (D-914) has no sure reading; it is never read as the positive one."""
    assert not all(r.high_confidence for r in parse_windows(text))
    assert advise(text, _atom(from_days=-7, to_days=0)) == []


def test_a_spaced_dash_is_a_range_not_a_sign() -> None:
    assert all(r.reason != NEGATIVE for r in parse_windows("aged 6 months - 17 years"))
    assert all(r.reason != NEGATIVE for r in parse_windows("Chemotherapy within 2 - 4 weeks before screening"))


def test_alternative_anchors_are_not_cut_to_the_first() -> None:
    """ "before screening or first dose" names two dates; one window cannot say which: not confident."""
    text = "Chemotherapy within 7 days before screening or first dose"
    assert not all(r.high_confidence for r in parse_windows(text))
    assert advise(text, _atom(from_days=-7, to_days=0)) == []


def test_an_unbounded_first_dose_clause_is_read_beside_a_numeric_one() -> None:
    text = "Chemotherapy in the past month and surgery prior to the first dose"
    assert any(r.anchor == "first_dose" and r.relation == "unbounded" for r in parse_windows(text))
    first = "Prior to the first dose and within 30 days of screening"  # the clause before the number too
    assert any(r.anchor == "first_dose" and r.relation == "unbounded" for r in parse_windows(first))


def test_a_line_in_a_script_the_rules_do_not_read_is_left_alone() -> None:
    assert not reads_text("六個月內曾使用降尿酸藥物。")
    assert advise("六個月內曾使用降尿酸藥物。", _atom(from_days=-180, to_days=0)) == []


def test_a_comparison_such_as_at_least_is_no_event() -> None:
    r = _win("Most recent serum urate in the last year at least 7.0 mg/dL.")
    assert (r.anchor, r.high_confidence) == ("screening", True)
