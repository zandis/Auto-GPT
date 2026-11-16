"""F4 of the integrator's root-cause review of the P1b run (#639, 2026-11-16), D-948: sigir's 772 compiled criteria
carried 25 quantifiers, 6 values and 5 derived on demographic atoms, and 9 ages on other atoms; NCT00606840 EXC-02
was ``{"domain":"demographic","quantifier":"all","age":{"min":18,"max":35},"derived":"egfr"}``.

* A demographic atom's derived / quantifier / value / count / window / duration are dropped, flagged ``stray_field``.
* A demographic ``quantifier: none`` (it may mean "not") and an age on any other atom (it may be an age at onset;
  dropping it would widen the criterion) go to a person.

Public protocol text; no patient rows.
"""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import Atom, LlmExtractOutput


def _one(logic: dict[str, Any], kind: str = "inclusion", concepts: list[dict[str, str]] | None = None) -> Any:
    crit = {"kind": kind, "class": "structured", "text": "line", "logic": logic, "concept_candidates": concepts or []}
    post = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), Terminology(), "1.0.0")
    (c,) = post.criteria
    return c, post


def test_p1b_nct00606840_exc02_loses_its_quantifier_and_derived() -> None:
    c, post = _one({"domain": "demographic", "quantifier": "all", "age": {"min": 18, "max": 35}, "derived": "egfr"},
                   kind="exclusion")  # fmt: skip
    assert isinstance(c.logic, Atom) and c.logic.derived is None and c.logic.quantifier == "any"
    assert c.logic.age is not None and (c.logic.age.min, c.logic.age.max) == (18, 35)
    assert "stray_field" in (c.flags or []) and not any(k.startswith("VS_EGFR") for k in post.valuesets)


@pytest.mark.parametrize(
    "extra",
    [{"value": {"op": ">=", "num": 18}}, {"count": 2}, {"window": {"from_days": -30}}, {"quantifier": "latest"}],
)
def test_a_demographic_atoms_stray_field_is_dropped(extra: dict[str, Any]) -> None:
    c, _ = _one({"domain": "demographic", "age": {"min": 18}, **extra})
    assert c.class_ == "structured" and "stray_field" in (c.flags or [])
    assert isinstance(c.logic, Atom) and c.logic.value is None and c.logic.count is None and c.logic.window is None


def test_a_plain_demographic_atom_is_not_flagged() -> None:
    c, _ = _one({"domain": "demographic", "quantifier": "any", "age": {"min": 18}, "sex": "female"})
    assert c.class_ == "structured" and not {"stray_field", *pp.HOLD} & set(c.flags or [])


def test_a_demographic_none_goes_to_a_person() -> None:
    c, _ = _one({"domain": "demographic", "quantifier": "none", "age": {"max": 17}})
    assert c.class_ == "human" and "demographic_quantifier_none" in (c.flags or [])


def test_an_age_on_a_condition_goes_to_a_person_not_widened() -> None:
    c, _ = _one({"domain": "condition", "concept": "Type 2 diabetes", "age": {"max": 30}}, kind="exclusion",
                concepts=[{"name": "Type 2 diabetes", "domain": "condition"}])  # fmt: skip
    assert c.class_ == "human" and "age_on_non_demographic" in (c.flags or [])
