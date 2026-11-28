"""One model's note "not met" never takes a patient off a list (D-478, review 2026-11-22 R22-10).

``matching.decision.answer_of`` has two guards against a single-model note fail: its own ``basis`` check and
``tb_common.verdict_word.held_back`` (``single_model``). Either alone keeps the patient on the list, so a test that
leaves both in place cannot tell when one is lost (the review's mutation M3 survived). Here each guard is checked
by itself: once through the real rule, once with ``held_back`` taken out so that only the ``basis`` check stands.
A ``pair`` answer under the same input does exclude, so the checks are not vacuous.

R22-17 (D-1069; ruled on #639 7088402135): a note inclusion's "not met" goes to review whatever its basis, so for the
inclusion the basis check shows in what the answer may print, not in the status: whether the "not met" stands
(``decision.fail_stands``, what a CASE sheet prints as "not met" rather than "to check"). The control for the
inclusion is review; the exclusion's control still excludes.
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


#: L1 (#639 7107834329, D-1069: what is not shown never excludes): the note answer rests on a quote that states the
#: exclusion's condition; with no quote a note exclusion's "present" is review whatever its basis (pinned below)
ABSCESS = "Skin abscess on the left forearm, drained today."


#: round 5 (#639 7115208555, 7115258794): and both models affirmed it (judge v6); a row that does not say is pinned
def _fail(c: Any, basis: str, quote: str | None = ABSCESS, affirmed: bool | None = True) -> CriterionVerdict:
    return CriterionVerdict(id=c.id, verdict="fail", basis=basis, affirmed=affirmed,  # type: ignore[arg-type]
                            evidence=Evidence(resource_refs=[], confidence=SURE, quote=quote))  # fmt: skip


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
    assert not decision.fail_stands(_fail(criterion, "single"), MAY_EXCLUDE)  # what the basis check alone decides


@pytest.mark.parametrize("criterion", [INC, EXC], ids=["inclusion", "exclusion"])
def test_control_a_pair_fail_under_the_same_input_stands_for_review(
    criterion: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pair's "not met" stands (fail_stands); on the inclusion it is review (R22-17), and on the exclusion too
    since ring 0 (D-1072; before it, it excluded)."""
    want = "unknown"
    tier: tuple[str, list[str]] = ("review", [])
    assert answer_of(criterion, _fail(criterion, "pair"), MAY_EXCLUDE) == want
    _without_held_back(monkeypatch)
    assert answer_of(criterion, _fail(criterion, "pair"), MAY_EXCLUDE) == want
    status = status_of(BY, [_fail(criterion, "pair")], MAY_EXCLUDE)
    assert (status.tier, status.excluded_by) == tier
    assert decision.fail_stands(_fail(criterion, "pair"), MAY_EXCLUDE)


def test_a_pair_fail_on_a_note_exclusion_both_models_did_not_affirm_is_review() -> None:
    """Round 5, the control's exclusion case with a row that does not say both models affirmed it: review."""
    assert answer_of(EXC, _fail(EXC, "pair", affirmed=None), MAY_EXCLUDE) == "unknown"
    status = status_of(BY, [_fail(EXC, "pair", affirmed=None)], MAY_EXCLUDE)
    assert (status.tier, status.excluded_by) == ("review", [])


def test_a_pair_fail_on_a_note_exclusion_with_no_quote_is_review() -> None:
    """L1, the old input of the control's exclusion case: nothing shown, nothing excluded."""
    assert answer_of(EXC, _fail(EXC, "pair", None), MAY_EXCLUDE) == "unknown"
    status = status_of(BY, [_fail(EXC, "pair", None)], MAY_EXCLUDE)
    assert (status.tier, status.excluded_by) == ("review", [])
