"""F2 of the integrator's root-cause review of the P1b run (#639, 2026-11-16), D-946: NCT01260883 INC-02 "Aged 0.17
years or older" compiled as ``age.min 0.17`` (INC-03: 1.5). The age is counted in complete years (D-442, ``AGE_SQL``,
CQL ``AgeInYearsAt``), so a two-month-old is 0 and never met 0.17: every infant failed an inclusion they meet.

* A non-integer age bound is a ``CompileError`` (``semantics.kind``): ``postprocess`` flags it ``logic_invalid`` and
  a person reads it; ``demote_uncompilable`` moves an approved one to a person; the generators refuse it.
* Whole-year bounds compile as before (the shipped rulesets are unchanged: ``build_rulesets --check``).

Public protocol text; no patient rows.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from criteria_compiler.compile_cql.generator import CqlGenerator
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.semantics import CompileError, kind
from criteria_compiler.service import Compiler
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from tb_contracts import Atom, CriterionIR, LlmExtractOutput


def _inc(age: dict[str, float]) -> CriterionIR:
    return CriterionIR.model_validate({"id": "T-INC-02", "ruleset": "T", "kind": "inclusion", "class": "structured",
                                       "text": "Aged 0.17 years or older", "review": {"status": "approved"},
                                       "logic": {"domain": "demographic", "valueset": "NONE", "age": age}})  # fmt: skip


@pytest.mark.parametrize("age", [{"min": 0.17}, {"min": 1.5}, {"max": 17.5}, {"min": 0.5, "max": 2}])
def test_a_fractional_age_bound_is_not_compiled(age: dict[str, float]) -> None:
    atom = Atom(domain="demographic", valueset="NONE", age=age)  # type: ignore[arg-type]
    with pytest.raises(CompileError, match="whole number of years"):
        kind(atom)
    vsi = ValueSets("T", {}, Terminology())
    for gen in (SqlGenerator("T", "1.0.0", vsi), CqlGenerator("T", "1.0.0", vsi)):
        with pytest.raises(CompileError):
            gen.render([_inc(age)])


def test_p1b_nct01260883_an_infant_is_not_failed_on_0_17_years() -> None:
    out = LlmExtractOutput.model_validate({"criteria": [
        {"kind": "inclusion", "class": "structured", "text": "Aged 0.17 years or older",
         "logic": {"domain": "demographic", "age": {"min": 0.17}}, "concept_candidates": []}]})  # fmt: skip
    (c,) = pp.postprocess("T", out, Terminology(), "1.0.0").criteria
    assert c.class_ == "human" and {"needs_review", "logic_invalid"} <= set(c.flags or [])  # a person, never FALSE


def test_an_approved_fractional_bound_goes_to_a_person_and_the_rest_compiles() -> None:
    whole = _inc({"min": 18}).model_copy(update={"id": "T-INC-01", "text": "Aged 18 or older"})
    comp = Compiler(SimpleNamespace(term=Terminology()))  # type: ignore[arg-type]
    out, warnings = comp.demote_uncompilable("T", "1.0.0", [whole, _inc({"min": 0.17})], {})
    by_id = {c.id: c for c in out}
    assert by_id["T-INC-01"].class_ == "structured"
    assert by_id["T-INC-02"].class_ == "human" and "compile_error" in (by_id["T-INC-02"].flags or [])
    assert any("whole number of years" in w for w in warnings)


@pytest.mark.parametrize("age", [{"min": 0}, {"min": 18.0}, {"min": 2, "max": 17}])
def test_whole_years_compile_as_before(age: dict[str, float]) -> None:
    assert kind(Atom(domain="demographic", valueset="NONE", age=age)).value == "demographic"  # type: ignore[arg-type]
