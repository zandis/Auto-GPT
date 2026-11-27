"""OPT-1 W3 (D-1318): the window rules are the first step of ``postprocess``; the anchor enum of IR 3.x grows
(``enrollment``, ``consent``, ``first_dose``, ``last_dose``, ``end_of_study``); compile checks (iii) to (v).

* a window the line says is read by rules, and the rule's wins where the model's differs (flagged, needs review);
* a window the line never says, or a duration ("stable dose for 3 months"), is not a window;
* a window counted from the study's own dosing or end is held for a person;
* a line in Chinese, Japanese or Korean is left to the model;
* the new anchors have no v1 form (``NotV1Expressible``, by name) and are not compiled (``CompileError``);
* a window of more than ten years, more than 72 hours counted in hours, or the same length as window and duration, is
  refused.

Public protocol text; no patient rows."""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.ir_extract import window_rules
from criteria_compiler.semantics import CompileError, lower, window
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import Atom, LlmExtractOutput
from tb_contracts.criterion_ir import STUDY_ANCHORS, CriterionIRv3, NotV1Expressible, downgrade_to_v1, upgrade_v1

pytestmark = pytest.mark.nodb

DRUG = {"domain": "medication", "concept": "Chemotherapy", "quantifier": "any"}
CONCEPTS = [{"name": "Chemotherapy", "domain": "medication"}]


def _one(text: str, win: dict[str, Any] | None, cls: str = "structured", extra: dict[str, Any] | None = None) -> Any:
    logic = {**DRUG, **({"window": win} if win else {}), **(extra or {})}
    crit = {"kind": "exclusion", "class": cls, "text": text, "logic": logic, "concept_candidates": CONCEPTS}
    if cls == "mixed":
        crit["note_question"] = "Did the patient have chemotherapy?"
    out = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), Terminology(), "1.0.0")
    return out.criteria[0], out.warnings


def test_a_window_the_model_got_wrong_is_the_rules() -> None:
    c, warns = _one("Chemotherapy within 30 days before screening", {"from_days": -14, "to_days": 0})
    assert c.class_ == "structured"
    assert (c.logic.window.from_days, c.logic.window.to_days) == (-30, 0)
    assert {"window_rules_override", "needs_review"} <= set(c.flags)
    assert any("window" in w for w in warns)


def test_an_agreeing_window_is_not_flagged() -> None:
    c, _ = _one("Chemotherapy within 30 days before screening", {"from_days": -30, "to_days": 0})
    assert not any(f.startswith("window_") for f in c.flags or [])


def test_a_window_the_line_never_says_is_left_alone_by_default() -> None:
    c, _ = _one("Chemotherapy", {"from_days": -45, "to_days": 0})
    assert (c.logic.window.from_days, c.logic.window.to_days) == (-45, 0)
    assert not any(f.startswith("window_") for f in c.flags or [])


def test_a_window_the_line_never_says_is_dropped_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(window_rules, "DROP_UNSTATED_WINDOWS", True)
    c, _ = _one("Chemotherapy", {"from_days": -45, "to_days": 0})
    assert c.logic.window is None
    assert {"window_not_in_text", "needs_review"} <= set(c.flags)


def test_a_stable_dose_duration_is_not_a_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(window_rules, "DROP_UNSTATED_WINDOWS", True)
    c, _ = _one("Chemotherapy at a stable dose for at least 3 months", {"from_days": -90, "to_days": 0})
    assert c.logic.window is None
    assert "window_not_in_text" in c.flags


def test_a_window_from_the_last_dose_goes_to_a_person() -> None:
    c, warns = _one("Chemotherapy within 30 days of last dose", {"from_days": -30, "to_days": 0})
    assert c.class_ == "human"
    assert {"window_anchor_unsupported", "needs_review"} <= set(c.flags)
    assert any("last dose" in w for w in warns)


def test_a_mixed_line_from_the_last_dose_keeps_its_note_question() -> None:
    c, _ = _one("Chemotherapy within 30 days of last dose", {"from_days": -30, "to_days": 0}, cls="mixed")
    assert c.class_ == "note"
    assert c.note_question


