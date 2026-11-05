"""judge post-processing, tiering rules and the 300-item judge agreement set (SPEC §7.3, §8.2, §11.1)."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from llm_stub.app import app as stub
from orchestrator.clients import StepFailed
from orchestrator.scenarios.evaluate import (
    NoteJudge,
    NoteResult,
    check_judge,
    effective_note_block,
    eligibility,
    evaluate_patients,
    postprocess,
    tier,
)
from orchestrator.scenarios.terms import keywords
from tb_common.llm import LlmClient
from tb_common.ruleset import Ruleset
from tb_contracts import CriterionVerdict, Evidence

from tools.judge_eval import evaluate

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
SET = ROOT / "tests" / "fixtures" / "llm" / "judge_set.jsonl"


def test_postprocess_requires_verbatim_quote() -> None:
    ex = [{"date": "2026-10-01", "text": "目前右側第一蹠趾關節急性紅腫熱痛，\n診斷為急性痛風發作中。", "did": "D1"}]
    ok = postprocess({"verdict": "pass", "quote": "急性紅腫熱痛， 診斷為急性痛風發作中", "confidence": 0.9}, ex)
    assert ok.predicate == "pass" and ok.dids == ["D1"]
    bad = postprocess({"verdict": "pass", "quote": "病人目前發作", "confidence": 0.9}, ex)
    assert bad.predicate == "unknown" and bad.reason == "quote_not_found"
    assert postprocess({"verdict": "unknown", "confidence": 0.2}, ex).predicate == "unknown"


def _v(cid: str, verdict: str, conf: float | None = None) -> CriterionVerdict:
    return CriterionVerdict(id=cid, verdict=verdict, evidence=Evidence(resource_refs=[], confidence=conf))  # type: ignore[arg-type]


def test_tiers() -> None:
    base = [_v(c.id, "pass") for c in GZQO.active() if c.class_ == "structured"]
    human = [_v(c.id, "pending_human") for c in GZQO.active() if c.class_ == "human"]
    notes_ok = [_v("GZQO-INC-05", "pass", 0.9), _v("GZQO-EXC-11", "pass", 0.95)]
    t, actions, unknown = tier(GZQO, base + notes_ok + human, 0.75)
    assert t == "high" and unknown == 0 and "ask injection willingness" in actions
    assert tier(GZQO, [*base, _v("GZQO-INC-05", "pass", 0.6), _v("GZQO-EXC-11", "pass", 0.9)], 0.75)[0] == "review"
    assert tier(GZQO, [*base, _v("GZQO-INC-05", "unknown"), _v("GZQO-EXC-11", "pass", 0.9)], 0.75)[0] == "review"
    assert tier(GZQO, [*base, _v("GZQO-INC-05", "fail", 0.9)], 0.75)[0] == "excluded"
    assert tier(GZQO, [*base, _v("GZQO-INC-05", "fail", 0.5)], 0.75)[0] == "review"  # weak note fail is reviewed
    bad = [_v(v.id, "fail") if v.id == "GZQO-INC-03" else v for v in base]
    assert tier(GZQO, bad, 0.75)[0] == "excluded"
    assert eligibility("exclusion", True) == "fail" and eligibility("inclusion", None) == "unknown"
    assert keywords("At least 2 gout flares") == ["痛風", "發作", "発作"]


def _llm() -> LlmClient:
    url = os.environ.get("TB_JUDGE_LLM_URL")
    if url:
        return LlmClient(url, os.environ.get("TB_JUDGE_MODEL", "trialbox"))
    llm = LlmClient("http://stub/v1", "stub")
    llm.http = TestClient(stub)
    return llm


def test_judge_set_agreement_stub() -> None:
    items = [json.loads(x) for x in SET.read_text(encoding="utf-8").splitlines()]
    assert len(items) == 300 and {i["gold"] for i in items} == {"pass", "fail", "unknown"}
    report = evaluate(items, _llm())
    assert report["agreement"] >= 0.90, report


@pytest.mark.llm
def test_judge_set_agreement_real_model() -> None:
    """Phase 4 DoD with a real local model: TB_JUDGE_LLM_URL=http://<vllm>:8000/v1 pytest -m llm."""
    if not os.environ.get("TB_JUDGE_LLM_URL"):
        pytest.skip("TB_JUDGE_LLM_URL not set")
    items = [json.loads(x) for x in SET.read_text(encoding="utf-8").splitlines()]
    assert evaluate(items, _llm())["agreement"] >= 0.90


