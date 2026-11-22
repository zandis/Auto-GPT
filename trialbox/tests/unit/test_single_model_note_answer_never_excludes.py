"""One model's note "not met" never takes a patient off a list (D-478, review 2026-11-22 R22-10).

``matching.decision.answer_of`` has two guards against a single-model note fail: its own ``basis`` check and
``tb_common.verdict_word.held_back`` (``single_model``). Either alone keeps the patient on the list, so a test that
leaves both in place cannot tell when one is lost (the review's mutation M3 survived). Here each guard is checked
by itself: once through the real rule, once with ``held_back`` taken out so that only the ``basis`` check stands.
A ``pair`` answer under the same input does exclude, so the checks are not vacuous.
"""

from __future__ import annotations

from typing import Any

import pytest
from matching import decision
from matching.decision import Policy, answer_of, status_of
from tb_contracts import CriterionVerdict, Evidence

from tests.judge_kit import note_criterion, ruleset

INC = note_criterion("T-INC-02", "inclusion", "Gout flare", "Is a gout flare noted?")
EXC = note_criterion("T-EXC-02", "exclusion", "Skin abscess", "Is a skin abscess noted?")
BY = ruleset([INC, EXC]).by_id()
MAY_EXCLUDE = Policy(0.75, True)  # notes may exclude on this run
SURE = 0.95  # well above the threshold


def _fail(c: Any, basis: str) -> CriterionVerdict:
    return CriterionVerdict(id=c.id, verdict="fail", basis=basis,  # type: ignore[arg-type]
                            evidence=Evidence(resource_refs=[], confidence=SURE))  # fmt: skip


def _without_held_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave the ``basis`` check of ``answer_of`` as the only guard."""
    monkeypatch.setattr(decision, "held_back", lambda _verdict: None)


@pytest.mark.parametrize("criterion", [INC, EXC], ids=["inclusion", "exclusion"])
def test_a_single_model_fail_is_unknown_not_an_exclusion(criterion: Any) -> None:
    assert answer_of(criterion, _fail(criterion, "single"), MAY_EXCLUDE) == "unknown"


@pytest.mark.parametrize("criterion", [INC, EXC], ids=["inclusion", "exclusion"])
def test_the_basis_check_alone_keeps_a_single_model_fail_from_excluding(
    criterion: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _without_held_back(monkeypatch)
    assert answer_of(criterion, _fail(criterion, "single"), MAY_EXCLUDE) == "unknown"
    status = status_of(BY, [_fail(criterion, "single")], MAY_EXCLUDE)
    assert (status.tier, status.excluded_by) == ("review", [])


@pytest.mark.parametrize("criterion", [INC, EXC], ids=["inclusion", "exclusion"])
def test_control_a_pair_fail_under_the_same_input_excludes(criterion: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    assert answer_of(criterion, _fail(criterion, "pair"), MAY_EXCLUDE) == "no"
    _without_held_back(monkeypatch)
    assert answer_of(criterion, _fail(criterion, "pair"), MAY_EXCLUDE) == "no"
    status = status_of(BY, [_fail(criterion, "pair")], MAY_EXCLUDE)
    assert (status.tier, status.excluded_by) == ("excluded", [criterion.id])
