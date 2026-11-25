"""Ring 0: a note answer never takes a patient off the list, on any path (INT-S-A, D-1072).

The owner's ruling: the model sorts, it does not adjudicate. No answer read from the notes takes a patient off the
investigator's list, also when both models agree on a quote that states the condition; only the coded records (and a
person) exclude. A note "not eligible" is review, and its row keeps the verdict, the quote with its note and the
reason code ``notes_suggest_not_eligible``.

The property, over enumerated inputs (no ``hypothesis``, as ``tests/unit/test_safety_properties.py``): for any
combination of note answers (verdict, confidence, quote stated or inferred or none, affirmed or not, one model or a
pair, final or not, notes allowed to exclude or not), a patient whose coded answers do not exclude is never
``excluded``, so is on the list (``screen.candidate_list`` lists ``high`` and ``review``). A coded "not met" still
excludes in the same tables, so no check passes by never excluding. The paths:

* the one rule, :func:`matching.note_answer.note_answer_may`;
* the cascade (SCREEN, and MICROBATCH's screen of new patients): ``run_cascade`` with a stub judge, then
  ``screen_cascade.verdicts_of``; every note criterion is judged (no CAS-3 stop on a note answer);
* the v1 evaluator (SCREEN on v1, MICROBATCH on v1, CASE): ``note_verdict``, ``not_final``, ``tier``;
* NAV: ``nav.classify``;
* a stored row re-tiered (MICROBATCH's re-check of the pool, a re-run): ``decision.status_of`` on any stored row.
"""

from __future__ import annotations

import itertools
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from matching import decision
from matching.cascade import engine as cascade_engine
from matching.cascade.judge import AgreementJudge, JudgeReply, verify_span
from matching.note_answer import NoteEffect, note_answer_may
from orchestrator.scenarios import nav
from orchestrator.scenarios.evaluate import (
    NoteJudge,
    NoteResult,
    PatientVerdicts,
    evaluate_patients,
    not_final,
    note_block_policy,
    note_block_why,
    note_verdict,
    tier,
)
from orchestrator.scenarios.screen import judging_sentence, models_used
from orchestrator.scenarios.screen_cascade import OrchestratorJudge, verdict_of, verdicts_of
from tb_common.config import DECLARED
from tb_common.reasons import Reason, code_of
from tb_contracts import CriterionVerdict, Evidence

from tests.judge_kit import ScriptedModel, says
from tests.unit.test_safety_properties import (
    CASCADE_RS,
    COND,
    LEXICON,
    _cascade,
    _ir,
    _Judge,
    _lake,
    _note,
    _ruleset,
    _run_for_map,
)

POLICIES = [decision.Policy(t, b) for t in (0.5, 0.75, 0.95) for b in (True, False)]
STATED = "Active infection of the left toe."  # states the exclusion's condition
INFERRED = "No active infection."  # negated: the models' inference
QUOTES = (STATED, INFERRED, None)
RING0 = "notes_suggest_not_eligible"  # the reason code a note "not eligible" carries (``tb_common.reasons.Reason``)
CRITERIA = [
    _ir("R-INC-00", "inclusion", "structured", COND),
    _ir("R-INC-01", "inclusion", "note", COND, text="Gout flare documented", note_question="Flare?"),
    _ir("R-EXC-01", "exclusion", "note", COND, text="Active infection", note_question="Infection?"),
    _ir("R-INC-02", "inclusion", "mixed", COND, text="Gout flare documented", note_question="Flare?"),
    _ir("R-EXC-02", "exclusion", "mixed", COND, text="Active infection", note_question="Infection?"),
]
RS = _ruleset(CRITERIA)


class _NoStructured:
    name = "sql"

    def evaluate(self, *a: Any, **kw: Any) -> dict[str, Any]:
        return {}


def _nj(cls: Any = NoteJudge) -> Any:
    llm, verifier = (ScriptedModel(n, says("pass", STATED)) for n in ("a", "b"))
    return cls(lake=None, llm=llm, verifier=verifier)


class _Fixed:
    """A cascade ``JudgeClient`` that always gives one answer on one quote."""

    def __init__(self, verdict: str, quote: str) -> None:
        self.verdict, self.quote = verdict, quote

    def judge(self, **kw: Any) -> JudgeReply:
        return JudgeReply(self.verdict, 0.95, self.quote, "2026-10-01", "scripted", call_id=self.quote, affirmed=True)


CODED, NOTES = CRITERIA[0], CRITERIA[1:]


def _coded(verdict: Any) -> CriterionVerdict:
    return CriterionVerdict(id=CODED.id, verdict=verdict, evidence=Evidence(resource_refs=[]), basis="coded")


