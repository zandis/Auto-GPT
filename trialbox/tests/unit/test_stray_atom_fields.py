"""F4 and G10 of the integrator's reviews of the P1b run (#639, 2026-11-16), D-948. sigir's extracted criteria
(``raw-traces.json``, public SIGIR protocols) carried fields their atoms cannot use; the compile ignored or refused
them. The lines below are the run's own.

* A demographic atom's derived / quantifier / value / count / window / duration are dropped (``stray_field``);
  an unambiguous age written in ``value`` becomes ``age`` (``value_read_as_age``); a ``none`` on a negated line goes
  to a person.
* On any other atom a derived name off an observation is dropped; an age is dropped unless the line writes its numbers
  beside an age word (an age at onset), which goes to a person.
"""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import Atom, LlmExtractOutput


def _one(text: str, logic: dict[str, Any], kind: str = "inclusion", concepts: list[dict[str, str]] | None = None,
         cls: str = "structured") -> tuple[Any, Any]:  # fmt: skip
    crit = {"kind": kind, "class": cls, "text": text, "logic": logic, "concept_candidates": concepts or []}
    post = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), Terminology(), "1.0.0")
    (c,) = post.criteria
    return c, post


def _age(c: Any) -> tuple[Any, Any]:
    assert isinstance(c.logic, Atom) and c.logic.age is not None, c.logic
    return c.logic.age.min, c.logic.age.max


def test_p1b_nct00606840_exc02_loses_its_quantifier_and_derived() -> None:
    c, post = _one("Age outside of range specified", {"domain": "demographic", "concept": "age", "quantifier": "all",
                   "age": {"min": 18, "max": 35}, "derived": "egfr"}, kind="exclusion")  # fmt: skip
    # what this card does, whatever D-945 then makes of the range (with no inclusion here, a person reads it)
    assert "stray_field" in (c.flags or []) and not any(k.startswith("VS_EGFR") for k in post.valuesets)
    assert isinstance(c.logic, Atom) and c.logic.derived is None and c.logic.quantifier == "any"


@pytest.mark.parametrize(
    ("text", "logic"),
    [
        ("Aged 40 years or older", {"domain": "demographic", "concept": "age", "quantifier": "none", "age": {"min": 40}}),
        ("Aged 18 years or older", {"domain": "demographic", "concept": "age", "quantifier": "count>=", "count": 1,
                                    "age": {"min": 18}}),
        ("Age <= 50 years", {"domain": "demographic", "concept": "age", "quantifier": "count>=", "count": 1,
                             "age": {"max": 50}}),
        ("Female participants only", {"domain": "demographic", "concept": "sex", "quantifier": "none", "sex": "female"}),
    ],
)  # fmt: skip
def test_a_demographic_atoms_stray_fields_are_dropped_and_it_compiles(text: str, logic: dict[str, Any]) -> None:
    c, _ = _one(text, logic)
    assert c.class_ == "structured" and "stray_field" in (c.flags or []), text
    assert isinstance(c.logic, Atom) and c.logic.quantifier == "any" and c.logic.count is None


def test_a_demographic_none_on_a_negated_line_goes_to_a_person() -> None:
    c, _ = _one("Not aged 18 to 65", {"domain": "demographic", "quantifier": "none", "age": {"min": 18, "max": 65}})
    assert c.class_ == "human" and "demographic_negated" in (c.flags or [])


@pytest.mark.parametrize(
    ("text", "value", "age"),
    [
        ("Aged 50 years or older", {"op": ">=", "num": 50, "unit": "years"}, (50, None)),
        ("Age 18-65", {"op": "between", "num": 18, "num2": 65, "unit": "years"}, (18, 65)),
        ("65歳以下", {"op": "<=", "num": 65, "unit": "歳"}, (None, 65)),
    ],
)
def test_an_unambiguous_age_in_value_is_read_as_age(text: str, value: dict[str, Any], age: tuple[Any, Any]) -> None:
    c, _ = _one(text, {"domain": "demographic", "concept": "age", "quantifier": "all", "value": value})
    assert c.class_ == "structured" and "value_read_as_age" in (c.flags or []) and _age(c) == age, text


