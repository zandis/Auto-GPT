"""judge post-processing, tiering rules and the 300-item judge agreement set (SPEC §7.3, §8.2, §11.1)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from llm_stub.app import app as stub
from orchestrator.scenarios.evaluate import eligibility, postprocess, tier
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