def test_the_one_rule_never_excludes() -> None:
    n = 0
    for kind, present, quote, affirmed in itertools.product(
        ("inclusion", "exclusion", "renewal", "documentation"), (True, False), QUOTES, (True, False, None)
    ):
        may = note_answer_may(kind, present, quote, "Active infection", affirmed=affirmed)
        assert may.effect != "excludes", (kind, present, quote, affirmed)
        n += 1
    may = note_answer_may("exclusion", True, STATED, "Active infection", affirmed=True)
    assert (may.effect, code_of(may.reason), may.reading_stands) == ("review", RING0, True)
    assert RING0 in {r.value for r in Reason}
    assert n == 4 * 2 * 3 * 3


ANSWERS = (("pass", 0.95), ("fail", 0.95), ("fail", 0.5), ("pass", 0.5), ("unknown", 0.0))


def test_the_cascade_never_excludes_on_a_note_answer_and_judges_every_criterion() -> None:
    """SCREEN on the cascade (and MICROBATCH's new patients): the pair's answers on both note criteria, every
    combination, notes allowed to exclude or not, one model or a pair. The note quotes the exclusion's condition, so
    the "present" answer is the one that excluded before ring 0."""
    texts = ("Gout flare documented", "Active infection")
    n = 0
    for s1, inc, exc, block, pair in itertools.product(
        (True, None, False), ANSWERS, ANSWERS, (True, False), (True, False)
    ):
        answers = {(role, t): a for role in ("judge", "second_opinion") for t, a in zip(texts, (inc, exc), strict=True)}
        judge = _Judge(answers)
        lake = _lake(CASCADE_RS, ["P-1"], [_note("P-1", "Active infection and a gout flare noted.")], s1)
        res = _cascade(lake, lexicon=LEXICON, judge=judge, sample_per_stratum=None, note_block=block)
        t = res.traces["P-1"]
        pv = verdicts_of(CASCADE_RS, t, policy=decision.Policy(0.75, block), pair=pair)
        coded_out = s1 is False  # the control: the coded inclusion "not met" excludes
        assert (pv.tier == "excluded") is coded_out, (s1, inc, exc, block, pair, pv.tier)
        assert (t.tier == "excluded") is coded_out, (s1, inc, exc, block, pair, t.tier)
        if not coded_out:
            # no CAS-3 stop on a note answer: the investigator sees every criterion judged
            assert {c for r, c in judge.calls if r == "judge"} == set(texts), (inc, exc, judge.calls)
            assert not any(o.hard for o in t.outcomes.values())
        n += 1
    assert n == 3 * 5 * 5 * 2 * 2


def test_the_cascade_row_keeps_what_the_page_needs() -> None:
    """The answer that excluded before ring 0 (a pair, a stated quote both models affirmed, sure, notes allowed to
    exclude) is review; its row keeps the verdict, the quote with its note and the reason code."""
    judge = _Judge({("judge", "Active infection"): ("pass", 0.95)})
    rs = _ruleset([CASCADE_RS.criteria[0], CASCADE_RS.criteria[2]])
    res = _cascade(_lake(rs, ["P-1"], [_note("P-1", STATED, did="doc-9")]), lexicon=LEXICON, judge=judge,
                   sample_per_stratum=None, note_block=True)  # fmt: skip
    pv = verdicts_of(rs, res.traces["P-1"], policy=decision.Policy(0.75, True), pair=True)
    row = next(v for v in pv.verdicts if v.id == "N-EXC-01")
    assert pv.tier == "review"
    assert row.verdict == "fail" and row.evidence is not None
    assert row.evidence.quote == STATED and row.evidence.resource_refs == ["DocumentReference/doc-9"]
    assert row.evidence.reason == RING0


def test_the_v1_path_never_excludes_on_a_note_answer() -> None:
    """SCREEN, MICROBATCH and CASE on the v1 evaluator: ``note_verdict``, ``not_final`` and ``tier``, for every note
    and mixed criterion, every answer, quote, affirmation, basis and policy; NAV's ``classify`` over the same rows."""
    n = 0
    for c, (pred, conf), quote, affirmed, pair, policy, coded in itertools.product(
        NOTES, ANSWERS, QUOTES, (True, False), (True, False, None), POLICIES, ("pass", "unknown", "fail")
    ):
        r = NoteResult(pred, conf, quote if pred != "unknown" else None, "2026-10-01", Reason.NOTE.value,
                       dids=["d1"], sentence=quote or "", affirmed=affirmed)  # fmt: skip
        v = not_final(c, note_verdict(c, r, pair), policy.note_block)
        rows = [_coded(coded), v]
        t, _, _ = tier(RS, rows, policy.threshold, note_block=policy.note_block)
        assert (t == "excluded") is (coded == "fail"), (c.id, pred, conf, quote, affirmed, pair, policy, coded, t)
        assert decision.answer_of(c, v, policy) != "no"
        if c.kind == "exclusion" and coded == "pass":  # NAV: a note exclusion never drops the patient
            name, _ = nav.classify(RS, PatientVerdicts("P-1", rows, t, [], 0), None, None, date(2026, 10, 5),
                                   30, 90, policy.threshold, policy.note_block)  # fmt: skip
            assert name == "likely_eligible", (c.id, pred, conf, quote, affirmed, pair, policy)
        n += 1
    assert n == 4 * 5 * 3 * 2 * 3 * 6 * 3


