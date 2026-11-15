"""T-694 part 3 (placed with lane A2 on #593, 2026-11-15): the cascade's note stage runs in batches of patients, and
the statuses are the same for any batch size.

S2 and S2b read every alive patient's notes at once: at 50,000 patients with 20 notes each the run held a million
notes in memory before a single judge call. With ``CascadeConfig.note_batch`` S2 and S2b run on that many patients at
a time, reading only their notes; the routes keep only their excerpts. Each patient's answer depends on its own notes
alone, the stage logs are written once from the totals, and the routes go on to sampling and S3 in the order of an
unbatched run (a pair budget stops at the same pair). So the traces, the metrics and the stage logs are the same for
no batches, one patient a batch, and any size between. Synthetic fixture, a judge that gives decided answers.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

TRIAL = "GZQO"


@pytest.fixture(scope="module")
def env(synth_dir: Path, tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str) -> dict[str, Any]:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from matching.cascade import CascadeConfig

    from tools.cascade_e2e import load_trial, run_end_to_end

    out = tmp_path_factory.mktemp("note_batches")
    with pytest.MonkeyPatch.context() as mp:  # module fixtures run before the per-test TB_DB_URL (D-126)
        mp.setenv("TB_DB_URL", f"{pg_cluster_url}{'&' if '?' in pg_cluster_url else '?'}tb_prefix=m{os.getpid()}ntbt_")
        e2e = run_end_to_end(synth_dir / "site-a", TRIAL, out, repro=True)
    lake_dir = Path(e2e.out_dir) / "ingest" / "lake"
    snapshot = (lake_dir / "CURRENT").read_text(encoding="utf-8").strip()
    rs = load_trial(TRIAL)
    cfg = CascadeConfig(
        study_id=TRIAL,
        run_date=date(2026, 10, 5),
        lookback_months=int(rs.manifest.scopes.feas.lookback_months or 36),
        notes_class="D0",
        purpose="feasibility",
        step_id="test",
        sample_per_stratum=200,
        snapshot=snapshot,
    )
    return {"lake": LakeLocal(lake_dir, HashEmbedder(), "Asia/Taipei"), "rs": rs, "cfg": cfg}


def _run(env: dict[str, Any], **cfg: Any) -> Any:
    from embed_service.embedder import HashEmbedder
    from matching.cascade import run_cascade

    from tests.unit.test_notes_only_ruleset import TextJudge
    from tools.cascade_e2e import _reviewer

    conf = replace(env["cfg"], **cfg)
    rs = env["rs"]
    return run_cascade(env["lake"], rs, conf, judge=TextJudge(), embedder=HashEmbedder(), reviewer=_reviewer(None, rs))


def _view(res: Any) -> dict[str, Any]:
    traces = {
        p: (t.in_scope, t.index_date, t.exit_stage, t.exit_criterion, t.tier, t.sampled,
            sorted((c, o.status, o.stage, o.reason, o.hard) for c, o in t.outcomes.items()))
        for p, t in res.traces.items()
    }  # fmt: skip
    stages = [(s.stage, s.patients_in, s.patients_out, s.pairs_in, s.pairs_out, s.detail) for s in res.stages]
    m = res.metrics
    metrics = {k: getattr(m, k) for k in ("pairs_s2_hit", "pairs_s2_zero_hit", "pairs_s2_no_notes", "pairs_s2b_above",
                                          "pairs_s2b_below", "rescued", "n_after", "pairs_judged")}  # fmt: skip
    return {"traces": traces, "stages": stages, "metrics": metrics}


@pytest.mark.parametrize("index_mode", ["single", "month_ends"])
def test_the_statuses_are_the_same_for_any_batch_size(env: dict[str, Any], index_mode: str) -> None:
    whole = _view(_run(env, index_mode=index_mode))
    assert any(t[4] == "excluded" for t in whole["traces"].values())  # the comparison compares decided answers
    for size in (1, 7, 1000):
        assert _view(_run(env, index_mode=index_mode, note_batch=size)) == whole, size


def test_a_pair_budget_stops_at_the_same_pair(env: dict[str, Any]) -> None:
    whole = _view(_run(env, max_llm_items=5))
    assert _view(_run(env, max_llm_items=5, note_batch=3)) == whole


def test_each_batch_reads_only_its_patients_notes(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from matching.cascade import engine

    asked: list[int] = []
    real = engine._Run.notes

    def notes(self: Any, pids: list[str]) -> Any:
        asked.append(len(pids))
        return real(self, pids)

    monkeypatch.setattr(engine._Run, "notes", notes)
    _run(env, note_batch=4)
    assert asked and max(asked) <= 4


def test_a_batch_size_below_one_is_refused(env: dict[str, Any]) -> None:
    from matching.cascade.engine import CascadeError

    with pytest.raises(CascadeError, match="note_batch"):
        _run(env, note_batch=0)


def test_screen_runs_the_note_stage_in_batches_of_its_setting() -> None:
    from orchestrator.clients import StepFailed
    from orchestrator.scenarios.screen_cascade import note_batch_of
    from tb_common.config import DECLARED

    assert note_batch_of({}) == 1000  # SCREEN batches by default: the answers are the same, the memory bounded
    assert note_batch_of({"TB_SCREEN_NOTE_BATCH": "250"}) == 250
    assert "TB_SCREEN_NOTE_BATCH" in DECLARED
    for bad in ("0", "-3", "many"):
        with pytest.raises(StepFailed, match="TB_SCREEN_NOTE_BATCH"):
            note_batch_of({"TB_SCREEN_NOTE_BATCH": bad})
