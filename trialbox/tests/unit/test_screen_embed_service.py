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
from types import SimpleNamespace
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
    assert isinstance(got.inner, emb.HttpEmbedder) and got.model == "e-embed-1"  # wrapped: see the mid-run test


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


def _rescue_run(embedder: Any, absence: bool) -> tuple[_Run, str, list[_Note]]:
    rs = Ruleset.load(ROOT / "rulesets" / "GOUT-COH")
    c = rs.active()[0]
    cfg = CascadeConfig(study_id="S-1", run_date=IDX, absence_semantics=absence)
    run = _Run(None, rs, cfg, None, embedder)  # type: ignore[arg-type]
    t = PatientTrace("P1", IDX)
    t.outcomes[c.id] = Outcome(c.id, "unknown", "S1", reason="index_absent")
    run.traces = {"P1": t}
    # the criterion's own words in a note: the hash stub's overlap finds them
    note = _Note("d1", date(2026, 9, 1), "progress", "x", ["Breakfast was served.", c.text])
    return run, f"index:{c.id}", [note]


@pytest.mark.parametrize("absence", [False, True])
def test_a_real_models_score_never_rescues_on_the_placeholder_threshold(absence: bool) -> None:
    run, key, notes = _rescue_run(Semantic(), absence)
    run.s2b([("P1", key, notes)], [])
    t = run.traces["P1"]
    o = t.outcomes[key.split(":", 1)[1]]
    assert o.reason != "index rescued" and o.rescue is None and run.metrics.rescued == 0
    # review, never an absence: a held-back rescue is no exclusion, whatever the absence semantics
    assert o.status == "unknown" and t.exit_stage is None


def test_the_hash_stub_rescues_as_before() -> None:
    """Unchanged where the placeholder was set: the hash embedder's word overlap rescues."""
    run, key, notes = _rescue_run(HashEmbedder(), False)
    run.s2b([("P1", key, notes)], [])
    assert run.traces["P1"].outcomes[key.split(":", 1)[1]].reason == "index rescued" and run.metrics.rescued == 1


# ------------------------------------------------------------------------------------------- review fixes
def test_no_embed_url_leaves_the_local_hash() -> None:
    from orchestrator.scenarios.screen_cascade import screen_embedder

    assert isinstance(screen_embedder(None), HashEmbedder)


def test_the_probe_is_once_per_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """MICROBATCH screens many studies in one job: one probe, not one per study."""
    from orchestrator.scenarios.screen_cascade import job_embedder

    calls = {"n": 0}

    def embed(self: Any, texts: list[str]) -> list[list[float]]:
        calls["n"] += 1
        self.model = "e-embed-1"
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(emb.HttpEmbedder, "embed", embed)
    ctx = SimpleNamespace(job=SimpleNamespace(job_id="J1"), cfg=SimpleNamespace(env=SimpleNamespace(embed_url="u")))
    a, b = job_embedder(ctx), job_embedder(ctx)
    assert a is b and calls["n"] == 1


@pytest.mark.parametrize("fault", ["down", "stub"])
def test_a_service_that_fails_after_the_probe_stops_the_job_with_a_sentence(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """Mid-run: the job stops and says why, never a generic error, never two embedders mixed in one run."""
    from matching.cascade.engine import CascadeError
    from orchestrator.scenarios.screen_cascade import screen_embedder

    state = {"probed": False}

    def embed(self: Any, texts: list[str]) -> list[list[float]]:
        if not state["probed"]:
            state["probed"] = True
            self.model = "e-embed-1"
            return [[1.0, 0.0] for _ in texts]
        if fault == "down":
            raise OSError("connection reset")
        self.model = "hash-1024-v1"
        return [[1.0] for _ in texts]

    monkeypatch.setattr(emb.HttpEmbedder, "embed", embed)
    served = screen_embedder("http://embed-service:8014")
    with pytest.raises(CascadeError, match="embed service"):
        served.embed(["a sentence"])