def test_model_outage_fails_the_job_instead_of_an_all_unknown_list() -> None:
    judge = NoteJudge(lake=None, llm=None)  # type: ignore[arg-type]
    check_judge(judge)
    judge.calls, judge.failures = 95, 5  # a few unanswered checks stay "unknown" for manual review
    check_judge(judge)
    judge.calls, judge.failures = 0, 25  # the gateway was down for the whole run
    with pytest.raises(StepFailed, match="25 of 25 note checks"):
        check_judge(judge)


def test_note_block_never(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """D-95: on a single-model box a confident note fail sends the patient to review, never out; structured fails
    still exclude."""
    base = [_v(c.id, "pass") for c in GZQO.active() if c.class_ == "structured"]
    monkeypatch.setenv("TB_NOTE_BLOCK", "never")
    assert tier(GZQO, [*base, _v("GZQO-INC-05", "fail", 0.95)], 0.75)[0] == "review"
    assert tier(GZQO, [*base, _v("GZQO-INC-05", "fail", 0.95)], 0.75, note_block=True)[0] == "excluded"
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    assert tier(GZQO, [*base, _v("GZQO-INC-05", "fail", 0.95)], 0.75)[0] == "excluded"
    monkeypatch.setenv("TB_NOTE_BLOCK", "sometimes")
    with pytest.raises(ValueError):
        tier(GZQO, base, 0.75)


def test_both_agree_without_a_verifier_falls_back_to_never(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """D-97: ``both_agree`` promises two models agreed; with one model the run may route to review, never exclude."""
    from types import SimpleNamespace

    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")
    judge_only = NoteJudge(SimpleNamespace(), SimpleNamespace(model="j"), "judge", verifier=None)  # type: ignore[arg-type]
    pair = NoteJudge(SimpleNamespace(), SimpleNamespace(model="j"), "judge", verifier=SimpleNamespace(model="v"))  # type: ignore[arg-type]
    assert effective_note_block(None) == (False, "never", "no note judge on this box")
    may, policy, why = effective_note_block(judge_only)
    assert (may, policy) == (False, "never") and "verifier" in why
    assert effective_note_block(pair)[:2] == (True, "both_agree")
    monkeypatch.setenv("TB_NOTE_BLOCK", "never")
    assert effective_note_block(pair)[:2] == (False, "never")

    # and evaluate_patients applies it: a confident note fail from a lone judge lands in review, not excluded
    monkeypatch.setenv("TB_NOTE_BLOCK", "both_agree")

    class Engine:
        name = "sql"

        def evaluate(self, rs, pids, index_date, ids):  # type: ignore[no-untyped-def]
            raise AssertionError("no structured criteria asked for")

    class LoneJudge(NoteJudge):
        def judge(self, pid, c, index_date, full=False):  # type: ignore[no-untyped-def]
            return NoteResult("fail", 0.99, quote="documented tophus", reason="note says so")

    lone = LoneJudge(SimpleNamespace(), SimpleNamespace(model="j"), "judge", verifier=None)  # type: ignore[arg-type]
    only = {"GZQO-INC-05"}
    kw = dict(only=only, workers=1, full_record_fallback=False)
    res = evaluate_patients(GZQO, ["p1"], date(2026, 10, 5), Engine(), lone, 0.75, **kw)  # type: ignore[arg-type]
    assert res["p1"].tier == "review"
    res = evaluate_patients(GZQO, ["p1"], date(2026, 10, 5), Engine(), lone, 0.75, note_block=True, **kw)  # type: ignore[arg-type]
    assert res["p1"].tier == "excluded"
