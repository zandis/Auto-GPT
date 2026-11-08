"""The two-model rule on the paths SCREEN runs (Fable review 2026-11-08, finding 4): a note answer excludes a patient
only when the judge and the verifier agree. v1 ``NoteJudge`` and the v4 cascade's ``OrchestratorJudge``."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from orchestrator import selftest
from orchestrator.scenarios.evaluate import NoteJudge, note_verdict, tier
from orchestrator.scenarios.screen_cascade import OrchestratorJudge
from tb_common.llm import LlmError, LlmResult
from tb_contracts import CriterionIR

EXCERPTS = [
    {"date": "2026-01-10", "note_type": "progress", "text": "Known HIV infection on ART since 2019.", "did": "D1"}
]
QUOTE = "Known HIV infection on ART since 2019."
IDX = date(2026, 2, 1)


class FakeModel:
    """An LLM client answering every judge call with one fixed reply (or raising)."""

    def __init__(self, verdict: str, conf: float = 0.9, quote: str | None = QUOTE, error: bool = False) -> None:
        self.model = f"fake-{verdict}"
        self.reply = {"verdict": verdict, "reason": "r", "confidence": conf, "quote": quote, "quote_date": "2026-01-10"}
        self.error = error
        self.calls = 0

    def chat_json(self, prompt_id: str, variables: dict[str, Any], schema: str | None = None, **kw: Any) -> LlmResult:
        self.calls += 1
        if self.error:
            raise LlmError("model down")
        data = dict(self.reply)
        if data["verdict"] == "unknown":
            data["quote"] = None
        return LlmResult(data, prompt_id, 4, self.model, "local", "i" * 64, "o" * 64, 100, 20, 1)


def _exclusion() -> CriterionIR:
    return CriterionIR.model_validate(
        {"id": "T-EXC-01", "ruleset": "T", "text": "Known HIV infection", "kind": "exclusion", "class": "note",
         "note_question": "Does the patient have HIV infection?",
         "logic": {"domain": "condition", "valueset": "VS_HIV"}}
    )  # fmt: skip


def _judge(judge: FakeModel, verifier: FakeModel | None) -> NoteJudge:
    return NoteJudge(lake=None, llm=judge, verifier=verifier)  # type: ignore[arg-type]


@pytest.mark.parametrize(("first", "second"), [("pass", "fail"), ("fail", "pass")])
def test_v1_disagreement_is_unknown_and_goes_to_review(first: str, second: str) -> None:
    c = _exclusion()
    nj = _judge(FakeModel(first), FakeModel(second))
    r = nj.judge_excerpts(c.text, c.note_question or c.text, IDX, EXCERPTS)
    assert r.predicate == "unknown" and nj.disagreements == 1 and r.reason == "disagree"
    v = note_verdict(c, r)
    rs = _ruleset(c)
    assert v.verdict == "unknown" and tier(rs, [v], 0.75, note_block=True)[0] == "review"


def test_v1_agreement_excludes_with_the_lower_confidence() -> None:
    c = _exclusion()
    nj = _judge(FakeModel("pass", 0.95), FakeModel("pass", 0.8))
    r = nj.judge_excerpts(c.text, c.note_question or c.text, IDX, EXCERPTS)
    assert r.predicate == "pass" and r.confidence == 0.8 and nj.disagreements == 0
    v = note_verdict(c, r)
    assert v.verdict == "fail" and tier(_ruleset(c), [v], 0.75, note_block=True)[0] == "excluded"
    # the same agreement under the verifier's threshold only sends the patient to review
    low = _judge(FakeModel("pass", 0.95), FakeModel("pass", 0.6)).judge_excerpts(
        c.text, c.note_question or c.text, IDX, EXCERPTS
    )
    assert tier(_ruleset(c), [note_verdict(c, low)], 0.75, note_block=True)[0] == "review"


def test_v1_verifier_down_is_a_failure_not_an_exclusion() -> None:
    nj = _judge(FakeModel("pass"), FakeModel("pass", error=True))
    r = nj.judge_excerpts(_exclusion().text, "HIV?", IDX, EXCERPTS)
    assert r.predicate == "unknown" and nj.failures == 1 and r.reason == "model_down"


def test_v1_verifier_quote_missing_is_named() -> None:
    nj = _judge(FakeModel("pass"), FakeModel("pass", quote="HIV positive since birth"))
    r = nj.judge_excerpts(_exclusion().text, "HIV?", IDX, EXCERPTS)
    assert r.predicate == "unknown" and nj.disagreements == 1 and r.reason == "verifier_quote_missing"


def test_v1_judge_unknown_never_asks_the_verifier() -> None:
    v = FakeModel("pass")
    nj = _judge(FakeModel("unknown"), v)
    assert nj.judge_excerpts(_exclusion().text, "HIV?", IDX, EXCERPTS).predicate == "unknown" and v.calls == 0


def _ask(oj: OrchestratorJudge) -> Any:
    return oj.judge(
        role="judge", criterion_text="Known HIV infection", note_question="HIV?", index_date=IDX, excerpts=EXCERPTS,
        study_id="T", data_class="D0", step_id="s", purpose="screen",
    )  # fmt: skip


@pytest.mark.parametrize(("first", "second"), [("pass", "fail"), ("fail", "pass"), ("pass", "unknown")])
def test_cascade_disagreement_is_unknown(first: str, second: str) -> None:
    oj = OrchestratorJudge(None, FakeModel(first), verifier=FakeModel(second))  # type: ignore[arg-type]
    r = _ask(oj)
    assert r.verdict == "unknown" and oj.disagreements == 1


def test_cascade_agreement_keeps_the_lower_confidence_and_verifier_down_is_unknown() -> None:
    oj = OrchestratorJudge(None, FakeModel("pass", 0.9), verifier=FakeModel("pass", 0.7))  # type: ignore[arg-type]
    r = _ask(oj)
    assert r.verdict == "pass" and r.confidence == 0.7
    down = OrchestratorJudge(None, FakeModel("pass"), verifier=FakeModel("pass", error=True))  # type: ignore[arg-type]
    assert _ask(down).verdict == "unknown" and down.failures == 1


def _ruleset(c: CriterionIR) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(by_id=lambda: {c.id: c})


# ------------------------------------------------------------------------------------------ the canary as the pair
def test_canary_runs_the_pair_and_fails_on_a_decided_wrong_pair_answer() -> None:
    cases = selftest.load_cases()
    assert len(cases) == 54 and {c["expected"] for c in cases} == {"pass", "fail", "unknown"}

    class Oracle:
        """Answers each case right, quoting the first excerpt; ``wrong`` ids answered the opposite way."""

        model = "oracle"

        def __init__(self, wrong: set[str] | None = None) -> None:
            self.wrong = wrong or set()

        def chat_json(self, prompt_id: str, variables: dict[str, Any], **kw: Any) -> LlmResult:
            case = next(
                c
                for c in cases
                if c["excerpts"] == variables["excerpts"] and c["note_question"] == variables["note_question"]
            )
            want = case["expected"]
            if case["id"] in self.wrong:
                want = {"pass": "fail", "fail": "pass", "unknown": "fail"}[want]
            quote = None if want == "unknown" else case["excerpts"][0]["text"][:20]
            d = {"verdict": want, "reason": "r", "confidence": 0.9, "quote": quote, "quote_date": None}
            return LlmResult(d, prompt_id, 4, "oracle", "local", "i" * 64, "o" * 64, 1, 1, 1)

    ok = selftest.run_selftest(Oracle(), Oracle(), cases=cases)  # type: ignore[arg-type]
    assert ok["ok"] and ok["pair"]["decided_wrong"] == 0 and ok["pair"]["cases"] == 54
    # both models wrong the same way on two "not in the note" cases: each model alone passes the per-model limits
    # (≤1 flip, silent cases are not flips) but the pair would exclude on them, so the canary fails
    silent = [c["id"] for c in cases if c["expected"] == "unknown"][:2]
    bad = selftest.run_selftest(Oracle(set(silent)), Oracle(set(silent)), cases=cases)  # type: ignore[arg-type]
    assert not bad["ok"] and bad["pair"]["decided_wrong"] == 2 and any("pair" in p for p in bad["problems"])
    # one model wrong alone: the pair does not decide on it (they disagree), so the pair is safe
    one = selftest.run_selftest(Oracle(set(silent)), Oracle(), cases=cases)  # type: ignore[arg-type]
    assert one["pair"]["decided_wrong"] == 0 and one["pair"]["disagreed"] == 2
