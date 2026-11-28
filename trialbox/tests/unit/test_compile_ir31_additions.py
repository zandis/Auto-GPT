"""The IR 3.1 additions on the compile path: ``subject: patient`` lowers as its absence; the others are refused by name."""

from __future__ import annotations

from typing import Any

import pytest
from criteria_compiler.semantics import CompileError, lower
from tb_contracts.criterion_ir import CriterionIRv3


def _crit(**atom: Any) -> CriterionIRv3:
    a: dict[str, Any] = {
        "id": "a1",
        "domain": "observation",
        "valueset": "VS_ALT",
        "quantifier": "latest",
        "value": {"op": ">", "num": 120, "unit": "U/L"},
        "window": {"from_days": -180, "to_days": 0, "anchor": "index"},
    }
    for k, v in atom.items():
        a[k] = {**a["window"], **v} if k == "window" else v
    return CriterionIRv3.model_validate(
        {
            "ir_version": "3.1.0",
            "id": "SYN-EXC-01",
            "ruleset": "SYN/v1.0.0",
            "kind": "exclusion",
            "class": "structured",
            "text": {"source": "ALT > 120 U/L in the last 180 days"},
            "logic": "a1",
            "atoms": [a],
        }
    )


def test_subject_patient_lowers_as_the_plain_atom() -> None:
    plain, _ = lower(_crit())
    patient, _ = lower(_crit(subject="patient"))
    assert patient.model_dump(mode="json", exclude_none=True) == plain.model_dump(mode="json", exclude_none=True)


@pytest.mark.parametrize(
    ("atom", "named"),
    [
        ({"subject": "parent"}, "subject"),
        ({"window": {"anchor_text": "start of the run-in period"}}, "window.anchor_text"),
        ({"window": {"anchor": "first_dose"}}, "window anchor first_dose"),
        ({"value": {"lo": 10, "lo_incl": True, "hi": 20, "hi_incl": True, "unit": "U/L"}}, "value.hi"),
    ],
)
def test_the_other_additions_are_refused_by_name(atom: dict[str, Any], named: str) -> None:
    with pytest.raises(CompileError, match=named):
        lower(_crit(**atom))
