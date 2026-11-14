"""NEW-LLM-2, embedder step (deep review 2026-11-12, LLM-002): SCREEN ranks note sentences with the box's embed service
when it serves a real model, and a real model's on-the-fly score never decides an index rescue on the placeholder
threshold.

SCREEN hard-coded the hash stub, so on a GPU box with bge-m3 served every criterion without a lexicon term still read
"not evaluated" (#582). Now each job asks the embed service once: a real model is used; the hash stub, or no answer,
leaves the local hash embedder (retrieval by meaning off, as before). The S2b threshold is a public-prior placeholder
fitted to nothing real (CAS-14); a real model's similarities clear it almost always, so such a score only picks the
excerpts and never rescues an index condition until the refit (the rule D-449 set for stored vectors). Synthetic, no
model.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from embed_service import embedder as emb
from embed_service.embedder import HashEmbedder
from matching.cascade.engine import CascadeConfig, _Note, _Run
from matching.cascade.model import Outcome, PatientTrace
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
IDX = date(2026, 10, 5)


# ------------------------------------------------------------------------------------------- the job's embedder
def test_a_real_model_served_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.scenarios.screen_cascade import screen_embedder

    def embed(self: Any, texts: list[str]) -> list[list[float]]:
        self.model = "e-embed-1"
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(emb.HttpEmbedder, "embed", embed)
    got = screen_embedder("http://embed-service:8014")
    assert isinstance(got, emb.HttpEmbedder) and got.model == "e-embed-1"


def test_the_hash_stub_served_leaves_the_local_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.scenarios.screen_cascade import screen_embedder

    def embed(self: Any, texts: list[str]) -> list[list[float]]:
        self.model = "hash-1024-v1"
        return [[1.0] for _ in texts]

    monkeypatch.setattr(emb.HttpEmbedder, "embed", embed)
    assert isinstance(screen_embedder("http://embed-service:8014"), HashEmbedder)


def test_no_answer_leaves_the_local_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    from orchestrator.scenarios.screen_cascade import screen_embedder

    def embed(self: Any, texts: list[str]) -> list[list[float]]:
        raise OSError("connection refused")

    monkeypatch.setattr(emb.HttpEmbedder, "embed", embed)
    assert isinstance(screen_embedder("http://embed-service:8014"), HashEmbedder)


def test_screen_asks_the_embed_service() -> None:
    src = (ROOT / "services" / "orchestrator" / "scenarios" / "screen_cascade.py").read_text("utf-8")
    assert "embedder=HashEmbedder()" not in src and "screen_embedder(" in src


# ------------------------------------------------------------------------------------------- the index rescue
class Semantic:
    model = "e-embed-1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]  # every sentence "similar": 1.0, far above the placeholder


def _rescue_run(embedder: Any) -> tuple[_Run, str]:
    rs = Ruleset.load(ROOT / "rulesets" / "GOUT-COH")
    c = rs.active()[0]
    run = _Run(None, rs, CascadeConfig(study_id="S-1", run_date=IDX), None, embedder)  # type: ignore[arg-type]
    t = PatientTrace("P1", IDX)
    t.outcomes[c.id] = Outcome(c.id, "unknown", "S1", reason="index_absent")
    run.traces = {"P1": t}
    note = _Note("d1", date(2026, 9, 1), "progress", "x", ["Breakfast was served.", "The weather was mild."])
    return run, f"index:{c.id}", [note]  # type: ignore[return-value]


def test_a_real_models_score_never_rescues_on_the_placeholder_threshold() -> None:
    run, key, notes = _rescue_run(Semantic())  # type: ignore[misc]
    run.s2b([("P1", key, notes)], [])
    o = run.traces["P1"].outcomes[key.split(":", 1)[1]]
    assert o.reason != "index rescued" and o.rescue is None  # a person looks instead
    assert run.metrics.rescued == 0


def test_the_hash_stub_rescues_as_before() -> None:
    """Unchanged where the placeholder was set: the hash embedder's word overlap."""
    run, key, notes = _rescue_run(HashEmbedder())  # type: ignore[misc]
    notes[0].sents.append("Gout confirmed by the rheumatologist.")
    notes[0].low.append("gout confirmed by the rheumatologist.")
    run.s2b([("P1", key, notes)], [])
    o = run.traces["P1"].outcomes[key.split(":", 1)[1]]
    assert (o.reason == "index rescued") == (run.metrics.rescued == 1)
