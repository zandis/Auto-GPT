"""invariant: no evaluation path excludes on a negated, family-history, rule-out or suspected quote.

D-985 says an exclusion's "present" stands only on a quote that states the condition. Before D-1266 only the cascade's
S3 read it; the v1 note verdict (re-checks of new patients, NAV, CASE, and SCREEN when the pipeline is set to v1)
excluded on these quotes with both models agreeing as a real pair at 0.9 (review R22-16). Each input runs on both
paths with a pair of two different models, the quote verbatim in the record, and a run that may exclude on notes.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from matching import decision
from matching.cascade.judge import verify_span
from orchestrator.scenarios.evaluate import NoteJudge, is_pair, note_verdict, tier
from orchestrator.scenarios.screen_cascade import OrchestratorJudge, verdict_of
from tb_common.quotes import quote_in
from tb_contracts import CriterionIR

from tests.unit.test_note_pair_disagreement import FakeModel
from tests.unit.test_safety_properties import _run_for_map

IDX = date(2026, 2, 1)
NOTE_DATE = "2026-01-10"
JA_RECORD = "母親にHIV感染あり。患者本人のHIV検査は陰性。"

# (case id, the exclusion's text, the record, the quote both models give)
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
    # the pair's answer as given (a final pair "present"); the shared rule decides it may not exclude
    assert (v.verdict, v.basis) == ("fail", "pair")
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
    # the cascade's outcome as before D-1266: unknown, not hard, the inferred reason
    assert o.status == "unknown" and not o.hard and o.reason == decision.INFERRED


def test_control_an_affirmative_quote_still_excludes_on_both_paths() -> None:
    _, text, record, quote = CONTROL
    assert _v1(text, record, quote) == "excluded"
    o, t = _cascade(text, record, quote)
    assert o.status == "fail" and o.hard and t == "excluded"


def test_a_stored_row_is_read_by_the_same_rule() -> None:
    """A stored v1 fail from before D-1266 (a pair's, final, sure) re-tiered: the shared rule reads its quote."""
    from tb_contracts import CriterionVerdict, Evidence

    c = _exclusion("Known HIV infection")
    pol = decision.Policy(0.75, note_block=True)
    row = CriterionVerdict(
        id=c.id, verdict="fail", basis="pair", final=True, prov=[],
        evidence=Evidence(resource_refs=["DocumentReference/D1"], quote="Mother has HIV.", confidence=0.9,
                          reason="note"),
    )  # fmt: skip
    assert decision.answer_of(c, row, pol) == "unknown" and row.evidence is not None
    stated = row.model_copy(update={"evidence": row.evidence.model_copy(update={"quote": CONTROL[3]})})
    assert decision.answer_of(c, stated, pol) == "no"


def test_an_inclusion_is_never_affected() -> None:
    c = _exclusion("Known HIV infection").model_copy(update={"kind": "inclusion"})
    assert decision.inferred_exclusion(c, True, "Mother has HIV.") is None


# --------------------------------------------------------------------------- one pair of quotation marks (D-1266)
def test_a_quote_wrapped_in_one_pair_matches() -> None:
    assert quote_in("「母親にHIV感染あり。」", JA_RECORD)
    assert quote_in('"Mother has HIV."', NEVER[0][2])
    assert quote_in("“Mother has HIV.”", NEVER[0][2])


def test_a_quote_with_brackets_inside_it_is_unchanged() -> None:
    record = "診断名「高血圧」あり、「糖尿病」なし。"
    assert quote_in("診断名「高血圧」あり", record)
    assert quote_in("「高血圧」あり、「糖尿病」", record)  # brackets of its own: read as written
    assert not quote_in("「高血圧」あり、「糖尿病」", "高血圧」あり、「糖尿病")  # nothing stripped
    assert not quote_in("「」", JA_RECORD) and not quote_in("「「母親にHIV感染あり。」」", JA_RECORD)
