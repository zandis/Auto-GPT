"""SCREEN on the v1 evaluator (``TB_SCREEN_PIPELINE=v1``) reports the note judge that ran (audit 2026-11-11).

The run built one judge for its ``judging`` record before the evaluation and the evaluator built a second one that
did the work, so the candidate list, the PDF and the mail always said 0 disagreements and 0 failures on the v1 path.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from matching import coded_values
from orchestrator.scenarios import screen
from orchestrator.scenarios.evaluate import NoteJudge, PatientVerdicts
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
GZQO = Ruleset.load(ROOT / "rulesets" / "GZQO")
RUN = date(2026, 10, 5)


def test_the_v1_run_reports_the_disagreements_of_the_judge_that_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    used: list[NoteJudge] = []

    def evaluate(rs: Any, pids: list[str], index_date: date, engine: Any, judge: Any, *a: Any, **kw: Any) -> Any:
        used.append(judge)
        judge.disagreements += 2
        judge.calls += 10
        return {p: PatientVerdicts(p, [], "review", [], 0) for p in pids}

    monkeypatch.setenv("TB_SCREEN_PIPELINE", "v1")
    monkeypatch.setenv("TB_SCREEN_JUDGE", "single")
    monkeypatch.setattr(screen, "practitioners_of", lambda ctx, rs: ["D1"])
    monkeypatch.setattr(screen, "scope_patients", lambda *a, **kw: [screen.Scoped("P1", None, "D1", "RHEUM")])
    monkeypatch.setattr(screen, "drop_opted_out", lambda ctx, scoped: scoped)
    monkeypatch.setattr(screen, "evaluate_patients", evaluate)
    monkeypatch.setattr(coded_values, "attach", lambda *a, **kw: 0)
    monkeypatch.setattr(screen, "pinned_judge", lambda rs: "judge")
    audit: list[tuple[str, dict[str, Any]]] = []
    ctx: Any = SimpleNamespace(
        job=SimpleNamespace(
            job_id="J1", options={}, metrics=None, received_at=datetime(2026, 10, 5, 1, 0, tzinfo=UTC), ruleset="GZQO"
        ),
        metrics=lambda **kw: None,
        orch=SimpleNamespace(audit=SimpleNamespace(append=lambda ev, **kw: audit.append((ev, kw)))),
        services=SimpleNamespace(lake=None, fhir=None, llm=SimpleNamespace(model="judge-a"), verifier=None),
        cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Taipei"), settings=SimpleNamespace(thresholds=None)),
    )
    srun = screen.run_screen(ctx, GZQO, RUN, "2026-10-04")
    assert len(used) == 1 and srun.judge is used[0]  # one judge: the one the run reports
    assert srun.judging is not None and srun.judging["disagreements"] == 2
    (evaluated,) = [kw for ev, kw in audit if ev == "screen.evaluated"]
    assert evaluated["detail"]["judging"]["disagreements"] == 2
