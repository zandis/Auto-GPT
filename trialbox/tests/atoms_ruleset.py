"""Helper building the ATOMS test ruleset (every atom type / quantifier / bool form) for unit and gate tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from criteria_compiler.ir_extract.postprocess import derived_valueset
from criteria_compiler.terminology.mapper import Terminology, ValueSets, valueset
from tb_contracts import CriterionIR

FIX = Path(__file__).resolve().parent / "fixtures" / "ir"


def atoms_ruleset(term: Terminology | None = None) -> tuple[list[CriterionIR], dict[str, dict[str, Any]], ValueSets]:
    term = term or Terminology()
    crit = [CriterionIR.model_validate(x) for x in json.loads((FIX / "atoms_ruleset.json").read_text("utf-8"))]
    vs: dict[str, dict[str, Any]] = {}
    for name, (domain, concept) in json.loads((FIX / "atoms_concepts.json").read_text("utf-8")).items():
        res = term.map(domain, concept)
        assert res.concepts, (name, concept)
        vs[name] = valueset("ATOMS", name, concept, res.concepts, "1.0.0")
    for d in ("bmi", "das28", "egfr"):
        vs[f"VS_{d.upper()}_COMPONENTS"] = derived_valueset("ATOMS", d, "1.0.0", term)
    return crit, vs, ValueSets("ATOMS", vs, term)
