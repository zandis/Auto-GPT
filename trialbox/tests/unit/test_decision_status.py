"""One function where a verdict becomes a status (T-709, D-478): ``matching.decision``.

The paths against each other are ``tests/property/`` (T-705, T-706). Here: the rule itself as a table, the four
rules on which the three old functions differed (review M1 a to d), and that every path calls the one function.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from matching import decision
from matching import verdict as verdict_table
from matching.cascade.model import Outcome, PatientTrace
from matching.decision import Policy, answer_of, status_of
from orchestrator.scenarios import evaluate, nav
from orchestrator.scenarios.evaluate import NoteResult, PatientVerdicts, is_pair, note_verdict, tier
from orchestrator.scenarios.screen_cascade import verdict_of, verdicts_of
from tb_contracts import CriterionVerdict, Evidence

from tests.judge_kit import note_criterion, ruleset

INC = note_criterion("T-INC-02", "inclusion", "Gout flare", "Is a gout flare noted?")
EXC = note_criterion("T-EXC-02", "exclusion", "Skin abscess", "Is a skin abscess noted?")
RS = ruleset([INC, EXC])  # T-INC-01 (age, structured) + the two note criteria
BY = RS.by_id()
AGE = next(c for c in RS.active() if c.class_ == "structured")
T = 0.75
PAIR = Policy(T, True)  # two models that may exclude
HELD = Policy(T, False)  # a run on which notes may not exclude


def _v(c: Any, verdict: str, *, conf: float | None = None, basis: Any = None, final: bool | None = None,
       reason: str | None = None) -> CriterionVerdict:  # fmt: skip
    return CriterionVerdict(id=c.id, verdict=verdict, basis=basis, final=final,  # type: ignore[arg-type]
                            evidence=Evidence(resource_refs=[], confidence=conf, reason=reason))  # fmt: skip


# ------------------------------------------------------------------------------------------------ one answer
@pytest.mark.parametrize(
    ("verdict", "policy", "want"),
    [
        # the records: decided as they stand, whatever the notes policy
        (_v(AGE, "pass", basis="coded"), HELD, "yes"),
        (_v(AGE, "fail", basis="coded"), HELD, "no"),
        (_v(AGE, "unknown"), PAIR, "unknown"),
        # a note "not met": no only when a pair gave it, it is final, sure enough and the run may exclude
        (_v(EXC, "fail", conf=0.95, basis="pair"), PAIR, "no"),
        (_v(EXC, "fail", conf=0.95, basis="pair"), HELD, "unknown"),
        (_v(EXC, "fail", conf=0.95, basis="single"), PAIR, "unknown"),  # one model (H2)
        (_v(EXC, "fail", conf=0.95, basis="pair", final=False), PAIR, "unknown"),  # stored as not final (H1)
        (_v(EXC, "fail", conf=0.60, basis="pair"), PAIR, "unknown"),  # below the threshold
        (_v(EXC, "fail", conf=0.95), PAIR, "no"),  # a row stored before the field: by the rest of the rule
        (_v(EXC, "fail", conf=0.95, final=False), PAIR, "unknown"),
        # a note "met": yes only when sure enough and nothing was left out of what the models read
        (_v(INC, "pass", conf=0.95, basis="pair"), PAIR, "yes"),
        (_v(INC, "pass", conf=0.95, basis="single"), HELD, "yes"),  # one model may keep a patient
        (_v(INC, "pass", conf=0.60, basis="pair"), PAIR, "unknown"),  # M1a
        (_v(INC, "pass", conf=0.95, basis="pair", reason="notes_over_budget"), PAIR, "unknown"),  # M1d
        # nobody answered, or a person decides
        (_v(INC, "unknown", reason="disagree"), PAIR, "unknown"),
        (_v(INC, "pending_human", basis="person"), PAIR, "unknown"),
        # a person's decision on a note criterion (the cascade's S5) stands as a coded answer does
        (_v(EXC, "fail", basis="person"), HELD, "no"),
        (_v(INC, "pass", basis="person"), HELD, "yes"),
    ],
)
def test_what_one_verdict_says(verdict: CriterionVerdict, policy: Policy, want: str) -> None:
    assert answer_of(BY[verdict.id], verdict, policy) == want


def test_the_structured_answer_is_the_table_of_t652() -> None:
    """``evaluate.eligibility`` is no second copy: it is ``matching.verdict``'s table."""
    for kind in ("inclusion", "exclusion", "renewal", "documentation"):
        for pred in (True, False, None):
            assert evaluate.eligibility(kind, pred) == verdict_table.eligibility(kind, pred)
    assert evaluate.eligibility("exclusion", True) == "fail" and evaluate.eligibility("exclusion", None) == "unknown"


