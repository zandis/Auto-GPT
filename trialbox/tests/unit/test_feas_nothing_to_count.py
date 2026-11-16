"""Red of lane G's accuracy run (#639, 2026-11-15): FEAS failed both tcga protocols with "ruleset has no structured
criteria to count", where every criterion is mixed (a coded pre-check at screening only) or read from the notes.

FEAS counts structured criteria alone (D-40), so it has nothing to count: that is the answer, not a failure. The job
now ends done, says so in its summary and headline (three languages), sends no funnel, and the job chain goes on. A
ruleset with a structured criterion is counted as before. Synthetic: a shipped ruleset with its classes changed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.scenarios import feas
from orchestrator.scenarios.feas_compute import steps
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]


def _notes_only() -> Ruleset:
    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    crit = [c.model_copy(update={"class_": "mixed" if i % 2 else "note", "note_question": c.note_question or c.text})
            for i, c in enumerate(rs.criteria)]  # fmt: skip
    return Ruleset(manifest=rs.manifest, criteria=crit, valuesets=rs.valuesets, sql=rs.sql)


def _ctx(lang: str) -> Any:
    seen: dict[str, Any] = {"states": [], "updates": {}}
    job = SimpleNamespace(ruleset="GZQO", options={}, requested_by="crc@hosp.test", job_id="J-1", ruleset_version=None)
    return SimpleNamespace(
        job=job,
        update=lambda **kw: seen["updates"].update(kw),
        state=seen["states"].append,
        metrics=seen.update,
        orch=SimpleNamespace(lang=lambda j: lang),
        services=SimpleNamespace(lake=SimpleNamespace(snapshot=lambda: pytest.fail("the lake is not read"))),
        seen=seen,
    )


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_a_ruleset_with_nothing_to_count_ends_done_and_says_so(monkeypatch: pytest.MonkeyPatch, lang: str) -> None:
    rs = _notes_only()
    assert not any(s.applied for s in steps(rs))
    monkeypatch.setattr(feas, "approved_or_none", lambda ctx, rid, v: rs)
    monkeypatch.setattr(feas, "protocol_input", lambda ctx: None)
    ctx = _ctx(lang)
    out = feas.run(ctx)
    assert out.state == "done" and out.deliveries == []
    assert out.summary_md and out.headline and "GZQO" in out.summary_md
    assert ctx.seen["patients_scoped"] == 0


def test_a_ruleset_with_a_structured_criterion_still_counts() -> None:
    assert any(s.applied for s in steps(Ruleset.load(ROOT / "rulesets" / "GZQO")))
