"""U6 (notelint): no note criterion is silently dead. A note or mixed criterion whose text gives the S2 lexicon no
term is "not evaluated" on every SCREEN night (inv-j5 P5: AD-MAB and RA-JAK, 8,654 rows); the ruleset lint refuses
it by name, and the shipped rulesets carry none. Synthetic notes, no model.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from embed_service.embedder import HashEmbedder
from matching.cascade.engine import CascadeConfig, _Note, _Run
from matching.cascade.model import PatientTrace
from tb_common.ruleset import Ruleset

from tools.build_rulesets import note_lint, shipped

ROOT = Path(__file__).resolve().parents[2]
IDX = date(2026, 10, 5)


def test_a_note_criterion_without_lexicon_keys_fails_the_lint_by_name() -> None:
    rs = Ruleset.load(ROOT / "rulesets" / "GOUT-COH")
    c = rs.active()[0].model_copy(
        update={"class_": "note", "text": "NYHA class III or IV heart failure", "note_question": None}
    )
    rs.criteria = [c]
    assert note_lint(rs) == [f"GOUT-COH: note criterion {c.id} has no lexicon keys (S2 cannot retrieve for it)"]


def test_the_shipped_rulesets_have_no_dead_note_criterion() -> None:
    dirs = ROOT / "rulesets"
    assert [m for rid in shipped(dirs) for m in note_lint(Ruleset.load(dirs / rid))] == []


def test_a_note_stating_the_criterion_reaches_the_judge() -> None:
    """AD-MAB-INC-03 (MMSE, Japanese text): a synthetic note stating the score is a lexicon hit, routed to S3."""
    rs = Ruleset.load(ROOT / "rulesets" / "AD-MAB")
    c = next(x for x in rs.active() if x.id == "AD-MAB-INC-03")
    note = _Note("d1", date(2026, 9, 1), "progress", "x", ["定期受診。", "MMSE 26点、HDS-R 24点。"])
    run = _Run(None, rs, CascadeConfig(study_id="S-1", run_date=IDX, require_retrieval=True), None, HashEmbedder())  # type: ignore[arg-type]
    run.traces = {"P1": PatientTrace("P1", IDX)}
    run.notes = lambda pids: {"P1": [note]}  # type: ignore[method-assign]
    routes, _zero = run.s2([c])
    assert [r.cid for r in routes] == [c.id] and run.metrics.no_retrieval == {}
