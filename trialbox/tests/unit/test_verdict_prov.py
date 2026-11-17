"""D-989 step 2a: each candidate-list verdict names the model calls it rests on (``prov``), and says when none did.

* a coded answer (S1's SQL), a person's check and a criterion nobody evaluated carry ``prov: []``: "no model" is
  stated, not inferred from absence (the integrator's reading of D-989);
* a note answer names the judge's call and, where it ran, the verifier's, also when the pair disagreed (both answers
  influenced the "unknown"), and only the judge's when the verifier did not answer;
* the cascade's evidence keeps every call of the pair, and its verdict reads them back; an outcome stored before the
  ``calls`` meta still names its ``call_id``;
* the field is in the candidate list's schema (1.5.0) and survives a round trip.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

from matching.cascade.judge import JudgeReply
from matching.cascade.model import Outcome
from orchestrator.scenarios.evaluate import NoteJudge, NoteResult, human_verdict, note_verdict, structured_verdict
from orchestrator.scenarios.screen_cascade import verdict_of
from tb_common.llm import LlmError, LlmResult
from tb_contracts import CriterionVerdict

DAY = date(2026, 11, 1)
QUOTE = "Acute gout flare of the right toe."
EXCERPTS = [{"date": "2026-10-01", "note_type": "progress", "text": QUOTE, "did": "D1"}]


class Model:
    """One model of the pair: its answer, its served name and the call id each answer comes back under."""

    gateway = None

    def __init__(self, name: str, call_id: str, verdict: str | None = "pass") -> None:
        self.model = name
        self.served_root = name
        self.call_id = call_id
        self.verdict = verdict

    def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
        if self.verdict is None:
            raise LlmError("LLM endpoint unreachable (local): scripted outage")
        data = {"verdict": self.verdict, "reason": "r", "confidence": 0.95, "quote": QUOTE, "quote_date": "2026-10-01"}
        return LlmResult(data, prompt_id, 4, self.model, "local", "i" * 64, "o" * 64, 10, 2, 1, call_id=self.call_id)


def _crit(cid: str = "N-INC-01", kind: str = "inclusion") -> Any:
    return SimpleNamespace(id=cid, kind=kind, class_="note", text="Gout", note_question="Gout?", logic=None)


def _ask(verifier: Model | None) -> NoteResult:
    judge = NoteJudge(lake=None, llm=Model("judge-a", "call-judge"), verifier=verifier)  # type: ignore[arg-type]
    return judge.judge_excerpts("Gout", "Gout?", DAY, EXCERPTS)


def test_a_coded_answer_a_persons_check_and_no_answer_say_no_model() -> None:
    coded = structured_verdict(_crit(), None)
    assert coded.prov == []
    assert human_verdict(_crit()).prov == []
    assert note_verdict(_crit(), NoteResult("unknown", 0.0, reason="model_down")).prov == []


def test_a_pairs_answer_names_both_calls() -> None:
    r = _ask(Model("verifier-b", "call-verifier"))
    assert r.predicate == "pass" and r.calls == ["call-judge", "call-verifier"]
    v = note_verdict(_crit(), r, pair=True)
    assert v.verdict == "pass" and v.prov == ["call-judge", "call-verifier"]


def test_a_disagreement_names_both_calls_behind_its_unknown() -> None:
    r = _ask(Model("verifier-b", "call-verifier", verdict="fail"))
    assert r.predicate == "unknown"
    assert note_verdict(_crit(), r, pair=True).prov == ["call-judge", "call-verifier"]


def test_a_verifier_that_did_not_answer_adds_no_call() -> None:
    r = _ask(Model("verifier-b", "call-verifier", verdict=None))
    assert r.calls == ["call-judge"]


def test_one_model_names_its_one_call() -> None:
    r = _ask(None)
    assert note_verdict(_crit(), r, pair=False).prov == ["call-judge"]


def test_a_cascade_reply_names_its_own_call_unless_it_carries_the_pairs() -> None:
    one = JudgeReply("pass", 0.9, QUOTE, None, "r", call_id="c1")
    assert one.all_calls == ("c1",)
    assert JudgeReply("pass", 0.9, QUOTE, None, "r", call_id="c1", calls=("c1", "c2", "c1")).all_calls == ("c1", "c2")
    assert JudgeReply("unknown", 0.0, None, None, "r").all_calls == ()


def test_the_cascade_verdict_reads_the_calls_back_and_s1_states_none() -> None:
    span = {"did": "D1", "quote": QUOTE, "date": "2026-10-01"}
    s3 = Outcome("N-INC-01", "pass", "S3", evidence=[span, {"call_id": "c1", "calls": ["c1", "c2"]}])
    assert verdict_of(s3, pair=True).prov == ["c1", "c2"]
    before = Outcome("N-INC-01", "pass", "S3", evidence=[span, {"call_id": "c1"}])  # stored before the calls meta
    assert verdict_of(before).prov == ["c1"]
    s1 = Outcome("S-INC-01", "pass", "S1", evidence=[{"source": "lake", "record": "Condition/1"}])
    assert verdict_of(s1).prov == []


def test_the_field_is_in_the_candidate_list_and_survives_a_round_trip() -> None:
    v = CriterionVerdict(id="N-INC-01", verdict="pass", prov=["c1", "c2"])
    assert CriterionVerdict.model_validate_json(v.model_dump_json()).prov == ["c1", "c2"]
    assert CriterionVerdict(id="X", verdict="unknown").prov is None  # a row stored before the field
