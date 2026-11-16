"""Lane A2's review of lane G's #772 (#639, 2026-11-16), D-907: three things from it that master lacked.

* The in-run judge cache key carries the criterion's text. The canonical hash drops free text, so two criteria with
  one note question and structure but different text shared a cached answer whenever their sentence sets met; on
  D-904's whole-window path (no ranking) the set is the whole window, so they always met.
* S2b's similarities are computed in numpy: the same numbers as :func:`cosine`, without a Python loop over every
  window of every note for each zero-hit pair.
* The embed service loads its model when it starts, in every environment, not at the first request.

Synthetic notes, a recording judge, no model.
"""

from __future__ import annotations

import json
import math
import random
from datetime import date
from typing import Any

import pytest
from embed_service import app as service
from embed_service.embedder import HashEmbedder
from fastapi.testclient import TestClient
from lake.client import LakeLocal
from matching.cascade.engine import CascadeConfig, criterion_hashes, run_cascade
from matching.cascade.s2b_semantic import cosine, cosines

from tests.judge_kit import ScriptedJudge, note_criterion, note_lake, reply, ruleset

IDX = date(2026, 10, 5)
SNAP = "2026-10-05"
PATIENTS = {"P-1": [(date(2026, 9, 1), "Seen in clinic.\nKnee pain, no swelling."), (date(2026, 9, 20), "Walks well.")]}
QUESTION = "Is there a record of the condition named in the criterion?"
A = note_criterion("T-EXC-01", "exclusion", "Active tuberculosis", QUESTION)
B = note_criterion("T-EXC-02", "exclusion", "Chronic hepatitis B", QUESTION)


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    return note_lake(tmp_path_factory.mktemp("judge-key"), PATIENTS, SNAP)


def test_two_criteria_that_differ_only_in_text_are_each_asked(lake: LakeLocal) -> None:
    rs = ruleset([A, B])
    hashes = criterion_hashes(rs)
    assert hashes[A.id] == hashes[B.id]  # the case: the canonical hash cannot tell them apart
    asked: list[str] = []

    def script(role: str, kw: dict[str, Any]) -> Any:
        asked.append(json.dumps([role, kw["criterion_text"]]))
        return reply("not_met", quote=None)

    cfg = CascadeConfig(study_id="T", run_date=IDX, lookback_months=36, index_mode="single", purpose="screening",
                        step_id="t", snapshot=SNAP, population=sorted(PATIENTS), language="en",
                        absence_semantics=False, s2b_when_fits=False)  # fmt: skip
    run_cascade(lake, rs, cfg, judge=ScriptedJudge(script), embedder=HashEmbedder(), reviewer=None)
    texts = {json.loads(x)[1] for x in asked}
    assert texts == {A.text, B.text}  # before D-907 the second was answered from the first's cache


def test_numpy_similarities_are_the_python_ones() -> None:
    rnd = random.Random(7)
    q = [rnd.uniform(-1, 1) for _ in range(32)]
    rows = [[rnd.uniform(-1, 1) for _ in range(32)] for _ in range(20)] + [[0.0] * 32]
    got = cosines(q, rows)
    assert len(got) == len(rows)
    assert all(math.isclose(g, cosine(q, r), rel_tol=1e-12, abs_tol=1e-12) for g, r in zip(got, rows, strict=True))
    assert got[-1] == 0.0 and cosines(q, []) == []


def test_the_embed_service_loads_its_model_at_start(monkeypatch: pytest.MonkeyPatch) -> None:
    loads: list[int] = []

    def load() -> Any:
        loads.append(1)
        return HashEmbedder()

    monkeypatch.setattr(service, "_embedder", None)
    monkeypatch.setattr(service, "service_embedder", load)
    with TestClient(service.app):
        assert loads == [1]  # before any request
    assert loads == [1]
