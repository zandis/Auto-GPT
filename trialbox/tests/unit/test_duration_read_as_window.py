"""ASSESS-1 Q1 (P-07): the box's criteria step with its own served pair. One ir_extract call on six plain criteria came
back with all six ``structured``, but the three time limits ("within the last 6 months", "within the last 3 months")
written as ``window: {anchor: index}`` with no bounds and ``duration: {min_days: -180}``. A duration of at most 0 days
is met by everyone (D-914), so each of the three went to a person. A bare window and a negative duration together say
"looking back N days from the index": that is read as the window from -N to 0 (``duration_read_as_window``), only when
the line writes that period. Anything else stays as D-914 left it.

The reply below is the recorded answer of that call (synthetic criteria); only the model's own text is kept.
"""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import LlmExtractOutput

REPLY: dict[str, Any] = {"criteria": [
    {"text": "Age 20 to 75 years.", "source_ref": "I1", "kind": "inclusion", "class": "structured",
     "logic": {"domain": "demographic", "age": {"min": 20, "max": 75}},
     "concept_candidates": [{"domain": "demographic", "name": "age", "synonyms": ["age", "年齡"]}]},
    {"text": "A diagnosis of gout (ICD-10 M10).", "source_ref": "I2", "kind": "inclusion", "class": "structured",
     "logic": {"domain": "claim", "concept": "gout", "quantifier": "any"},
     "concept_candidates": [{"domain": "claim", "name": "gout", "synonyms": ["gout", "痛風", "ICD-10 M10"]}]},
    {"text": "Serum uric acid at or above 7.0 mg/dL within the last 6 months.", "source_ref": "I3", "kind": "inclusion",
     "class": "structured",
     "logic": {"domain": "observation", "concept": "serum uric acid", "quantifier": "any",
               "value": {"op": ">=", "num": 7.0}, "window": {"anchor": "index"}, "duration": {"min_days": -180}},
     "concept_candidates": [{"domain": "observation", "name": "serum uric acid",
                             "synonyms": ["serum uric acid", "血清尿酸", "uric acid level"]}]},
    {"text": "eGFR below 30 mL/min/1.73m2 within the last 6 months.", "source_ref": "E1", "kind": "exclusion",
     "class": "structured",
     "logic": {"domain": "observation", "concept": "eGFR", "quantifier": "any", "value": {"op": "<", "num": 30},
               "window": {"anchor": "index"}, "duration": {"min_days": -180}},
     "concept_candidates": [{"domain": "observation", "name": "eGFR",
                             "synonyms": ["eGFR", "估計腎絲球過濾率", "estimated glomerular filtration rate"]}]},
    {"text": "Pregnancy.", "source_ref": "E2", "kind": "exclusion", "class": "structured",
     "logic": {"domain": "demographic", "concept": "pregnancy", "quantifier": "any"},
     "concept_candidates": [{"domain": "demographic", "name": "pregnancy", "synonyms": ["pregnancy", "懷孕"]}]},
    {"text": "Febuxostat taken within the last 3 months.", "source_ref": "E3", "kind": "exclusion", "class": "structured",
     "logic": {"domain": "medication", "concept": "febuxostat", "quantifier": "any", "window": {"anchor": "index"},
               "duration": {"min_days": -90}},
     "concept_candidates": [{"domain": "medication", "name": "febuxostat", "synonyms": ["febuxostat", "非布司亭"]}]},
]}  # fmt: skip


def _post(reply: dict[str, Any]) -> Any:
    return pp.postprocess("GOUT-301", LlmExtractOutput.model_validate(reply), Terminology(), "1.0.0")


def _window(c: Any) -> tuple[Any, Any]:
    w = c.logic.window
    return (w.from_days, w.to_days) if w is not None else (None, None)


def test_the_recorded_reply_keeps_its_time_limits_as_windows() -> None:
    by_ref = {c.source_ref: c for c in _post(REPLY).criteria}
    for ref, days in (("I3", -180), ("E1", -180), ("E3", -90)):
        c = by_ref[ref]
        assert c.class_ == "structured" and "duration_read_as_window" in (c.flags or []), ref
        assert _window(c) == (days, 0) and c.logic.duration is None, ref
    assert by_ref["I1"].class_ == "structured" and by_ref["I2"].class_ == "structured"
    assert by_ref["E2"].class_ == "human"  # a demographic atom without age or sex: still a person's (no repair)


FEBUXOSTAT = [{"domain": "medication", "name": "febuxostat", "synonyms": ["febuxostat"]}]


def _one(text: str, logic: dict[str, Any]) -> Any:
    crit = {"kind": "exclusion", "class": "structured", "text": text, "logic": logic, "concept_candidates": FEBUXOSTAT}
    (c,) = _post({"criteria": [crit]}).criteria
    return c


def test_the_same_atom_with_its_window_written_out_compiles() -> None:
    """The control: what the repair produces is what a model that writes the window itself gets."""
    c = _one("Febuxostat taken within the last 3 months.", {"domain": "medication", "concept": "febuxostat",
             "quantifier": "any", "window": {"from_days": -90, "to_days": 0}})  # fmt: skip
    assert c.class_ == "structured" and _window(c) == (-90, 0)


