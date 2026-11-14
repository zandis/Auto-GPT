"""NEW-LLM-2, first step (deep review 2026-11-12, LLM-002): a SCREEN note criterion that nothing can retrieve for is
not judged on the first five sentences of a note; it is "not evaluated" and the run says so.

The shipped lexicon is 32 English words; "Interstitial lung disease or pulmonary fibrosis", "間質性肺疾患の既往" and
"NYHA class III or IV heart failure" get no term at all, and SCREEN ranks sentences with the hash embedder, which
knows no meaning. The models then read the first sentences of each note: "not present" for an exclusion stated
further down, with ``left_out = 0``. With ``require_retrieval`` (SCREEN sets it) such a pair is unknown, reason
"not evaluated", never sent to the judge; ``metrics.no_retrieval`` counts the pairs per criterion. A criterion with
lexicon terms, or any criterion with a semantic embedder, is retrieved as before. Synthetic notes, no model.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from matching.cascade.engine import CascadeConfig, _Note, _Run
from matching.cascade.model import PatientTrace
from tb_common.reasons import Reason, code_of
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
IDX = date(2026, 10, 5)
NOTE = _Note(
    "d1",
    date(2026, 9, 1),
    "progress",
    "x",
    [f"Routine sentence {i}." for i in range(60)] + ["Interstitial lung disease confirmed on CT."],
)


class Semantic:
    model = "e-embed-1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return HashEmbedder().embed(texts)


def _run(embedder: Any, require: bool, text: str) -> tuple[_Run, Any]:
    rs = Ruleset.load(ROOT / "rulesets" / "GOUT-COH")
    c = rs.active()[0].model_copy(update={"text": text, "note_question": None})
    cfg = CascadeConfig(study_id="S-1", run_date=IDX, require_retrieval=require)
    run = _Run(None, rs, cfg, None, embedder)  # type: ignore[arg-type]
    run.traces = {"P1": PatientTrace("P1", IDX)}
    run.notes = lambda pids: {"P1": [NOTE]}  # type: ignore[method-assign]
    return run, c


def test_a_criterion_nothing_can_retrieve_for_is_not_evaluated_and_counted() -> None:
    run, c = _run(HashEmbedder(), True, "Interstitial lung disease or pulmonary fibrosis")
    routes, zero = run.s2([c])
    assert routes == [] and zero == []  # never sent on to S2b or the judge
    o = run.traces["P1"].outcomes[c.id]
    assert o.status == "unknown" and code_of(o.reason) == Reason.NOT_EVALUATED.value
    assert run.metrics.no_retrieval == {c.id: 1}


@pytest.mark.parametrize("text", ["間質性肺疾患の既往", "NYHA class III or IV heart failure"])
def test_japanese_and_unlisted_english_criteria_too(text: str) -> None:
    run, c = _run(HashEmbedder(), True, text)
    run.s2([c])
    assert run.traces["P1"].outcomes[c.id].status == "unknown" and run.metrics.no_retrieval == {c.id: 1}


def test_a_semantic_embedder_retrieves_as_before() -> None:
    run, c = _run(Semantic(), True, "Interstitial lung disease or pulmonary fibrosis")
    _routes, zero = run.s2([c])
    assert [z[1] for z in zero] == [c.id] and run.metrics.no_retrieval == {}


def test_lexicon_terms_retrieve_as_before() -> None:
    run, c = _run(HashEmbedder(), True, "History of gout flares")
    run.s2([c])
    assert c.id not in run.metrics.no_retrieval


def test_without_the_flag_nothing_changes() -> None:
    """The scale gate and the tools keep their behaviour; only SCREEN asks for retrieval."""
    run, c = _run(HashEmbedder(), False, "Interstitial lung disease or pulmonary fibrosis")
    _routes, zero = run.s2([c])
    assert [z[1] for z in zero] == [c.id] and run.metrics.no_retrieval == {}


def test_screen_asks_for_retrieval() -> None:
    src = (ROOT / "services" / "orchestrator" / "scenarios" / "screen_cascade.py").read_text("utf-8")
    assert "require_retrieval=True" in src


def test_stored_vectors_retrieve_as_before() -> None:
    """Review: with the vec.s2b flag on the stored vectors (the embed service's model) can rank sentences by meaning,
    so the criterion goes on to S2b, not cut."""
    run, c = _run(HashEmbedder(), True, "Interstitial lung disease or pulmonary fibrosis")
    run.s2b_source = object()  # type: ignore[assignment]  # a stored-vector source (D-449)
    _routes, zero = run.s2([c])
    assert [z[1] for z in zero] == [c.id] and run.metrics.no_retrieval == {}
