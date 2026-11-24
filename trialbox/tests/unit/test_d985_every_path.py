"""invariant: no evaluation path excludes on a negated, family-history, rule-out or suspected quote.

D-985 says an exclusion's "present" stands only on a quote that states the condition. Review R22-16 found the v1 note
verdict (re-checks of new patients, NAV, CASE, and SCREEN when the pipeline is set to v1) excluding on these quotes
with both models agreeing as a real pair at 0.9, while the cascade's S3 sent them to review. R22-16 made
:func:`matching.note_answer.note_answer_may` the one rule of every path; this test holds every path to it (D-1266).
Each input runs on both paths with a pair of two different models, the quote verbatim in the record, and a run that
may exclude on notes.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from matching import decision
from matching.cascade.judge import verify_span
from matching.note_answer import INFERRED_REASON, note_answer_may
from orchestrator.scenarios.evaluate import NoteJudge, is_pair, note_verdict, tier
from orchestrator.scenarios.screen_cascade import OrchestratorJudge, verdict_of
from tb_common.quotes import as_in, unwrap
from tb_contracts import CriterionIR, CriterionVerdict, Evidence

from tests.unit.test_note_pair_disagreement import FakeModel
from tests.unit.test_safety_properties import _run_for_map

IDX = date(2026, 2, 1)
NOTE_DATE = "2026-01-10"
JA_RECORD = "母親にHIV感染あり。患者本人のHIV検査は陰性。"

# (case id, the exclusion's text, the record, the quote both models give): the four inputs of review R22-16, and the
# Japanese line against the English criterion
NEVER = [
    ("family-history", "Known HIV infection", "Mother has HIV. Patient tested negative for HIV.", "Mother has HIV."),
    ("rule-out", "History of myocardial infarction", "Rule out myocardial infarction; troponin pending.",
     "Rule out myocardial infarction; troponin pending."),
    ("suspected", "Active hepatitis C", "Suspected hepatitis C, awaiting PCR.", "Suspected hepatitis C, awaiting PCR."),
    ("family-history-ja", "HIV感染が既知の患者", JA_RECORD, "母親にHIV感染あり。"),
    ("family-history-ja-en-criterion", "Known HIV infection", JA_RECORD, "母親にHIV感染あり。"),
]  # fmt: skip
CONTROL = ("affirmative", "Known HIV infection", "Known HIV infection, on ART.", "Known HIV infection, on ART.")


class PairModel(FakeModel):
    """:class:`FakeModel` with its own weights, so that two of them are a real pair (``is_pair``, D-276)."""

    def __init__(self, quote: str) -> None:
        super().__init__("pass", 0.9, quote=quote)
        self.served_root = self.model


def _exclusion(text: str) -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": "N-EXC-01", "ruleset": "N", "text": text, "kind": "exclusion", "class": "note",
         "note_question": "Does the patient have the condition?",
         "logic": {"domain": "condition", "valueset": "VS_X"}}
    )  # fmt: skip


def _excerpts(record: str) -> list[dict[str, Any]]:
    return [{"date": NOTE_DATE, "note_type": "progress", "text": record, "did": "D1"}]


def _v1(text: str, record: str, quote: str) -> str:
    """The v1 path: ``NoteJudge.judge_excerpts`` then ``note_verdict`` with the pair's basis, tiered on a run that may
    exclude on notes."""
    c = _exclusion(text)
    nj = NoteJudge(lake=None, llm=PairModel(quote), verifier=PairModel(quote))  # type: ignore[arg-type]
    assert is_pair(nj)
    r = nj.judge_excerpts(c.text, c.note_question or c.text, IDX, _excerpts(record))
    v = note_verdict(c, r, pair=is_pair(nj))
    return tier(SimpleNamespace(by_id=lambda: {c.id: c}), [v], 0.75, note_block=True)[0]  # type: ignore[arg-type]


def _cascade(text: str, record: str, quote: str) -> tuple[Any, str]:
    """The cascade path: ``OrchestratorJudge.judge`` (the pair), the verified span, then S3's ``_map`` on a run that
    may exclude on notes; the outcome and the tier of its verdict row."""
    c = _exclusion(text)
    oj = OrchestratorJudge(None, PairModel(quote), verifier=PairModel(quote))  # type: ignore[arg-type]
    reply = oj.judge(
        role="judge", criterion_text=c.text, note_question=c.note_question or c.text, index_date=IDX,
        excerpts=_excerpts(record), study_id="N", data_class="D0", step_id="s", purpose="screen",
    )  # fmt: skip
    assert reply.verdict == "pass" and reply.confidence == 0.9
    span = verify_span(reply, _excerpts(record), date(2025, 1, 1), IDX)
    assert span is not None  # the quote is verbatim in the record
    o = _run_for_map(True)._map(c, reply, span, "S3")
    status = decision.status_of({c.id: c}, [verdict_of(o, pair=True)], decision.Policy(0.75, note_block=True))
    return o, status.tier


@pytest.mark.parametrize(("case", "text", "record", "quote"), NEVER, ids=[n[0] for n in NEVER])
def test_v1_never_excludes(case: str, text: str, record: str, quote: str) -> None:
    assert _v1(text, record, quote) != "excluded"


@pytest.mark.parametrize(("case", "text", "record", "quote"), NEVER, ids=[n[0] for n in NEVER])
def test_cascade_never_excludes(case: str, text: str, record: str, quote: str) -> None:
    o, t = _cascade(text, record, quote)
    assert t != "excluded"
    assert o.status == "unknown" and not o.hard and o.reason == INFERRED_REASON


@pytest.mark.parametrize(("case", "text", "record", "quote"), NEVER, ids=[n[0] for n in NEVER])
def test_the_one_rule_sends_each_to_review(case: str, text: str, record: str, quote: str) -> None:
    may = note_answer_may("exclusion", True, quote, text, record)
    assert may.effect == "review" and may.reason == INFERRED_REASON


def test_control_an_affirmative_quote_still_excludes_on_both_paths() -> None:
    _, text, record, quote = CONTROL
    assert _v1(text, record, quote) == "excluded"
    o, t = _cascade(text, record, quote)
    assert o.status == "fail" and o.hard and t == "excluded"


def test_a_stored_row_is_read_by_the_same_rule() -> None:
    """A stored pair's final, sure note fail re-tiered (MICROBATCH): on a family-history quote it never excludes."""
    c = _exclusion("Known HIV infection")
    row = CriterionVerdict(
        id=c.id, verdict="fail", basis="pair", final=True, prov=[],
        evidence=Evidence(resource_refs=["DocumentReference/D1"], quote="Mother has HIV.", confidence=0.9,
                          reason="note"),
    )  # fmt: skip
    assert decision.answer_of(c, row, decision.Policy(0.75, note_block=True)) == "unknown"


