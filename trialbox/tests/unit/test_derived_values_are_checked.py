"""G5 of the integrator's second review of the P1b run (#639, 2026-11-16), D-956: on NCT01187901 the model wrote a
derived name that does not exist with ``value.op "in"``; ``semantics.kind`` returned DERIVED without ``check_value``
and the CQL held ``(None in { })``, which failed the translator. The run's traces show the model copying the prompt's
example names onto atoms that are not those scores ("sdai" on a brain injury, "egfr" on an FEV1/FVC ratio or on a
serum creatinine, which would compile as eGFR < 0.7 or > 3.0).

* ``kind``: a derived value is a score this box computes, with a numeric comparison (``check_value``; no ``in``).
* ``postprocess``: a derived value runs only when its line names that score; else the coded part cannot run.
* Every shipped derived criterion names its score (the 13 atoms of the shipped rulesets).

Lines from the run's public SIGIR protocols; no patient rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from criteria_compiler.ir_extract import postprocess as pp
from criteria_compiler.semantics import CompileError, atoms, kind
from criteria_compiler.terminology.mapper import Terminology
from tb_contracts import Atom, AtomValue, CriterionIR, LlmExtractOutput

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("derived", "value", "why"),
    [("cholesterol_ratio", {"op": ">", "num": 5}, "not one this box computes"),
     ("asdas", {"op": "in", "codes": ["1"]}, "is a number"), ("egfr", None, "needs a comparison"),
     ("egfr", {"op": "between", "num": 30}, "requires num and num2")],
)  # fmt: skip
def test_a_derived_value_is_a_known_score_compared_as_a_number(derived: str, value: Any, why: str) -> None:
    v = AtomValue(**value) if value else None  # model_construct: the contract's enum refuses an unknown name already
    atom = Atom.model_construct(domain="observation", valueset="VS_X", derived=derived, value=v, quantifier="any")
    with pytest.raises(CompileError, match=why):
        kind(atom)


def _one(text: str, logic: dict[str, Any], kind_: str = "inclusion", cls: str = "structured") -> Any:
    crit = {"kind": kind_, "class": cls, "text": text, "logic": logic, "concept_candidates": []}
    (c,) = pp.postprocess("T", LlmExtractOutput.model_validate({"criteria": [crit]}), Terminology(), "1.0.0").criteria
    return c


@pytest.mark.parametrize(
    ("text", "logic", "kind_"),
    [
        ("Forced Expiratory Volume in one second (FEV1) ≤ 70 % of predicted value and FEV1 / Forced Vital Capacity < 0.7",
         {"domain": "observation", "concept": "FEV1_FVC_ratio", "quantifier": "all", "value": {"op": "<", "num": 0.7},
          "derived": "egfr"}, "inclusion"),
        ("Serum Creatinine > 3.0 mg/dL in patients who are not in hemodialysis.",
         {"domain": "observation", "concept": "serum_creatinine", "value": {"op": ">", "num": 3.0, "unit": "mg/dL"},
          "derived": "egfr"}, "exclusion"),
        ("Adequate bone marrow function as show by: normal leukocyte count, platelet count",
         {"domain": "observation", "concept": "bone marrow function", "value": {"op": "in", "num": 1, "unit": "n/a"},
          "derived": "asdas"}, "inclusion"),
    ],
)  # fmt: skip
def test_the_runs_misplaced_derived_names_never_compile(text: str, logic: dict[str, Any], kind_: str) -> None:
    c = _one(text, logic, kind_)
    assert c.class_ == "human" and "logic_invalid" in (c.flags or []), text


@pytest.mark.parametrize(
    ("text", "derived", "value"),
    [("BMI between 21 and 30", "bmi", {"op": "between", "num": 21, "num2": 30}),
     ("eGFRが30 mL/min/1.73m²未満の者", "egfr_jsn", {"op": "<", "num": 30}),
     ("DAS28-CRP of 3.2 or more", "das28", {"op": ">=", "num": 3.2})],
)  # fmt: skip
def test_a_derived_value_its_line_names_compiles(text: str, derived: str, value: dict[str, Any]) -> None:
    c = _one(text, {"domain": "observation", "concept": derived, "derived": derived, "value": value})
    assert c.class_ == "structured" and "logic_invalid" not in (c.flags or []), text


def test_every_shipped_derived_criterion_names_its_score() -> None:
    seen = 0
    for f in sorted(ROOT.glob("rulesets/*/ir/*.json")):
        c = CriterionIR.model_validate(json.loads(f.read_text(encoding="utf-8")))
        for a in atoms(c.logic) if c.logic is not None else []:
            if a.derived:
                seen += 1
                kind(a)
                assert pp.derived_said(a.derived, c.text), f.name
    assert seen >= 13