@pytest.mark.parametrize(
    ("text", "logic"),
    [
        # the line writes no such period (90 days is not "3 weeks"): D-914's refusal stands
        ("Febuxostat within the last 3 weeks.", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
        # a window with bounds of its own: the duration is not read into it
        (
            "Febuxostat within the last 3 months.",
            {"window": {"from_days": -30, "to_days": 0}, "duration": {"min_days": -90}},
        ),
        # no window at all: nothing says "relative to the index"
        ("Febuxostat within the last 3 months.", {"duration": {"min_days": -90}}),
        # the period turned round or a duration (Codex review R1): never read as "within"
        ("Febuxostat taken more than 3 months ago.", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
        ("On febuxostat for at least 3 months.", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
        ("Febuxostat for 3 months or longer.", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
        ("3か月以上フェブキソスタットを服用", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
        # the tail of a grouped number is not a period (Codex review R2): 1,090 days never stands for 90
        ("Febuxostat within the last 1,090 days.", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
        ("1,090日以内のフェブキソスタット", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
        # a negated line, also with the atom under "not": left for a person
        ("No febuxostat within the last 3 months.", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
        # a bare "within N" says no direction, past or future (PR review R1, F2): moved here from the forms read
        ("Febuxostat within 12 weeks.", {"window": {"anchor": "index"}, "duration": {"min_days": -84}}),
        ("3か月以内のフェブキソスタット", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
        (
            "Start febuxostat within 12 weeks after enrollment.",
            {"window": {"anchor": "index"}, "duration": {"min_days": -84}},
        ),
        # a period turned forward or held over its length (PR review R1, F1, F2)
        (
            "Febuxostat started in the past 3 months following surgery.",
            {"window": {"anchor": "index"}, "duration": {"min_days": -90}},
        ),
        (
            "Febuxostat taken since diagnosis in the last 3 months.",
            {"window": {"anchor": "index"}, "duration": {"min_days": -90}},
        ),
        (
            "Febuxostat taken continuously throughout the last 3 months.",
            {"window": {"anchor": "index"}, "duration": {"min_days": -90}},
        ),
        (
            "On a stable dose of febuxostat for the past 3 months.",
            {"window": {"anchor": "index"}, "duration": {"min_days": -90}},
        ),
        (
            "Febuxostat for 3 consecutive months in the last 6 months.",
            {"window": {"anchor": "index"}, "duration": {"min_days": -180}},
        ),
        ("過去3か月間継続してフェブキソスタットを服用", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
        # a duration with another bound: reading it as a window would drop that bound (PR review F3)
        (
            "Febuxostat within the last 6 months.",
            {"window": {"anchor": "index"}, "duration": {"min_days": -180, "gap_days": 14}},
        ),
        # two periods on the line: which one is the atom's is not said (PR review F4)
        (
            "Febuxostat within the last 3 months or the last 6 months.",
            {"window": {"anchor": "index"}, "duration": {"min_days": -90}},
        ),
        # the tail of a number grouped with a fullwidth separator (PR review F5)
        ("1，090日以内のフェブキソスタット", {"window": {"anchor": "index"}, "duration": {"min_days": -90}}),
    ],
)
def test_anything_else_with_a_negative_duration_still_goes_to_a_person(text: str, logic: dict[str, Any]) -> None:
    c = _one(text, {"domain": "medication", "concept": "febuxostat", "quantifier": "any", **logic})
    assert c.class_ == "human" and "duration_read_as_window" not in (c.flags or []), logic


def test_an_atom_under_not_on_a_negated_line_is_not_read() -> None:
    atom = {"domain": "medication", "concept": "febuxostat", "quantifier": "any", "window": {"anchor": "index"},
            "duration": {"min_days": -90}}  # fmt: skip
    c = _one("No febuxostat in the last 3 months.", {"op": "not", "args": [atom]})
    assert "duration_read_as_window" not in (c.flags or [])
    # the repair step itself left the atom as it was (PR review F6): a person's line shows no logic to check
    node, flags = pp.strip_stray({"op": "not", "args": [atom]}, "No febuxostat in the last 3 months.", "exclusion")
    assert node["args"][0] == atom and "duration_read_as_window" not in flags


def _atom(concept: str, days: int) -> dict[str, Any]:
    return {"domain": "observation" if concept == "eGFR" else "medication", "concept": concept, "quantifier": "any",
            "window": {"anchor": "index"}, "duration": {"min_days": days}}  # fmt: skip


@pytest.mark.parametrize(
    ("text", "args"),
    [
        # one atom carrying the other clause's period (PR review R2)
        (
            "Febuxostat within the last 3 months or allopurinol within the last 6 months.",
            [_atom("febuxostat", -90), _atom("allopurinol", -90)],
        ),
        # the two periods swapped between the atoms (PR review F4)
        (
            "eGFR below 30 within the last 6 months or febuxostat within the last 3 months.",
            [_atom("eGFR", -90), _atom("febuxostat", -180)],
        ),
    ],
)
def test_a_compound_line_still_goes_to_a_person(text: str, args: list[dict[str, Any]]) -> None:
    c = _one(text, {"op": "or", "args": args})
    assert c.class_ == "human" and "duration_read_as_window" not in (c.flags or []), text


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("Febuxostat in the past 3 months.", -90),
        ("過去6か月以内にフェブキソスタットを服用", -180),
    ],
)
def test_a_look_back_period_is_read_in_its_forms(text: str, days: int) -> None:
    c = _one(text, {"domain": "medication", "concept": "febuxostat", "quantifier": "any", "window": {"anchor": "index"},
                    "duration": {"min_days": days}})  # fmt: skip
    assert c.class_ == "structured" and "duration_read_as_window" in (c.flags or []) and _window(c) == (days, 0), text


def test_a_real_duration_is_left_as_it_is() -> None:
    c = _one("On febuxostat for at least 3 months.", {"domain": "medication", "concept": "febuxostat",
             "quantifier": "any", "window": {"anchor": "index"}, "duration": {"min_days": 90}})  # fmt: skip
    assert c.logic.duration is not None and c.logic.duration.min_days == 90
    assert "duration_read_as_window" not in (c.flags or [])