def test_the_v1_row_keeps_what_the_page_needs() -> None:
    c = CRITERIA[2]
    r = NoteResult("pass", 0.95, STATED, "2026-10-01", Reason.NOTE.value, dids=["d1"], sentence=STATED, affirmed=True)
    v = not_final(c, note_verdict(c, r, True), True)
    assert v.verdict == "fail" and v.evidence is not None and v.evidence.quote == STATED
    assert v.evidence.resource_refs == ["DocumentReference/d1"]
    assert v.evidence.reason == RING0
    assert decision.status_of(RS.by_id(), [_coded("pass"), v], decision.Policy(0.75, True)).tier == "review"


@pytest.mark.parametrize("path", ["v1", "screen_judge", "agreement_judge"])
@pytest.mark.parametrize("kind", ["exclusion", "inclusion"])
def test_the_row_keeps_both_quotes_and_both_notes(path: str, kind: str) -> None:
    """A pair's "not eligible" (an exclusion present, an inclusion not met) keeps each model's quote and its note, the
    judge's first, on every judge; an answer that keeps the patient carries no opinions, as before."""
    against, eligible = ("pass", "fail") if kind == "exclusion" else ("fail", "pass")
    second = "Active infection of the right knee."
    excerpts = [{"did": f"d{n}", "date": "2026-10-01", "text": t, "note_type": "progress"}
                for n, t in enumerate((STATED, second), 1)]  # fmt: skip
    c = CRITERIA[2] if kind == "exclusion" else CRITERIA[1]
    asked: dict[str, Any] = {"criterion_text": c.text, "note_question": "Q?", "index_date": date(2026, 10, 5)}
    cascade: dict[str, Any] = {
        "role": "judge",
        "study_id": "R",
        "data_class": "D3",
        "step_id": "t",
        "purpose": "screening",
    }

    def row(answer: str) -> CriterionVerdict:
        llm: Any = ScriptedModel("judge-a", says(answer, STATED, quote_date="2026-10-01"))
        verifier: Any = ScriptedModel("verifier-b", says(answer, second, quote_date="2026-10-01"))
        lake: Any = None
        if path == "v1":
            r = NoteJudge(lake=lake, llm=llm, verifier=verifier).judge_excerpts(excerpts=excerpts, **asked)
            return note_verdict(c, r, True)
        if path == "screen_judge":
            reply = OrchestratorJudge(lake, llm, verifier=verifier).judge(excerpts=excerpts, **asked, **cascade)
        else:
            pair = AgreementJudge(_Fixed(answer, STATED), _Fixed(answer, second))
            reply = pair.judge(excerpts=excerpts, **asked, **cascade)
        span = verify_span(reply, excerpts, date(2026, 1, 1), date(2026, 12, 31))
        return verdict_of(_run_for_map(True)._map(c, reply, span, "S3"), pair=True)

    v = row(against)
    assert v.verdict == "fail" and v.evidence is not None
    assert [(o.role, o.quote) for o in v.evidence.opinions or []] == [("judge", STATED), ("verifier", second)]
    assert v.evidence.quote == STATED
    assert v.evidence.resource_refs == ["DocumentReference/d1", "DocumentReference/d2"]
    kept = row(eligible)
    assert kept.verdict == "pass" and kept.evidence is not None and kept.evidence.opinions is None


