"""D-418 (T-619c; D-275 open point 3): a lab criterion whose unit would read every result as unknown is flagged.

"creatinine <= 1.5" with no unit reads only results recorded with no unit, so it is unknown for every patient; a
glucose criterion in mmol/L is unknown for a site that reports mg/dL. The compiler now says so to the reviewer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from criteria_compiler import unit_check
from criteria_compiler.ir_extract.postprocess import postprocess
from criteria_compiler.terminology.mapper import Concept, ConceptMapLLM, MappingResult, Terminology, valueset
from tb_contracts import Atom, LlmExtractOutput

LOINC = "http://loinc.org"
CREAT, GLUCOSE, HBA1C, DAS28 = "2160-0", "2345-7", "4548-4", "8664-5"
INR = "34714-6"


def _vs(code: str) -> dict[str, Any]:
    return valueset("U", "VS_X", "x", [Concept(LOINC, code, code)], "1.0.0")


def _atom(value: dict[str, Any] | None, **extra: Any) -> Atom:
    return Atom.model_validate(
        {"domain": "observation", "quantifier": "latest", "valueset": "VS_X", "value": value, **extra}
    )


def test_a_lab_number_with_no_unit_is_flagged_with_the_unit_it_is_reported_in() -> None:
    got = unit_check.check(_atom({"op": "<=", "num": 1.5}), _vs(CREAT))
    assert got is not None and got[0] == unit_check.MISSING and "mg/dL" in got[1]
    got = unit_check.check(_atom({"op": "<=", "num": 1.5, "unit": "{score}"}), _vs(CREAT))
    assert got is not None and got[0] == unit_check.MISSING


def test_a_unit_the_result_cannot_be_converted_from_is_flagged() -> None:
    got = unit_check.check(_atom({"op": "<", "num": 7.0, "unit": "mmol/L"}), _vs(GLUCOSE))
    assert got is not None and got[0] == unit_check.UNCONVERTIBLE and "mg/dL" in got[1]
    got = unit_check.check(_atom({"op": ">", "num": 53, "unit": "mmol/mol"}), _vs(HBA1C))
    assert got is not None and got[0] == unit_check.UNCONVERTIBLE


def test_a_unit_that_is_or_converts_to_the_usual_one_is_not_flagged() -> None:
    assert unit_check.check(_atom({"op": "<=", "num": 1.5, "unit": "mg/dL"}), _vs(CREAT)) is None
    assert unit_check.check(_atom({"op": "<=", "num": 1.5, "unit": "mg/dl"}), _vs(CREAT)) is None
    assert unit_check.check(_atom({"op": "<=", "num": 132.6, "unit": "umol/L"}), _vs(CREAT)) is None  # D-275 factor
    assert unit_check.check(_atom({"op": ">", "num": 10, "unit": "%"}), _vs(HBA1C)) is None


def test_numbers_that_have_no_unit_and_atoms_without_a_number_are_not_checked() -> None:
    assert unit_check.check(_atom({"op": ">=", "num": 20}), _vs(DAS28)) is None  # {pack-years}: a number
    assert unit_check.check(_atom({"op": ">", "num": 3}), _vs(INR)) is None  # {INR}: a number
    assert unit_check.check(_atom({"op": "in", "codes": ["LA6576-8"]}), _vs(CREAT)) is None
    assert unit_check.check(_atom(None), _vs(CREAT)) is None
    assert unit_check.check(_atom({"op": "<=", "num": 1.5}), _vs("99999-9")) is None  # not in the catalogue
    assert unit_check.check(_atom({"op": "<=", "num": 1.5}), None) is None
    derived = _atom({"op": "<", "num": 30}, derived="egfr", valueset="VS_EGFR_COMPONENTS")
    assert unit_check.check(derived, _vs(CREAT)) is None


class _Creatinine(Terminology):
    """A terminology that maps "creatinine" to LOINC 2160-0 (the built tables are not needed here)."""

    def __init__(self) -> None:
        super().__init__(directory=Path("/nonexistent"))

    def map(
        self, domain: str, name: str, synonyms: list[str] | None = None, llm: ConceptMapLLM | None = None
    ) -> MappingResult:
        return MappingResult(name, domain, [Concept(LOINC, CREAT, "Creatinine")], "exact", False)


def test_the_compiler_flags_the_criterion_for_review() -> None:
    def crit(unit: str | None) -> dict[str, Any]:
        value: dict[str, Any] = {"op": "<=", "num": 1.5}
        if unit:
            value["unit"] = unit
        return {
            "text": "serum creatinine <= 1.5",
            "kind": "inclusion",
            "class": "structured",
            "logic": {"domain": "observation", "concept": "creatinine", "quantifier": "latest", "value": value},
            "concept_candidates": [{"domain": "observation", "name": "creatinine"}],
        }

    post = postprocess("U", LlmExtractOutput.model_validate({"criteria": [crit(None), crit("mg/dL")]}), _Creatinine())
    (vs,) = post.valuesets.values()
    assert (LOINC, CREAT) in unit_check.valueset_codes(vs)
    no_unit, with_unit = post.criteria
    assert no_unit.flags is not None and {"needs_review", unit_check.MISSING} <= set(no_unit.flags)
    assert unit_check.MISSING not in (with_unit.flags or [])
    assert any(w.startswith(f"{no_unit.id}: the number has no unit") for w in post.warnings)
