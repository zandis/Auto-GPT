"""A-NOTES-ONLY (lane G's dry run of public sets, defect 4, #593 2026-11-14): a ruleset with no structured criterion
screens; SCREEN no longer refuses it.

The cascade refused such a ruleset at S1 ("has no compiled structured criteria"); no decision or test named that
rule. A public protocol that compiles to note criteria only was refused outright. Now S1 passes every in-scope
patient alive at an index date to the note stage, and in screening (one index date) the notes answer each patient as
they do when the coded criteria pass. Guards (review of D-788): a ruleset where nothing decides (no coded and no note
inclusion or exclusion) sends every patient in scope to review (D-909, before it was refused); a notes-only run needs
a pair budget (``max_pairs``), since every patient goes
to the models; and with nothing coded a patient is "strong" only on a judged "met", never on absence alone. The SQL
for no criterion has no trailing comma. Synthetic fixture, stub judges.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

TRIAL = "GZQO"
ROOT = Path(__file__).resolve().parents[2]


def _sql(rs: Any, criteria: list[Any]) -> str:
    from criteria_compiler.compile_sql.generator import SqlGenerator
    from criteria_compiler.terminology.mapper import Terminology, ValueSets

    return SqlGenerator(rs.id, rs.version, ValueSets(rs.id, rs.valuesets, Terminology())).render(criteria)


def test_the_generator_writes_valid_sql_for_no_criterion(tmp_path: Path) -> None:
    import duckdb
    from tb_common.ruleset import Ruleset

    rs = Ruleset.load(ROOT / "rulesets" / TRIAL)
    sql = _sql(rs, [])
    con = duckdb.connect(str(tmp_path / "t.duckdb"))
    con.execute(
        "CREATE TABLE patient (pid VARCHAR, birth_date DATE, sex VARCHAR, deceased_date DATE, deceased BOOLEAN)"
    )
    con.execute(
        "INSERT INTO patient VALUES ('P1', DATE '1960-01-01', 'F', NULL, NULL), "
        "('P2', DATE '1950-01-01', 'M', DATE '2020-01-01', TRUE)"
    )
    assert ",\n  \nFROM" not in sql and "index_date,\n" not in sql.split("SELECT b.pid")[1].split("FROM")[0]
    rows = con.execute(sql, [["2026-10-31"], None]).fetchall()
    assert [(r[0], str(r[1])) for r in rows] == [("P1", "2026-10-31")]  # alive at the index date, nothing else


@pytest.fixture(scope="module")
def env(synth_dir: Path, tmp_path_factory: pytest.TempPathFactory, pg_cluster_url: str) -> dict[str, Any]:
    from embed_service.embedder import HashEmbedder
    from lake.client import LakeLocal
    from matching.cascade import CascadeConfig

    from tools.cascade_e2e import load_trial, run_end_to_end

    out = tmp_path_factory.mktemp("notes_only")
    with pytest.MonkeyPatch.context() as mp:  # module fixtures run before the per-test TB_DB_URL (D-126)
        mp.setenv("TB_DB_URL", f"{pg_cluster_url}{'&' if '?' in pg_cluster_url else '?'}tb_prefix=m{os.getpid()}nonl_")
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


class TextJudge:
    """Decided answers fixed by the excerpts' text: "met" when an excerpt holds the criterion's first word, quoting
    it; else "not met", quoting the first excerpt; else unknown. The same excerpts give the same answer."""

    def judge(self, **kw: Any) -> Any:
        from matching.cascade.judge import JudgeReply

        words = str(kw.get("criterion_text") or kw.get("text") or "").split()
        excerpts = list(kw.get("excerpts") or [])
        if not excerpts or not words:
            return JudgeReply("unknown", 0.0, None, None, "no text")
        hit = next((e for e in excerpts if words[0].lower() in str(e.get("text", "")).lower()), None)
        e = hit or excerpts[0]
        return JudgeReply("pass" if hit else "fail", 0.9, str(e["text"])[:60], str(e.get("date")), "text judge")


def _run(env: dict[str, Any], rs: Any, judge: Any = None, **cfg: Any) -> Any:
    from embed_service.embedder import HashEmbedder
    from matching.cascade import run_cascade

    from tests.unit.test_cascade_pipeline import RecordingJudge
    from tools.cascade_e2e import _reviewer

    conf = replace(env["cfg"], **cfg)
    return run_cascade(
        env["lake"], rs, conf, judge=judge or RecordingJudge(), embedder=HashEmbedder(), reviewer=_reviewer(None, rs)
    )


def _notes_only(rs: Any) -> Any:
    from matching.cascade.engine import JUDGED

    keep = [c for c in rs.criteria if c.class_ in JUDGED or c.class_ == "human"]
    out = replace(rs, criteria=keep)
    out.sql = _sql(rs, [])
    return out


def test_a_ruleset_of_note_criteria_only_screens(env: dict[str, Any]) -> None:
    rs = _notes_only(env["rs"])
    res = _run(env, rs)
    in_scope = [t for t in res.traces.values() if t.in_scope]
    assert in_scope and all(t.index_date is not None for t in in_scope)
    assert res.applied == [] and res.note_criteria  # nothing coded applied; the notes decide
    assert all(t.exit_stage != "S1" for t in in_scope)  # S1 excludes no one: there is nothing coded to fail


def test_in_screening_removing_the_coded_criteria_changes_no_note_outcome_of_a_patient_they_let_through(
    env: dict[str, Any],
) -> None:
    """Screening has one index date (``index_mode="single"``), so the note window is the same with or without the
    coded criteria; the judge gives decided answers (review: an always-unknown judge compared nothing)."""
    full = _run(env, env["rs"], TextJudge(), index_mode="single")
    only = _run(env, _notes_only(env["rs"]), TextJudge(), index_mode="single")
    note_ids = set(full.note_criteria)
    through = [p for p, t in full.traces.items() if t.in_scope and t.exit_stage != "S1"]
    assert through
    decided = 0
    for p in through:
        a = {c: o.status for c, o in full.traces[p].outcomes.items() if c in note_ids}
        b = {c: o.status for c, o in only.traces[p].outcomes.items() if c in note_ids}
        assert a == b, p
        decided += sum(1 for v in a.values() if v in ("pass", "fail"))
    assert decided  # the comparison compared decided answers


def test_a_ruleset_where_nothing_decides_sends_every_patient_to_review(env: dict[str, Any]) -> None:
    """Review of D-788: all-human (every coded criterion demoted at compile) or empty, every patient read "high", so
    the run was refused. D-909 (red of lane G's run, 2026-11-16: 16 public protocols compiled to "for a person" only):
    such a run is an answer. S0 and S1 still scope the patients, nobody is judged, and every patient in scope is
    listed for review, never "high" and never under criteria not matched; the report says why."""
    from orchestrator.scenarios.screen import judging_sentence
    from orchestrator.scenarios.screen_cascade import verdicts_of

    rs = env["rs"]
    human = replace(rs, criteria=[c.model_copy(update={"class_": "human"}) for c in rs.criteria])
    human.sql = _sql(rs, [])
    empty = replace(rs, criteria=[])
    empty.sql = _sql(rs, [])
    for each in (human, empty):
        res = _run(env, each)
        assert res.metrics.nothing_decides
        scoped = [t for t in res.traces.values() if t.in_scope]
        assert scoped
        for t in scoped:
            v = verdicts_of(each, t)
            assert v.tier == "review" or (v.tier == "excluded" and not t.contact_ok), (t.pid, v.actions)
            assert not any(o.status in ("pass", "fail") for o in t.outcomes.values())  # nobody decided anything
    for lang in ("en", "ja", "zh-TW"):
        assert judging_sentence({"mode": "nothing"}, lang) != judging_sentence({"mode": "none"}, lang)


def test_a_run_with_nothing_coded_needs_a_pair_budget(env: dict[str, Any]) -> None:
    """Review: nothing at run time bounded the judge calls when every patient goes to the note stage."""
    from matching.cascade.engine import CascadeError

    with pytest.raises(CascadeError, match="max_pairs"):
        _run(env, _notes_only(env["rs"]), max_llm_items=None)


def test_with_nothing_coded_absence_alone_is_never_strong(env: dict[str, Any]) -> None:
    """Review: with absence semantics a patient whose only outcome was "not found in the notes" read "strong"."""
    only_exclusions = [c for c in _notes_only(env["rs"]).criteria if c.kind == "exclusion" or c.class_ == "human"]
    rs = replace(env["rs"], criteria=only_exclusions)
    rs.sql = _sql(env["rs"], [])
    res = _run(env, rs, TextJudge(), absence_semantics=True)
    assert any(o.reason and "absence" in o.reason for t in res.traces.values() for o in t.outcomes.values())
    for t in res.traces.values():
        if t.tier == "strong":
            assert any(o.status == "pass" and o.stage in ("S3", "S4") for o in t.outcomes.values()), t.pid


def test_a_screen_with_no_budget_set_gives_a_notes_only_ruleset_its_populations_pairs(env: dict[str, Any]) -> None:
    """G7 of the P1b review (D-953): every notes-only ruleset stopped at "running" on the guard above, since the mail
    sets no max_pairs. SCREEN gives it the population's own pairs; a coded ruleset keeps no budget."""
    from orchestrator.scenarios.screen_cascade import notes_only_budget

    rs = _notes_only(env["rs"])
    pids = [t.pid for t in _run(env, rs, max_llm_items=10_000).traces.values() if t.in_scope]
    budget = notes_only_budget(rs, pids)
    judged = [c for c in rs.active() if c.class_ in ("note", "mixed") and c.kind in ("inclusion", "exclusion")]
    assert budget == len(pids) * len(judged)
    res = _run(env, rs, max_llm_items=budget)
    assert res.metrics.unprocessed == 0  # every pair fits: the budget stops nothing a screen would read
    assert notes_only_budget(env["rs"], pids) is None  # coded: unchanged
