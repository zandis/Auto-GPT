"""The atomicity checker (PROFILE-1 A1.4 one-of-each): a fixture per reason, the clean atom, and the lint at load."""

from __future__ import annotations

import copy
import json
import logging
import shutil
from pathlib import Path
from typing import Any

import pytest
from tb_common.ruleset import Ruleset
from tb_contracts.atomicity import REASONS, check_atom, check_criterion
from tb_contracts.criterion_ir import Atom, CriterionIRv3

ROOT = Path(__file__).resolve().parents[2]
ATOM: dict[str, Any] = {
    "id": "a1",
    "domain": "observation",
    "valueset": "VS_ALT",
    "quantifier": "latest",
    "value": {"op": ">", "num": 120, "unit": "U/L"},
    "window": {"from_days": -180, "to_days": 0, "anchor": "index"},
}


def _edit(**kv: Any) -> dict[str, Any]:
    a = copy.deepcopy(ATOM)
    for k, v in kv.items():
        if v is None:
            a.pop(k, None)
        else:
            a[k] = v
    return a


W = ATOM["window"]
FIXTURES: list[tuple[str, dict[str, Any]]] = [
    ("two_subjects", _edit(subject=["patient", "parent"])),
    ("two_data_kinds", _edit(domain=["observation", "condition"])),
    ("two_concept_sets", _edit(valueset=["VS_ALT", "VS_AST"])),
    ("two_comparisons", _edit(value=[{"op": ">", "num": 120}, {"op": "<", "num": 400}])),
    ("two_comparisons", _edit(domain="demographic", valueset="NONE", value=None, age={"min": 18}, sex="female")),
    ("two_comparisons", _edit(attribute={"path": "ecog", "op": "<=", "num": 1, "source_priority": ["note"]})),
    ("two_windows", _edit(window=[W, {**W, "from_days": -30}])),
    ("two_durations", _edit(duration=[{"min_days": 90}, {"min_days": 30}])),
    ("two_evaluations", _edit(quantifier=["latest", "any"])),
    ("no_concept_set", _edit(valueset=None)),
    ("negation_in_atom", _edit(quantifier="none")),
    ("negation_in_atom", _edit(valueset="VS_MALIGNANCY_EXCEPT_NON_MELANOMA_SKIN_CANCER")),
    ("negation_in_atom", _edit(valueset="no-prior-biologic")),
    ("window_without_anchor", _edit(window={"from_days": -180, "to_days": 0})),
    ("window_without_anchor", _edit(window={**W, "anchor": "event"})),
    ("mixed_subject", _edit(subject=["parent", "donor"])),
]


def test_the_reason_list_is_closed_and_every_reason_has_a_fixture() -> None:
    assert sorted({r for r, _ in FIXTURES}) == sorted(REASONS)


@pytest.mark.parametrize(("reason", "atom"), FIXTURES, ids=[f"{r}-{i}" for i, (r, _) in enumerate(FIXTURES)])
def test_each_reason(reason: str, atom: dict[str, Any]) -> None:
    assert reason in check_atom(atom)


@pytest.mark.parametrize(
    "atom",
    [
        ATOM,
        _edit(quantifier="any", value=None),  # a bare concept set: an existence test
        _edit(domain="demographic", valueset="NONE", value=None, quantifier=None, age={"min": 18, "max": 75}),
        _edit(domain="demographic", valueset=None, value=None, quantifier=None, sex="female"),
        _edit(value={"lo": 10, "lo_incl": True, "hi": 20, "hi_incl": False}),
        _edit(derived={"calc": "egfr_ckd_epi_2021@1.0.0"}),  # a bare calculator: `value` is the one comparison
        _edit(window={**W, "anchor": "event", "event_atom": "dx"}),
        _edit(window={"from_days": -90, "to_days": 0, "anchor_text": "start of the run-in period"}),
        _edit(window={**W, "anchor": "last_dose"}, duration={"min_days": 90}),
        _edit(valueset="VS_NONSTEROIDAL_ANTI_INFLAMMATORY"),  # a word that merely starts with "non" is no negation
        _edit(subject="parent"),
    ],
)
def test_atomic_atoms_pass(atom: dict[str, Any]) -> None:
    assert check_atom(atom) == []
    assert check_atom(Atom.model_validate(atom)) == []  # the same answer on the validated model


def test_reasons_come_sorted_and_once() -> None:
    packed = _edit(valueset=["VS_A", "VS_B"], quantifier="none", window={"from_days": -1}, subject=["parent", "x"])
    got = check_atom(packed)
    assert got == sorted(set(got))
    assert set(got) == {
        "two_concept_sets",
        "negation_in_atom",
        "window_without_anchor",
        "two_subjects",
        "mixed_subject",
    }


def _crit(atoms: list[dict[str, Any]], logic: Any) -> CriterionIRv3:
    return CriterionIRv3.model_validate(
        {
            "ir_version": "3.1.0",
            "id": "SYN-INC-01",
            "ruleset": "SYN/v1.0.0",
            "kind": "inclusion",
            "class": "structured",
            "text": {"source": "x"},
            "logic": logic,
            "atoms": atoms,
        }
    )


def test_mixed_subject_across_referenced_atoms() -> None:
    dx = {"id": "dx", "domain": "condition", "valueset": "VS_AF", "quantifier": "any", "subject": "parent"}
    reads = _edit(window={**W, "anchor": "event", "event_atom": "dx"})
    assert check_criterion(_crit([reads, dx], {"op": "and", "args": ["a1", "dx"]})) == {"a1": ["mixed_subject"]}
    switched = _edit(value_if=[{"if_atom": "dx", "value": {"op": ">", "num": 200}}])
    assert check_criterion(_crit([switched, dx], {"op": "and", "args": ["a1", "dx"]})) == {"a1": ["mixed_subject"]}
    dx_patient = {**dx, "subject": "patient"}
    assert check_criterion(_crit([reads, dx_patient], {"op": "and", "args": ["a1", "dx"]})) == {}
    assert check_criterion(_crit([reads, {**dx, "subject": None}], {"op": "and", "args": ["a1", "dx"]})) == {}


def test_the_lint_runs_at_ruleset_load(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    rs = shutil.copytree(ROOT / "rulesets" / "RA-COH", tmp_path / "RA-COH")
    assert Ruleset.load(rs).lint == {}
    path = sorted((rs / "ir").glob("*.json"))[0]
    doc = json.loads(path.read_text("utf-8"))
    node = doc["logic"]
    while "domain" not in node:
        node = node["args"][0]
    node["quantifier"] = "none"  # polarity packed into the atom
    path.write_text(json.dumps(doc), encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="tb_common.ruleset"):
        loaded = Ruleset.load(rs)  # a lint, not a refusal: the ruleset still loads
    assert loaded.lint == {f"{doc['id']}.a1": ["negation_in_atom"]}
    assert "fail the atomicity lint" in caplog.text and loaded.criteria


def test_the_live_exception_folded_into_a_concept_set_is_linted() -> None:
    assert Ruleset.load(ROOT / "rulesets" / "GZQO").lint["GZQO-EXC-07.a1"] == ["negation_in_atom"]
