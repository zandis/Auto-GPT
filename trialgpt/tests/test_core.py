"""Core pipeline against the mock LLM: fidelity with NCBI's prompts and scoring, label handling, LLM client rules."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.conftest import CALLS, REAL_CLIENT, trial
from trialgpt_local import core, metrics, prompts
from trialgpt_local.config import ROOT, settings
from trialgpt_local.llm import ContextOverflow, LLMClient, extract_json

VENDOR = ROOT / "vendor" / "ncbi_trialgpt"


def _vendor_fn(rel: str, name: str) -> Any:
    """Execute one function from the vendored NCBI file without importing it (it builds an Azure client on import)."""
    src = (VENDOR / rel).read_text()
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns: dict[str, Any] = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), rel, "exec"), ns)
    return ns[name]


def test_prompts_are_verbatim_ncbi() -> None:
    import subprocess
    import sys

    assert subprocess.run([sys.executable, "tools/sync_prompts.py", "--check"], cwd=ROOT).returncode == 0
    t = trial("NCT9", ["Age >= 18", "Gout"], ["Pregnancy"])
    vendor = _vendor_fn("trialgpt_matching/TrialGPT.py", "get_matching_prompt")
    ns_parse = _vendor_fn("trialgpt_matching/TrialGPT.py", "parse_criteria")
    ns_print = _vendor_fn("trialgpt_matching/TrialGPT.py", "print_trial")
    vendor.__globals__.update(parse_criteria=ns_parse, print_trial=ns_print)
    ns_print.__globals__.update(parse_criteria=ns_parse)
    for kind in ("inclusion", "exclusion"):
        assert prompts.get_matching_prompt(t, kind, "0. note") == vendor(t, kind, "0. note")


def test_number_patient_matches_ncbi_and_splits_cjk() -> None:
    numbered, _ = core.number_patient("A 58-year-old woman. She has HTN.")
    assert numbered.splitlines() == ["0. A 58-year-old woman.", "1. She has HTN.", f"2. {core.CONSENT}"]
    _, zh = core.number_patient("病人主訴胃痛。無發燒！Creatinine 1.5 mg/dL.")
    assert zh[:3] == ["病人主訴胃痛。", "無發燒！", "Creatinine 1.5 mg/dL."]


def test_match_trial_labels_and_scores() -> None:
    c = LLMClient()
    numbered, _ = core.number_patient("A 60-year-old man with gout.")
    t = trial("NCT1", ["Adults with gout", "NEGATIVE prior biologic", "GARBLED x"], ["Pregnancy"])
    m = core.aggregate(c, core.match_trial(c, t, numbered), t, numbered)
    labels = {(r.kind, r.idx): r.label for r in m.criteria}
    assert labels[("inclusion", "0")] == "included"  # "Included" normalised (default)
    assert labels[("inclusion", "1")] == "not included" and labels[("inclusion", "2")] == "parse error"
    assert m.criteria[0].criterion == "Adults with gout" and m.criteria[0].evidence == [0]
    # NCBI rank_results: included/(included+not included+no info) - 1 for any "not included" = 1/2 - 1
    assert m.matching_score == pytest.approx(0.5 - 1)
    assert m.aggregation_score == pytest.approx((80 - 60) / 100) and m.score == pytest.approx(-0.5 + 0.2)
    strict = core.match_trial(c, t, numbered, strict_labels=True)
    assert {(r.kind, r.idx): r.label for r in strict.criteria}[("inclusion", "0")] == "parse error"


def test_extract_json_variants() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go: {"a": {"b": 2}} done') == {"a": {"b": 2}}
    assert extract_json("not json") is None


def test_llm_client_options_cache_and_overflow(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c = LLMClient()
    msgs = [{"role": "system", "content": "key conditions"}, {"role": "user", "content": "gouty arthritis patient"}]
    r1 = c.chat_json(msgs)
    body = CALLS[-1]
    assert body["format"] == "json" and body["options"]["num_ctx"] == 4096 and body["options"]["temperature"] == 0
    r2 = c.chat_json(msgs)
    assert r2.cached and r2.text == r1.text and len(CALLS) == 1
    nocache = LLMClient(cache=False)
    before = len(list((isolated / "cache").rglob("*.json")))
    nocache.chat_json([msgs[0], {"role": "user", "content": "another patient with gout"}])
    assert len(list((isolated / "cache").rglob("*.json"))) == before  # nothing written

    def overflow(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "{}"}, "prompt_eval_count": 4096, "eval_count": 1})

    tight = LLMClient(http=REAL_CLIENT(transport=httpx.MockTransport(overflow)), cache=False)
    with pytest.raises(ContextOverflow):
        tight.chat_json([msgs[0], {"role": "user", "content": "a very long note"}])


def test_degenerate_generation_is_a_failed_output_not_a_crash() -> None:
    hits: list[int] = []

    def looping(request: httpx.Request) -> httpx.Response:
        hits.append(1)
        return httpx.Response(500, json={"error": "prediction aborted, token repeat limit reached"})

    c = LLMClient(http=REAL_CLIENT(transport=httpx.MockTransport(looping)))
    m = core.match_trial(c, trial("NCT1", ["adult"], ["pregnant"]), "0. A 50-year-old man.")
    assert len(hits) == 2  # one call each for inclusion and exclusion: never retried
    assert m.raw == {"inclusion": {}, "exclusion": {}} and "repeat limit" in m.errors[0]
    assert not list(settings().cache_dir.rglob("*.json"))  # not cached


def test_openai_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TG_LLM_BACKEND", "openai")
    monkeypatch.setenv("TG_LLM_BASE_URL", "http://vllm:8000/v1")
    c = LLMClient()
    c.chat_json([{"role": "system", "content": "key conditions"}, {"role": "user", "content": "patient"}])
    assert CALLS[-1]["response_format"] == {"type": "json_object"} and "options" not in CALLS[-1]
    assert settings().llm_backend == "openai"


def test_metrics_definitions() -> None:
    rel = {"a": 2, "b": 1, "c": 0, "d": 2}
    assert metrics.precision_at_k(["a", "b", "c"], rel, k=3) == pytest.approx(3 / 6)
    assert metrics.ndcg_at_k(["a", "d", "b", "c"], rel, k=10) == pytest.approx(1.0)
    assert (metrics.ndcg_at_k(["c", "b", "d", "a"], rel, k=10) or 0) < 0.8
    assert metrics.auroc({"a": 0.9, "d": 0.8, "b": 0.1}, rel) == 1.0
    assert metrics.auroc({"a": 0.1, "d": 0.1, "b": 0.1}, rel) == 0.5
    assert metrics.recall_at_n(["a", "c"], rel, 2) == pytest.approx(2 / 5)


def test_keywords() -> None:
    kw = core.generate_keywords(LLMClient(), "Patient with chronic tophaceous gout")
    assert kw["summary"] == "mock summary" and kw["conditions"]
    assert json.dumps(kw)