@pytest.mark.parametrize(
    ("text", "logic"),
    [
        ("Age 50 to 89 years", {"domain": "demographic", "concept": "age", "value": {"op": ">=", "num": 50}}),  # 89
        ("Aged 5 years or older", {"domain": "demographic", "concept": "age", "value": {"op": ">=", "unit": "years"}}),
        ("Age > 18", {"domain": "demographic", "concept": "age", "value": {"op": ">", "num": 18}}),  # 18 or 19?
        # D-948's review: no unit said, a shorter unit, not an age
        ("18 and over", {"domain": "demographic", "concept": "age", "value": {"op": ">=", "num": 18}}),
        ("Aged 6 months or older", {"domain": "demographic", "concept": "age", "value": {"op": ">=", "num": 6}}),
        ("Gestational age >= 32 weeks", {"domain": "demographic", "value": {"op": ">=", "num": 32}}),
        ("Body weight >= 40", {"domain": "demographic", "value": {"op": ">=", "num": 40}}),
        ("Cigarette smoking greater than or equal to 30 pack years",
         {"domain": "demographic", "concept": "smoking_history", "value": {"op": ">=", "num": 30, "unit": "pack_years"}}),
    ],
)  # fmt: skip
def test_an_ambiguous_value_is_not_read_as_age(text: str, logic: dict[str, Any]) -> None:
    c, _ = _one(text, logic)
    assert "value_read_as_age" not in (c.flags or []) and c.class_ == "human", text  # no age, no sex: a person


def test_the_prompts_placeholders_on_a_condition_are_not_compiled() -> None:
    # D-948's review: dropping the placeholder derived name put the prompt's other junk in front of patients; it is
    # left for ``kind`` to refuse, as before, and the line goes to a person
    c, _ = _one(
        "DISEASE CHARACTERISTICS: Histologically confirmed esophageal squamous cell cancer that is stage T2-3 Nx M0",
        {"domain": "condition", "concept": "esophageal squamous cell carcinoma", "window": {"anchor": "index"},
         "age": {"min": 0, "max": 150}, "derived": "asdas"},
        concepts=[{"domain": "condition", "name": "esophageal squamous cell carcinoma"}],
    )  # fmt: skip
    assert c.class_ == "human" and "logic_invalid" in (c.flags or [])


def test_an_exclusions_age_in_value_is_never_repaired() -> None:
    c, _ = _one("Males and females aged 18-55 years", {"domain": "demographic", "concept": "age",
                "value": {"op": "between", "num": 18, "num2": 55, "unit": "years"}}, kind="exclusion")  # fmt: skip
    assert "value_read_as_age" not in (c.flags or []) and c.class_ == "human"


@pytest.mark.parametrize(
    ("text", "age"),
    [("Type 2 diabetes diagnosed before age 30", {"max": 30}), ("SLE before the age of 40", {"max": 39}),
     ("Type 2 diabetes diagnosed before 40", {"max": 39}), ("SLE with age less than 22", {"max": 21}),
     ("発症年齢が40歳未満の糖尿病", {"max": 39})],
)  # fmt: skip
def test_an_age_at_onset_on_a_condition_goes_to_a_person_not_widened(text: str, age: dict[str, int]) -> None:
    c, _ = _one(text, {"domain": "condition", "concept": "Diabetes", "age": age}, kind="exclusion",
                concepts=[{"name": "Diabetes", "domain": "condition"}])  # fmt: skip
    assert c.class_ == "human" and "age_on_non_demographic" in (c.flags or []), text


def test_a_held_mixed_line_keeps_its_note_question() -> None:
    text = "Children aged 1 to 12 years with CAP"
    crit = {"kind": "inclusion", "class": "mixed", "text": text,
            "note_question": "Does the child have community-acquired pneumonia?", "concept_candidates": [
                {"name": "Pneumonia", "domain": "condition"}],
            "logic": {"domain": "condition", "concept": "Pneumonia", "age": {"min": 1, "max": 12}}}  # fmt: skip
    (c,) = pp.postprocess(
        "T",
        LlmExtractOutput.model_validate({"criteria": [crit]}),
        Terminology(),
        "1.0.0",
        sources=[pp.PresenceSource(text, "inclusion", "en")],
    ).criteria
    assert c.class_ == "note" and c.note_question and "age_on_non_demographic" in (c.flags or [])


def test_a_plain_demographic_atom_is_not_flagged() -> None:
    c, _ = _one("Women aged 18 or older", {"domain": "demographic", "quantifier": "any", "age": {"min": 18},
                                           "sex": "female"})  # fmt: skip
    assert c.class_ == "structured" and not c.flags