@pytest.mark.parametrize("kind", [None, "", "cohort"])
def test_a_criterion_with_no_kind_or_an_unknown_one_is_review_on_the_whole_path(
    kind: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 1: a pair's stated, affirmed "present" through ``evaluate_patients`` (the judge, the row, ``not_final``,
    the status) on a criterion that does not say a known kind: never excluded, the answer reads unknown."""
    rs = _ruleset([CRITERIA[2].model_copy()])
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    for c in rs.criteria:
        c.kind = kind

    class _Pair(NoteJudge):
        def judge_patient(self, pid: str, c: Any, index_date: date, full: bool = False) -> NoteResult:
            return NoteResult("pass", 0.95, STATED, reason="note", dids=["d1"], sentence=STATED, affirmed=True)

    nj = _nj(_Pair)
    verdict: Any
    for verdict in ("pass", "fail"):
        row = CriterionVerdict(id="R-EXC-01", verdict=verdict, basis="pair", final=True, affirmed=True,
                               evidence=Evidence(resource_refs=[], quote=STATED, confidence=0.95))  # fmt: skip
        assert tier(rs, [row], 0.75, note_block=True)[0] != "excluded"
        assert decision.answer_of(rs.by_id()["R-EXC-01"], row, decision.Policy(0.75, True)) != "no"
    out = evaluate_patients(rs, ["P"], date(2026, 10, 5), _NoStructured(), nj, 0.75, only={"R-EXC-01"},
                            all_candidates=True, workers=1, note_block=True)  # fmt: skip
    assert out["P"].tier != "excluded"


def test_the_engine_never_makes_a_note_outcome_hard_whatever_the_rule_says(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 2: were the one rule to say ``excludes`` again, the engine still keeps the patient and judges on."""
    monkeypatch.setattr(cascade_engine, "note_answer_may", lambda *a, **kw: NoteEffect("excludes"))
    judge = _Judge({("judge", "Active infection"): ("pass", 0.95), ("judge", "Gout flare documented"): ("fail", 0.95)})
    lake = _lake(CASCADE_RS, ["P-1"], [_note("P-1", "Active infection and a gout flare noted.")])
    res = _cascade(lake, lexicon=LEXICON, judge=judge, sample_per_stratum=None, note_block=True)
    t = res.traces["P-1"]
    assert t.exit_stage is None and not any(o.hard for o in t.outcomes.values()) and len(judge.calls) == 2
    assert verdicts_of(CASCADE_RS, t, policy=decision.Policy(0.75, True), pair=True).tier == "review"


def test_the_words_of_a_run_never_promise_a_note_exclusion() -> None:
    """Ruling 3: the mail's and the PDF's sentence, in three languages, and the footer."""
    j = {"mode": "agreement", "judge_model": "j", "verifier_model": "v", "note_block": "never", "may_block": False,
         "note_block_code": "configured"}  # fmt: skip
    for info in (j, {**j, "may_block": True, "note_block": "both_agree"}):
        assert "stays on the list" in judging_sentence(info, "en") and "v" in judging_sentence(info, "en")
        assert "患者はリストに残" in judging_sentence(info, "ja") and "病人仍留在名單上" in judging_sentence(
            info, "zh-TW"
        )
        assert "notes never exclude" in models_used(info)


def test_the_default_policy_is_never_and_both_agree_does_not_exclude(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 4: unset is ``never``, in the code, the declared settings, the platform's site file and compose; set to
    ``both_agree``, a pair's stated exclusion is review all the same."""
    monkeypatch.delenv("TB_NOTE_BLOCK", raising=False)
    assert note_block_policy() == "never"
    root = Path(__file__).resolve().parents[2]
    assert DECLARED["TB_NOTE_BLOCK"].default == "never"
    assert "TB_NOTE_BLOCK=never\n" in (root / "deploy/platform/base/site.env").read_text("utf-8")
    assert "${TB_NOTE_BLOCK:-never}" in (root / "deploy/docker-compose.yml").read_text("utf-8")
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    monkeypatch.setenv("TB_CANARY_GATE", "off")
    nj = _nj()
    may = note_block_why(nj)[0]
    r = NoteResult("pass", 0.95, STATED, reason="note", dids=["d1"], sentence=STATED, affirmed=True)
    v = not_final(CRITERIA[2], note_verdict(CRITERIA[2], r, True), may)
    assert may and tier(RS, [_coded("pass"), v], 0.75, note_block=may)[0] == "review"


def test_a_stored_row_never_excludes_when_re_tiered() -> None:
    """MICROBATCH's re-check of the pool and any re-run re-tier stored rows: any stored note or mixed row (any
    verdict, basis, final, affirmed, quote and confidence, rows from before every field included) under any policy."""
    n = 0
    verdict: Any
    basis: Any
    for c, verdict, basis, final, affirmed, quote, conf, policy, coded in itertools.product(
        NOTES,
        ("pass", "fail", "unknown"),
        ("pair", "single", None),
        (True, False, None),
        (True, False, None),
        QUOTES,
        (0.5, 0.95),
        POLICIES,
        ("pass", "unknown", "fail"),
    ):
        row = CriterionVerdict(
            id=c.id,
            verdict=verdict,
            evidence=Evidence(resource_refs=["DocumentReference/d1"], quote=quote, confidence=conf),
            basis=basis,
            final=final,
            affirmed=affirmed,
        )
        st = decision.status_of(RS.by_id(), [_coded(coded), row], policy)
        why = (c.id, verdict, basis, final, affirmed, quote, conf, policy)
        assert (st.tier == "excluded") is (coded == "fail"), why
        n += 1
    assert n == 4 * 3 * 3 * 3 * 3 * 3 * 2 * 6 * 3
