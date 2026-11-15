"""The parity property of the structured verdict table (T-652, ENG-022, TB-DR-04 P7).

``matching.verdict`` holds the structured verdict rules once. Both engines that still carry their own copy must give
the table's answer for every row: the v1 path (``evaluate.eligibility``, ``structured_verdict``) and the cascade's S1
(``_s1_coded`` and ``_s1_outcome``, with the CAS-11, F-10 and D-135 overrides), and the full cascade S1 run over every
TRUE/FALSE/NULL combination of four criteria. A rule changed in one place and not the other fails here.
"""

from __future__ import annotations

import itertools
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from matching import verdict as vt
from matching.carried import Carried
from matching.cascade.engine import _Run, is_value_criterion
from orchestrator.scenarios import evaluate
from tb_contracts import CriterionIR, PatientEvaluation

from tests.unit.test_safety_properties import COND, S1_CRITERIA, S1_IDS, S1_RS, VALUE, _cascade, _combos, _FakeLake

INDEX = date(2026, 10, 5)
TRI: tuple[bool | None, ...] = (True, False, None)
KINDS = ("inclusion", "exclusion", "renewal", "documentation")


CODE = {"inclusion": "INC", "exclusion": "EXC", "renewal": "REN", "documentation": "DOC"}


def _ir(kind: str, logic: dict[str, Any]) -> CriterionIR:
    cid = f"VT-{CODE[kind]}-01"
    return CriterionIR.model_validate(
        {"id": cid, "ruleset": "VT", "kind": kind, "class": "structured", "text": cid, "logic": logic}
    )


# ------------------------------------------------------------------------------------------------ the table itself


def test_the_table_is_complete_and_unknown_never_excludes() -> None:
    assert set(vt.TABLE) == {(k, p) for k in ("inclusion", "exclusion") for p in TRI}
    for (k, p), v in vt.TABLE.items():
        assert v.hard is (v.outcome == "fail")
        if p is None:
            assert v == vt.UNKNOWN, k
    assert vt.excludes("inclusion", False) and vt.excludes("exclusion", True)
    assert not any(vt.excludes(k, None) for k in KINDS)


def test_overrides_only_ever_soften_an_answer() -> None:
    """No override turns a kept patient into an excluded one, and each one that applies gives unknown."""
    for kind, p, gap, prop, absent in itertools.product(KINDS, TRI, (False, True), (False, True), (False, True)):
        v = vt.structured(kind, p, code_gap=gap, proposed=prop, absent_is_unknown=absent)
        base = vt.structured(kind, p)
        assert not (v.hard and not base.hard), (kind, p, gap, prop, absent)
        if prop:
            assert v == vt.UNKNOWN
        if (gap or absent) and vt.kind_class(kind) == "inclusion" and p is False:
            assert v == vt.UNKNOWN
        if not (gap or absent or prop):
            assert v == base


def test_a_non_boolean_answer_is_refused() -> None:
    with pytest.raises(TypeError):
        vt.structured("inclusion", 1)  # type: ignore[arg-type]


def test_direction_changes() -> None:
    tolerated = {("inclusion", True, None), ("inclusion", None, True)}
    for kind, a, b in itertools.product(KINDS, TRI, TRI):
        want = a != b and (vt.kind_class(kind), a, b) not in tolerated
        assert vt.direction_changes(kind, a, b) is want, (kind, a, b)
        assert vt.direction_changes(kind, a, b) is vt.direction_changes(kind, b, a)


# ------------------------------------------------------------------------------------------------ the v1 path


@pytest.mark.parametrize(("kind", "p"), list(itertools.product(KINDS, TRI)))
def test_v1_path_parity(kind: str, p: bool | None) -> None:
    assert evaluate.eligibility(kind, p) == vt.eligibility(kind, p) == vt.structured(kind, p).outcome
    c = _ir(kind, COND)
    ev = PatientEvaluation(pid="A", index_date=INDEX, engine="sql", results={c.id: p})
    assert evaluate.structured_verdict(c, ev).verdict == vt.structured(kind, p).outcome
    assert evaluate.structured_verdict(c, None).verdict == vt.structured(kind, None).outcome


# ------------------------------------------------------------------------------------------------ the cascade S1


def _run(semantics: str, gap: list[str], facts: list[str]) -> Any:
    ns = SimpleNamespace(
        semantics=semantics,
        cfg=SimpleNamespace(snapshot=None),
        coverage=SimpleNamespace(refs=lambda c, pid, idx: list(gap)),
        proposed=SimpleNamespace(refs=lambda c, pid, idx, v: list(facts), reason=lambda pid, fids: "proposed_fact"),
        carried=Carried(),  # every system carried (not read): D-795's check has its own test
        rs=SimpleNamespace(valuesets={}),
        _uncarried_index=set(),
    )
    ns._s1_coded = lambda c, row: _Run._s1_coded(ns, c, row)  # type: ignore[arg-type]
    return ns


CASCADE_CASES = list(
    itertools.product(
        ("inclusion", "exclusion"), TRI, ("v1", "affirmative"), (COND, VALUE), (False, True), (False, True)
    )
)


@pytest.mark.parametrize(("kind", "p", "semantics", "logic", "gap", "proposed"), CASCADE_CASES)
def test_cascade_s1_parity(
    kind: str, p: bool | None, semantics: str, logic: dict[str, Any], gap: bool, proposed: bool
) -> None:
    c = _ir(kind, logic)
    ns = _run(semantics, ["Condition/g|2026-01-01"] if gap else [], ["Fact/f|2026-01-01"] if proposed else [])
    row = {"pid": "A", "index_date": INDEX, f"C_{c.id}": p}
    o = _Run._s1_outcome(ns, c, row)
    want = vt.structured(
        kind, p, code_gap=gap, proposed=proposed, absent_is_unknown=semantics != "v1" and not is_value_criterion(c)
    )
    assert o.hard is want.hard, (o, want)
    if want.outcome == "unknown":  # the cascade shows a kept unknown exclusion as pass with an unknown kind
        assert o.status == ("pass" if kind == "exclusion" else "unknown") and o.unknown_kind == "data_gap", o
    else:
        assert o.status == want.outcome and o.unknown_kind is None, o


@pytest.mark.parametrize("semantics", ["v1", "affirmative"])
def test_cascade_s1_run_parity(semantics: str) -> None:
    """The whole S1 stage over all 81 combinations: each criterion's ``hard`` is the table's, and the patient exits
    at S1 exactly when the table excludes on some criterion."""
    combos = _combos(S1_IDS)
    res = _cascade(_FakeLake(S1_RS, combos), semantics=semantics)
    by_id = {c.id: c for c in S1_CRITERIA}
    for pid, vals in combos.items():
        t = res.traces[pid]
        hard = {}
        for cid, v in vals.items():
            c = by_id[cid]
            hard[cid] = vt.structured(c.kind, v, absent_is_unknown=semantics != "v1" and not is_value_criterion(c)).hard
            assert t.outcomes[cid].hard is hard[cid], (pid, cid, t.outcomes[cid])
        assert (t.exit_stage == "S1") is any(hard.values()), (pid, t.exit_stage)
