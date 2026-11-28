"""The window rules are advisory (``ir_extract.window_rules``): where a criterion line and the extraction's time windows
differ, the criteria reviewer is told; nothing is overwritten, dropped, decided or compiled differently.

Each wrong-exclusion shape of the closed review (W01 to W06) is a case: the extraction is FLAGGED for the reviewer
and NOT applied (its logic is the same before and after the parser ran, and a postprocessed criterion is the same
with the parser switched off). Public protocol wording; no patient rows."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.ir_extract import window_rules
from criteria_compiler.ir_extract.window_rules import advise, say
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import Atom, LlmExtractOutput

pytestmark = pytest.mark.nodb

WINDOW_WORDS = (
    "the line and the extracted time window differ; check it",
    "条文と抽出された期間",
    "條文與擷取的時間範圍",
)


def _atom(concept: str, domain: str = "medication", **win: Any) -> dict[str, Any]:
    a: dict[str, Any] = {"domain": domain, "concept": concept, "quantifier": "any"}
    if win:
        a["window"] = win
    return a


def _all(*atoms: dict[str, Any]) -> dict[str, Any]:
    return atoms[0] if len(atoms) == 1 else {"op": "or", "args": list(atoms)}


CHEMO, SURGERY = "Chemotherapy", "Surgery"
#: (id, line, extraction, class): each is a reading that excluded a wrong patient when it was applied
SHAPES = [
    ("W01", "Chemotherapy within 30 days of last dose", _all(_atom(CHEMO, from_days=-30, to_days=0)), "mixed"),
    (
        "W02",
        "Chemotherapy within 7 days before randomization",
        _all(_atom(CHEMO, from_days=-7, to_days=0)),
        "structured",
    ),
    (
        "W03",
        "Surgery within 30 days and chemotherapy within 90 days before screening",
        _all(_atom(SURGERY, "procedure", from_days=-90, to_days=0), _atom(CHEMO, from_days=-30, to_days=0)),
        "structured",
    ),
    (
        "W04",
        "Surgery within 30 days or chemotherapy within 30 days",
        _all(_atom(SURGERY, "procedure", from_days=-30, to_days=0), _atom(CHEMO)),
        "structured",
    ),
    ("W05", "Surgery 30 days ago", _all(_atom(SURGERY, "procedure", from_days=-30, to_days=0)), "structured"),
    ("W06", "Diagnosis <7 days ago", _all(_atom("Diagnosis", "condition", from_days=-7, to_days=0)), "structured"),
]
IDS = [s[0] for s in SHAPES]


def _extract(text: str, logic: dict[str, Any], cls: str) -> LlmExtractOutput:
    concepts = [{"name": a["concept"], "domain": a["domain"]} for a in _atoms(logic)]
    crit: dict[str, Any] = {
        "kind": "exclusion",
        "class": cls,
        "text": text,
        "logic": logic,
        "concept_candidates": concepts,
    }
    if cls == "mixed":
        crit["note_question"] = "Did the patient have chemotherapy?"
    return LlmExtractOutput.model_validate({"criteria": [crit]})


def _atoms(logic: dict[str, Any]) -> list[dict[str, Any]]:
    args: list[dict[str, Any]] = logic.get("args", [logic])
    return args


def _dump(out: Any) -> str:
    criteria = [c.model_dump(mode="json", by_alias=True, exclude_none=True) for c in out.criteria]
    return json.dumps({"criteria": criteria, "valuesets": out.valuesets}, sort_keys=True)


@pytest.mark.parametrize(("sid", "text", "logic", "cls"), SHAPES, ids=IDS)
def test_a_wrong_exclusion_shape_is_flagged_not_applied(
    sid: str, text: str, logic: dict[str, Any], cls: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = copy.deepcopy(logic)
    advice = advise(text, logic)
    assert advice, sid  # FLAGGED for the reviewer
    assert logic == before, sid  # NOT applied: the extraction is byte-identical after the parser ran
    assert json.dumps(logic, sort_keys=True) == json.dumps(before, sort_keys=True)

    on = pp.postprocess("T", _extract(text, copy.deepcopy(logic), cls), Terminology(), "1.0.0")
    monkeypatch.setattr(window_rules, "advise", lambda *_: [])
    off = pp.postprocess("T", _extract(text, copy.deepcopy(logic), cls), Terminology(), "1.0.0")
    assert _dump(on) == _dump(off), sid  # no class, flag, window or code of any criterion differs
    said = [w for w in on.warnings if w not in off.warnings]
    assert len(said) == len(advice) and all(w.startswith("T-EXC-01: ") for w in said), sid
    assert all(all(words in w for words in WINDOW_WORDS) for w in said), sid
    assert off.warnings == [w for w in on.warnings if w not in said]


def test_w01_a_mixed_criterion_keeps_its_class_and_its_question() -> None:
    text, logic = SHAPES[0][1], SHAPES[0][2]
    out = pp.postprocess("T", _extract(text, copy.deepcopy(logic), "mixed"), Terminology(), "1.0.0")
    (c,) = out.criteria
    assert c.class_ == "mixed"
    assert c.note_question == "Did the patient have chemotherapy?"
    assert isinstance(c.logic, Atom)
    assert c.logic.window is not None and (c.logic.window.from_days, c.logic.window.to_days) == (-30, 0)


def test_w02_the_anchor_is_compared_as_well_as_the_offsets() -> None:
    (adv,) = advise("Chemotherapy within 7 days before randomization", _atom(CHEMO, from_days=-7, to_days=0))
    assert adv.stated is not None and adv.stated.anchor == "randomization"
    assert adv.extracted[0].anchor == "index"
    # the same offsets from the run's own date agree
    assert advise("Chemotherapy within 7 days before screening", _atom(CHEMO, from_days=-7, to_days=0)) == []


def test_w03_each_window_is_compared_with_its_own_clause() -> None:
    text = SHAPES[2][1]
    right = _all(_atom(SURGERY, "procedure", from_days=-30, to_days=0), _atom(CHEMO, from_days=-90, to_days=0))
    assert advise(text, right) == []
    swapped = advise(text, SHAPES[2][2])
    assert len(swapped) == 2  # both atoms differ from their own clause
    assert {adv.extracted[0].who for adv in swapped} == {SURGERY, CHEMO}


def test_w03_an_ambiguous_clause_lists_every_atoms_window_side_by_side() -> None:
    both = _all(_atom("Alpha agent", from_days=-30, to_days=0), _atom("Beta agent", from_days=-90, to_days=0))
    (adv,) = advise("Treatment within 30 days before screening", both)
    assert adv.unclear and [e.who for e in adv.extracted] == ["Alpha agent", "Beta agent"]
    # agreeing on every atom, which atom the clause is for does not matter
    same = _all(_atom("Alpha agent", from_days=-30, to_days=0), _atom("Beta agent", from_days=-30, to_days=0))
    assert advise("Treatment within 30 days before screening", same) == []


def test_w04_each_clause_keeps_its_own_window() -> None:
    (adv,) = advise(SHAPES[3][1], SHAPES[3][2])
    assert adv.stated is not None and adv.extracted[0].who == CHEMO and adv.extracted[0].unit == ""  # no window at all
    both = _all(_atom(SURGERY, "procedure", from_days=-30, to_days=0), _atom(CHEMO, from_days=-30, to_days=0))
    assert advise(SHAPES[3][1], both) == []


def test_w05_a_bare_ago_is_an_offset() -> None:
    assert advise("Surgery 30 days ago", _atom(SURGERY, "procedure", from_days=-30, to_days=-30)) == []
    (adv,) = advise("Surgery 30 days ago", _atom(SURGERY, "procedure", from_days=-30, to_days=0))
    assert (adv.stated.lo, adv.stated.hi) == (-30, -30) and (adv.extracted[0].lo, adv.extracted[0].hi) == (-30, 0)  # type: ignore[union-attr]


def test_w06_a_day_count_is_exact() -> None:
    assert advise("Diagnosis <7 days ago", _atom("Diagnosis", "condition", from_days=-6, to_days=0)) == []
    (adv,) = advise("Diagnosis <7 days ago", _atom("Diagnosis", "condition", from_days=-7, to_days=0))
    assert (adv.stated.lo, adv.stated.hi) == (-6, 0)  # type: ignore[union-attr]
    for text, win in [("within 7 days", (-8, 0)), ("within 7 days", (-6, 0)), ("within 2 weeks", (-13, 0))]:
        assert advise(
            f"Diagnosis {text} before screening", _atom("Diagnosis", "condition", from_days=win[0], to_days=0)
        )
    # a month or a year has no length in days: 12 months is a year
    assert advise("Chemotherapy within 12 months before screening", _atom(CHEMO, from_days=-365, to_days=0)) == []


def test_agreeing_and_unreadable_lines_get_no_advice() -> None:
    assert advise("Chemotherapy within 30 days before screening", _atom(CHEMO, from_days=-30, to_days=0)) == []
    assert advise("Recently treated with a stable regimen", _atom(CHEMO, from_days=-14, to_days=0)) == []
    assert advise("Surgery in the preceding year", _atom(SURGERY, "procedure", from_days=-365, to_days=0)) == []
    assert advise("History of stroke", {"domain": "demographic"}) == []


def test_a_window_the_line_never_says_is_told_not_dropped() -> None:
    logic = _atom("Alanine aminotransferase", "observation", from_days=-45, to_days=0)
    before = copy.deepcopy(logic)
    (adv,) = advise("Normal liver function tests", logic)
    assert adv.stated is None and logic == before
    (adv,) = advise("Stable dose of aspirin for at least 3 months", _atom("Aspirin", from_days=-90, to_days=0))
    assert adv.stated is None


def test_a_window_counted_from_another_event_or_the_study_dosing_is_told() -> None:
    (adv,) = advise("Chemotherapy within 30 days after surgery", _atom(CHEMO, from_days=0, to_days=30))
    assert adv.stated is not None and adv.stated.anchor == "surgery"
    (adv,) = advise("Radiotherapy within 30 days of last dose", _atom("Radiotherapy", from_days=-30, to_days=0))
    assert adv.stated is not None and adv.stated.anchor == "last_dose"
    (adv,) = advise("Chemotherapy prior to the first dose", _atom(CHEMO, from_days=-30, to_days=0))
    assert adv.stated is not None and adv.stated.anchor == "first_dose"
    assert advise("Chemotherapy prior to the first dose", _atom(CHEMO)) == []  # no window given: any time
    # the atom is the named event itself: the window from the index date is the line's, compared by length
    assert advise("At least 14 days since surgery", _atom(SURGERY, "procedure", to_days=-14)) == []
    assert advise("At least 14 days since surgery", _atom(SURGERY, "procedure", to_days=-30))


def test_a_window_the_extraction_lacks_is_told() -> None:
    (adv,) = advise("Chemotherapy in the past 30 days", _atom(CHEMO))
    assert adv.stated is not None and (adv.stated.lo, adv.stated.hi) == (-30, 0) and adv.extracted[0].unit == ""
    (adv,) = advise("Chemotherapy within 96 hours before screening", _atom(CHEMO, from_days=-2, to_days=0))
    assert (adv.stated.lo, adv.stated.unit, adv.extracted[0].lo) == (-96, "hour", -48)  # type: ignore[union-attr]
    assert advise("Chemotherapy within 96 hours before screening", _atom(CHEMO, from_days=-4, to_days=0)) == []


def test_the_reviewers_sentence_has_three_languages_and_both_windows() -> None:
    (adv,) = advise(*SHAPES[5][1:3])
    line = say("T-EXC-01", adv)
    assert line.startswith("T-EXC-01: ")
    assert all(words in line for words in WINDOW_WORDS)
    assert line.count("[-6 .. 0]") == 3 and line.count("[-7 .. 0]") == 3  # the line's and the extraction's, in each
    assert "window_" not in line and "needs_review" not in line  # no internal flag name
    (adv,) = advise("Chemotherapy within 7 days before randomization", _atom(CHEMO, from_days=-7, to_days=0))
    line = say("T-EXC-01", adv)
    assert all(w in line for w in ("randomization", "無作為化", "隨機分派", "基準日"))
