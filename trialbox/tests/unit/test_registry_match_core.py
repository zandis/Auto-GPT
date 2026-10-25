"""Vendored TrialGPT port, core: NCBI prompt fidelity and scoring, label handling, the injected model client (S1-17)."""

from __future__ import annotations

import ast
import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from matching.registry_match import core, prompts, sync_prompts
from matching.registry_match.config import settings
from matching.registry_match.llm import (
    ChatReply,
    ContextOverflow,
    DegenerateOutput,
    LLMClient,
    LLMError,
    Messages,
    NoClientInjected,
    call_model,
    extract_json,
)
from matching.registry_match.retrieval import BM25Okapi

from eval.match_registry import metrics
from tests.registry_match_mock import MockChat, trial


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    for k, sub in (("TB_MATCH_DATA_DIR", "data"), ("TB_MATCH_RESULTS_DIR", "results"), ("TB_MATCH_CACHE_DIR", "cache")):
        monkeypatch.setenv(k, str(tmp_path / sub))
    monkeypatch.setenv("TB_MATCH_MODEL", "mock-model")
    monkeypatch.setenv("TB_MATCH_CASSETTE_DIR", str(tmp_path / "cassettes"))
    monkeypatch.delenv("TB_MATCH_LLM_MODE", raising=False)
    yield tmp_path


def _upstream_fn(rel: str, name: str) -> Any:
    """Execute one function from the NCBI upstream file without importing it (it builds a cloud client on import)."""
    src = sync_prompts.upstream_source(rel)
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns: dict[str, Any] = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), rel, "exec"), ns)
    return ns[name]


@pytest.mark.req("FR-M5-14")
def test_prompts_are_verbatim_ncbi() -> None:
    assert sync_prompts.in_sync(), "prompts.py drifted: python -m matching.registry_match.sync_prompts"
    assert sync_prompts.main(["--check"]) == 0
    t = trial("NCT9", ["Age >= 18", "Gout"], ["Pregnancy"])
    vendor = _upstream_fn("trialgpt_matching/TrialGPT.py", "get_matching_prompt")
    ns_parse = _upstream_fn("trialgpt_matching/TrialGPT.py", "parse_criteria")
    ns_print = _upstream_fn("trialgpt_matching/TrialGPT.py", "print_trial")
    vendor.__globals__.update(parse_criteria=ns_parse, print_trial=ns_print)
    ns_print.__globals__.update(parse_criteria=ns_parse)
    for kind in ("inclusion", "exclusion"):
        assert prompts.get_matching_prompt(t, kind, "0. note") == vendor(t, kind, "0. note")
    score = _upstream_fn("trialgpt_ranking/rank_results.py", "get_matching_score")
    score.__globals__["eps"] = 1e-9
    pred = {"inclusion": {"0": ["r", [0], "included"], "1": ["r", [], "not included"]}, "exclusion": {}}
    assert core.matching_score(pred) == score(pred)


def test_upstream_notice_is_kept() -> None:
    up = sync_prompts.UPSTREAM
    assert "PUBLIC DOMAIN NOTICE" in (up / "LICENSE").read_text()
    assert len((up / "COMMIT").read_text().strip()) == 40
    assert not list(up.rglob("*.py"))  # reference copies are text, never importable


def test_number_patient_matches_ncbi_and_splits_cjk() -> None:
    numbered, _ = core.number_patient("A 58-year-old woman. She has HTN.")
    assert numbered.splitlines() == ["0. A 58-year-old woman.", "1. She has HTN.", f"2. {core.CONSENT}"]
    _, zh = core.number_patient("病人主訴胃痛。無發燒！Creatinine 1.5 mg/dL.")
    assert zh[:3] == ["病人主訴胃痛。", "無發燒！", "Creatinine 1.5 mg/dL."]


def test_match_trial_labels_and_scores() -> None:
    c = LLMClient(MockChat())
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


@pytest.mark.req("FR-M5-9")
def test_without_an_injected_client_every_model_call_raises() -> None:
    msgs: Messages = [{"role": "system", "content": "key conditions"}, {"role": "user", "content": "gout"}]
    with pytest.raises(NoClientInjected):
        call_model(None, msgs)
    with pytest.raises(NoClientInjected):
        LLMClient().chat_json(msgs)
    with pytest.raises(NoClientInjected):
        core.generate_keywords(LLMClient(), "Patient with chronic tophaceous gout")