def test_a_line_in_chinese_is_left_to_the_model() -> None:
    c, _ = _one("六個月內曾使用化療", {"from_days": -180, "to_days": 0})
    assert (c.logic.window.from_days, c.logic.window.to_days) == (-180, 0)
    assert not any(f.startswith("window_") for f in c.flags or [])


def test_a_window_with_no_word_about_time_is_refused_when_the_rules_abstain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(window_rules, "DROP_UNSTATED_WINDOWS", True)
    c, warns = _one("Chemotherapy before the biopsy", {"from_days": -30, "to_days": 0})
    assert c.class_ == "human"
    assert "window_invented" in c.flags
    assert any("Chemotherapy before the biopsy" in w for w in warns)


# ----------------------------------------------------------------------------------------------------- the enum
def _with_window(ir: CriterionIRv3, **fields: Any) -> CriterionIRv3:
    atoms = []
    for a in ir.atoms:
        assert a.window is not None
        atoms.append(a.model_copy(update={"window": a.window.model_copy(update=fields)}))
    return ir.model_copy(update={"atoms": atoms})


def _v3(anchor: str) -> CriterionIRv3:
    logic = {
        "domain": "medication",
        "valueset": "VS_X",
        "quantifier": "any",
        "window": {"from_days": -30, "to_days": 0},
    }
    v1 = {"id": "T-EXC-01", "ruleset": "T", "kind": "exclusion", "class": "structured", "text": "x", "logic": logic}
    return _with_window(upgrade_v1({**v1, "review": {"status": "draft"}}), anchor=anchor)


@pytest.mark.parametrize("anchor", STUDY_ANCHORS)
def test_the_new_anchors_are_valid_in_ir_3_and_have_no_v1_form(anchor: str) -> None:
    ir = CriterionIRv3.model_validate(_v3(anchor).model_dump(mode="json", by_alias=True, exclude_unset=True))
    with pytest.raises(NotV1Expressible, match=anchor):
        downgrade_to_v1(ir)


@pytest.mark.parametrize("anchor", STUDY_ANCHORS)
def test_the_new_anchors_are_refused_by_name_when_an_ir_3_criterion_is_lowered(anchor: str) -> None:
    with pytest.raises(CompileError, match=anchor):
        lower(_v3(anchor))


@pytest.mark.parametrize(("hours", "why"), [(90, "more than 72 hours"), (48, "counted in hours")])
def test_a_window_in_hours_is_not_compiled_and_one_beyond_72_says_why(hours: int, why: str) -> None:
    ir = _with_window(_v3("index"), from_days=-hours, unit="h")
    with pytest.raises(CompileError, match=why):
        lower(ir)


@pytest.mark.parametrize("anchor", STUDY_ANCHORS)
def test_the_new_anchors_are_not_compiled(anchor: str) -> None:
    atom = Atom.model_validate({
        "domain": "medication", "valueset": "VS_X", "quantifier": "any",
        "window": {"from_days": -30, "to_days": 0, "anchor": "event"},
    })  # fmt: skip
    assert atom.window is not None
    atom.window.anchor = anchor  # type: ignore[assignment]
    with pytest.raises(CompileError, match=anchor):
        window(atom)


# ------------------------------------------------------------------------------------- compile checks (iv) and (v)
def _atom(win: dict[str, Any], duration: dict[str, Any] | None = None) -> Atom:
    d: dict[str, Any] = {"domain": "medication", "valueset": "VS_X", "quantifier": "any", "window": win}
    if duration:
        d["duration"] = duration
    return Atom.model_validate(d)


def test_a_window_of_more_than_ten_years_is_refused() -> None:
    with pytest.raises(CompileError, match="ten years"):
        window(_atom({"from_days": -36500, "to_days": 0}))
    assert window(_atom({"from_days": -3650, "to_days": 0})).from_days == -3650


def test_the_same_length_as_window_and_duration_is_refused() -> None:
    with pytest.raises(CompileError, match="window and a duration"):
        window(_atom({"from_days": -90, "to_days": 0}, {"min_days": 90}))
    assert window(_atom({"from_days": -365, "to_days": 0}, {"min_days": 90})).from_days == -365  # a course in a window
