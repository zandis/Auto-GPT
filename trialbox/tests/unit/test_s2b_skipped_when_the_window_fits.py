"""Lane G's review (#639, 2026-11-15), card 1: SCREEN skips S2b where it changes no prompt.

SCREEN routes every zero-hit pair with sentences to the judge, whatever its S2b score (``absence_semantics=False``),
and when every note of the window fits the excerpt budget the builder shows them all in full, by date: the ranking
changes nothing the models read. Embedding there was pure cost (about 600 to 900 s of a 1,275 s job on the box). With
``CascadeConfig.s2b_when_fits`` False (SCREEN's setting) such a pair goes to the judge without S2b; the prompts are
byte for byte the same. S2b still runs when the window does not fit (the ranking picks what is shown), for the index
sweep (its score decides a rescue), and wherever absence semantics hold. Synthetic notes, a recording judge.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.client import LakeLocal
from matching.cascade import engine
from matching.cascade.engine import CascadeConfig, run_cascade

from tests.judge_kit import ScriptedJudge, note_criterion, note_lake, reply, ruleset

IDX = date(2026, 10, 5)
SNAP = "2026-10-05"
PATIENTS = {
    "P-1": [(date(2026, 9, 1), "Seen in clinic.\nKnee pain, no swelling."), (date(2026, 9, 20), "Walks well.")],
    "P-2": [(date(2026, 8, 3), "Follow-up visit.\nBlood pressure stable.")],
    "P-3": [(date(2026, 9, 9), "Routine check.\nNo new complaints.")],
}
CRIT = note_criterion("T-EXC-02", "exclusion", "Active tuberculosis", "Does the patient have active tuberculosis?")


class Counting(HashEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.texts = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts += len(texts)
        return super().embed(texts)


@pytest.fixture(scope="module")
def lake(tmp_path_factory: pytest.TempPathFactory) -> LakeLocal:
    return note_lake(tmp_path_factory.mktemp("s2b-fits"), PATIENTS, SNAP)


def _run(lake: LakeLocal, fits: bool) -> tuple[list[str], int, Any]:
    prompts: list[str] = []

    def script(role: str, kw: dict[str, Any]) -> Any:
        prompts.append(json.dumps([role, kw["criterion_text"], kw["note_question"], kw["excerpts"]], sort_keys=True))
        return reply("not_met", quote=None)

    emb = Counting()
    cfg = CascadeConfig(study_id="T", run_date=IDX, lookback_months=36, index_mode="single", purpose="screening",
                        step_id="t", snapshot=SNAP, population=sorted(PATIENTS), language="en",
                        absence_semantics=False, s2b_when_fits=fits)  # fmt: skip
    res = run_cascade(lake, ruleset([CRIT]), cfg, judge=ScriptedJudge(script), embedder=emb, reviewer=None)
    return sorted(prompts), emb.texts, res


def test_the_prompts_are_the_same_without_s2b_when_the_window_fits(lake: LakeLocal) -> None:
    with_s2b, embedded, res_a = _run(lake, True)
    without, embedded_none, res_b = _run(lake, False)
    assert with_s2b and with_s2b == without  # byte for byte
    assert embedded > 0 and embedded_none == 0
    assert {p: t.tier for p, t in res_a.traces.items()} == {p: t.tier for p, t in res_b.traces.items()}
    assert res_b.metrics.s2b_skipped_fit == len(PATIENTS) and res_a.metrics.s2b_skipped_fit == 0


def test_s2b_still_runs_when_the_window_does_not_fit(lake: LakeLocal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "EXCERPT_TOKENS", 4)  # nothing fits: the ranking picks what is shown
    _prompts, embedded, res = _run(lake, False)
    assert embedded > 0 and res.metrics.s2b_skipped_fit == 0


def test_screen_skips_s2b_where_it_changes_no_prompt() -> None:
    src = Path(__file__).resolve().parents[2] / "services" / "orchestrator" / "scenarios" / "screen_cascade.py"
    assert "s2b_when_fits=False" in src.read_text(encoding="utf-8")