# ------------------------------------------------------------------------------------------------ a status
def _three(inc: CriterionVerdict, exc: CriterionVerdict) -> list[CriterionVerdict]:
    return [_v(AGE, "pass", basis="coded"), inc, exc]


MET = _v(INC, "pass", conf=0.95, basis="pair")
ABSENT = _v(EXC, "pass", conf=0.95, basis="pair")


def test_a_status_is_excluded_on_a_no_review_on_an_unknown_else_high() -> None:
    assert status_of(BY, _three(MET, ABSENT), PAIR) == decision.Status("high", [], 0, [])
    out = status_of(BY, _three(MET, _v(EXC, "fail", conf=0.95, basis="pair")), PAIR)
    assert (out.tier, out.excluded_by) == ("excluded", ["T-EXC-02"])
    open_q = status_of(BY, _three(_v(INC, "unknown", reason="disagree"), ABSENT), PAIR)
    assert (open_q.tier, open_q.n_unknown) == ("review", 1)
    coded = status_of(BY, [_v(AGE, "fail", basis="coded"), MET, ABSENT], HELD)
    assert (coded.tier, coded.excluded_by) == ("excluded", [AGE.id])  # the records exclude without any model


@pytest.mark.parametrize(
    ("name", "inc", "exc"),
    [
        ("M1a a met below the threshold", _v(INC, "pass", conf=0.6, basis="pair"), ABSENT),
        ("M1c a soft fail", MET, _v(EXC, "fail", conf=0.95, basis="single", final=False)),
        ("M1d notes left out", _v(INC, "pass", conf=0.95, basis="pair", reason="notes_over_budget"), ABSENT),
        ("H2 one model's not met", MET, _v(EXC, "fail", conf=0.95, basis="single")),
    ],
)
def test_the_rules_the_old_functions_differed_on_are_review_on_every_path(
    name: str, inc: CriterionVerdict, exc: CriterionVerdict
) -> None:
    """One rule: the v1 tier, the cascade's rows and NAV's sheet all read these as a person's check."""
    vs = _three(inc, exc)
    assert status_of(BY, vs, PAIR).tier == "review", name
    assert tier(RS, vs, T, note_block=True)[0] == "review", name  # v1 and MICROBATCH
    answers = {v.id: answer_of(BY[v.id], v, PAIR) for v in vs}
    assert "no" not in answers.values() and "unknown" in answers.values(), name  # NAV: a row to confirm


def test_the_v1_tier_is_the_status_function() -> None:
    for vs in (_three(MET, ABSENT), _three(MET, _v(EXC, "fail", conf=0.95, basis="pair")),
               _three(_v(INC, "unknown"), ABSENT), _three(_v(INC, "pass", conf=0.5, basis="pair"), ABSENT)):  # fmt: skip
        for policy in (PAIR, HELD):
            st = status_of(BY, vs, policy)
            assert tier(RS, vs, policy.threshold, note_block=policy.note_block) == (st.tier, st.actions, st.n_unknown)


# ------------------------------------------------------------------------------------------------ the basis
def test_a_fresh_note_answer_carries_the_basis_of_the_run() -> None:
    said_no = NoteResult(predicate="pass", confidence=0.95, quote="q", quote_date="2026-10-01", dids=["D1"])
    assert note_verdict(EXC, said_no, pair=True).basis == "pair"
    assert note_verdict(EXC, said_no).basis == "single"  # a caller that does not say: one model
    assert note_verdict(EXC, NoteResult(predicate="unknown", confidence=0.0, reason="disagree")).basis is None
    assert evaluate.human_verdict(INC).basis == "person"
    model_a = SimpleNamespace(model="judge-a", base_url="http://a/v1", gateway=None, served_root="judge-a")
    model_b = SimpleNamespace(model="verifier-b", base_url="http://b/v1", gateway=None, served_root="verifier-b")
    again = SimpleNamespace(model="judge-a", base_url="http://c/v1", gateway=None, served_root="judge-a")
    judge: Any = SimpleNamespace
    assert is_pair(judge(llm=model_a, verifier=model_b))
    assert not is_pair(judge(llm=model_a, verifier=None)) and not is_pair(judge(llm=model_a, verifier=again))
    assert not is_pair(None)