def test_llm_client_cache_cassette_and_overflow(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chat = MockChat()
    msgs: Messages = [{"role": "system", "content": "key conditions"}, {"role": "user", "content": "gouty arthritis"}]
    nocache = LLMClient(chat)  # default: nothing written (prompts carry the patient note)
    nocache.chat_json(msgs)
    assert not list((isolated / "cache").rglob("*.json")) and chat.calls[-1]["json_mode"] is True
    cached = LLMClient(chat, cache=True)
    r1 = cached.chat_json(msgs)
    r2 = cached.chat_json(msgs)
    assert r2.cached and r2.text == r1.text and len(chat.calls) == 2 and r1.prompt_tokens == 500
    monkeypatch.setenv("TB_MATCH_LLM_MODE", "record")
    LLMClient(chat).chat_json(msgs)
    monkeypatch.setenv("TB_MATCH_LLM_MODE", "cassette")
    replay = LLMClient()  # no client needed to replay
    assert replay.chat_json(msgs).cached
    with pytest.raises(LLMError, match="cassette miss"):
        replay.chat_json([msgs[0], {"role": "user", "content": "unrecorded"}])

    def overflow(messages: Messages, *, json_mode: bool) -> ChatReply:
        raise ContextOverflow("prompt does not fit")

    monkeypatch.delenv("TB_MATCH_LLM_MODE")
    with pytest.raises(ContextOverflow):
        LLMClient(overflow).chat_json(msgs)


def test_degenerate_generation_is_a_failed_output_not_a_crash() -> None:
    hits: list[int] = []

    def looping(messages: Messages, *, json_mode: bool) -> ChatReply:
        hits.append(1)
        raise DegenerateOutput("prediction aborted, token repeat limit reached")

    m = core.match_trial(
        LLMClient(looping, cache=True), trial("NCT1", ["adult"], ["pregnant"]), "0. A 50-year-old man."
    )
    assert len(hits) == 2  # one call each for inclusion and exclusion: never retried
    assert m.raw == {"inclusion": {}, "exclusion": {}} and "repeat limit" in m.errors[0]
    assert not list(settings().cache_dir.rglob("*.json"))  # not cached


@pytest.mark.req("FR-M5-14")
def test_metrics_definitions() -> None:
    rel = {"a": 2, "b": 1, "c": 0, "d": 2}
    assert metrics.precision_at_k(["a", "b", "c"], rel, k=3) == pytest.approx(3 / 6)
    assert metrics.ndcg_at_k(["a", "d", "b", "c"], rel, k=10) == pytest.approx(1.0)
    assert (metrics.ndcg_at_k(["c", "b", "d", "a"], rel, k=10) or 0) < 0.8
    assert metrics.auroc({"a": 0.9, "d": 0.8, "b": 0.1}, rel) == 1.0
    assert metrics.auroc({"a": 0.1, "d": 0.1, "b": 0.1}, rel) == 0.5
    assert metrics.recall_at_n(["a", "c"], rel, 2) == pytest.approx(2 / 5)


def test_keywords() -> None:
    kw = core.generate_keywords(LLMClient(MockChat()), "Patient with chronic tophaceous gout")
    assert kw["summary"] == "mock summary" and kw["conditions"]
    assert json.dumps(kw)


def test_bm25_okapi_formula() -> None:
    corpus = [["gout", "urate", "gout"], ["arthritis"], ["gout", "arthritis", "lupus", "x"]]
    bm = BM25Okapi(corpus)
    n, avgdl, k1, b = 3, 8 / 3, 1.5, 0.75
    idf = {w: math.log(n - f + 0.5) - math.log(f + 0.5) for w, f in {"gout": 2, "lupus": 1}.items()}
    mean_idf = sum(math.log(n - f + 0.5) - math.log(f + 0.5) for f in (2, 1, 2, 1, 1)) / 5
    idf["gout"] = 0.25 * mean_idf  # negative idf floored at epsilon x mean idf, as rank_bm25 does
    want0 = idf["gout"] * 2 * (k1 + 1) / (2 + k1 * (1 - b + b * 3 / avgdl))
    want2 = idf["gout"] * (k1 + 1) / (1 + k1 * (1 - b + b * 4 / avgdl)) + idf["lupus"] * (k1 + 1) / (
        1 + k1 * (1 - b + b * 4 / avgdl)
    )
    got = bm.get_scores(["gout", "lupus"])
    assert got[0] == pytest.approx(want0) and got[1] == 0 and got[2] == pytest.approx(want2)