def test_an_exclusion_absent_and_an_inclusion_met_are_never_affected() -> None:
    assert note_answer_may("exclusion", False, "Mother has HIV.", "Known HIV infection").effect == "keeps"
    assert note_answer_may("inclusion", True, "Mother has HIV.", "Known HIV infection").effect == "keeps"


# ------------------------------------------------------------------------------------- a quote in one pair of marks
@pytest.mark.parametrize("wrapped", ["「母親にHIV感染あり。」", '"母親にHIV感染あり。"', "“母親にHIV感染あり。”"])
def test_a_quote_wrapped_in_one_pair_of_marks_is_found(wrapped: str) -> None:
    assert as_in(wrapped, JA_RECORD) == "母親にHIV感染あり。"


def test_the_wrapped_ja_quote_never_excludes_on_v1() -> None:
    """The model wraps its quote in 「」: the bare quote is found in the record and the guard still holds."""
    _, text, record, _ = NEVER[3]
    assert _v1(text, record, "「母親にHIV感染あり。」") != "excluded"


def test_a_quote_with_marks_inside_it_is_read_as_written() -> None:
    record = "診断名「高血圧」あり、「糖尿病」なし。"
    assert unwrap("「高血圧」あり、「糖尿病」") == "「高血圧」あり、「糖尿病」"
    assert as_in("「高血圧」あり、「糖尿病」", record) == "「高血圧」あり、「糖尿病」"
    assert as_in("「」", JA_RECORD) is None