def test_a_cascade_outcome_carries_its_basis() -> None:
    ev: list[dict[str, Any]] = [{"did": "D1", "quote": "q", "date": "2026-10-01"}, {"call_id": "c", "confidence": 0.9}]
    assert verdict_of(Outcome(AGE.id, "pass", "S1")).basis == "coded"
    assert verdict_of(Outcome(EXC.id, "fail", "S3", hard=True, evidence=ev)).basis == "pair"  # hard: a pair's (CAS-7)
    soft = verdict_of(Outcome(EXC.id, "fail", "S3", hard=False, evidence=ev))
    assert (soft.basis, soft.final) == ("single", False)
    assert verdict_of(Outcome(INC.id, "pass", "S3", evidence=ev), pair=True).basis == "pair"
    assert verdict_of(Outcome(INC.id, "pass", "S5", reason="S5 reviewer")).basis == "person"
    assert verdict_of(Outcome(INC.id, "unknown", "S3", unknown_kind="uncertain")).basis is None


def test_the_cascades_published_tier_is_the_status_function() -> None:
    """A "met" at confidence 0.6 was ``high`` on the cascade and ``review`` on v1 (M1a): now review on both."""
    low: list[dict[str, Any]] = [{"did": "D1", "quote": "q", "date": "2026-10-01"}, {"call_id": "c", "confidence": 0.6}]
    sure: list[dict[str, Any]] = [
        {"did": "D1", "quote": "q", "date": "2026-10-01"},
        {"call_id": "c", "confidence": 0.95},
    ]

    def trace(inc_ev: list[dict[str, Any]]) -> PatientTrace:
        t = PatientTrace(pid="P1", index_date=date(2026, 10, 5))
        t.outcomes = {AGE.id: Outcome(AGE.id, "pass", "S1"), INC.id: Outcome(INC.id, "pass", "S3", evidence=inc_ev),
                      EXC.id: Outcome(EXC.id, "pass", "S3", evidence=sure)}  # fmt: skip
        t.tier = "strong"  # the cascade's own label before T-709
        return t

    assert verdicts_of(RS, trace(sure), policy=PAIR, pair=True).tier == "high"
    weak = verdicts_of(RS, trace(low), policy=PAIR, pair=True)
    assert weak.tier == "review" and [v.verdict for v in weak.verdicts] == ["pass", "pass", "pass"]


# ------------------------------------------------------------------------------------------------ NAV
def test_nav_lists_a_patient_one_model_called_excluded_with_a_row_to_confirm() -> None:
    """H2: every inclusion met and one exclusion "present" by a single model was on no sheet. Now: listed, and the
    exclusion is a row to confirm. A pair's answer still keeps the patient off."""
    run, soon = date(2026, 10, 5), 42
    one = PatientVerdicts("P1", _three(MET, _v(EXC, "fail", conf=0.95, basis="single", final=False)), "review", [], 0)
    name, missing = nav.classify(RS, one, None, None, run, soon, 90, T, False)
    assert name == "likely_eligible" and [m.criterion_id for m in missing] == ["T-EXC-02"]
    pair = PatientVerdicts("P1", _three(MET, _v(EXC, "fail", conf=0.95, basis="pair")), "excluded", [], 0)
    assert nav.classify(RS, pair, None, None, run, soon, 90, T, True) == (None, [])
    cut = PatientVerdicts("P1", _three(_v(INC, "pass", conf=0.95, basis="pair", reason="notes_over_budget"), ABSENT),
                          "review", [], 0)  # fmt: skip
    name, missing = nav.classify(RS, cut, None, None, run, soon, 90, T, True)
    assert name is None and [m.criterion_id for m in missing] == ["T-INC-02"]  # M1d: not "yes" on a cut record
