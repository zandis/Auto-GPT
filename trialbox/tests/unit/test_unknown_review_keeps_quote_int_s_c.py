"""INT-S-C, accepted behaviour change: a decided answer the one rule sends to review is an ``unknown`` verdict. It keeps
its quote (a person reads it) and, like every unknown, carries no confidence."""

from __future__ import annotations

from orchestrator.scenarios.evaluate import NoteResult, note_verdict

from tests.judge_kit import note_criterion


def test_a_decided_answer_sent_to_review_keeps_its_quote_and_has_no_confidence() -> None:
    exc = note_criterion("T-EXC-01", "exclusion", "No gout flare", "Does the patient have a gout flare?")
    # an exclusion "present" on a quote that does not state the condition: the rule sends it to review
    v = note_verdict(exc, NoteResult("pass", 0.9, "q", "2026-10-01", "note"))
    assert v.verdict == "unknown" and v.evidence is not None
    assert v.evidence.quote == "q" and v.evidence.quote_date == "2026-10-01"
    assert v.evidence.confidence is None
