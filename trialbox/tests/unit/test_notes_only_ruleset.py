"""A-NOTES-ONLY (lane G's dry run of public sets, defect 4, #593 2026-11-14): a ruleset with no structured criterion
screens; SCREEN no longer refuses it.

The cascade refused such a ruleset at S1 ("has no compiled structured criteria"); no decision or test named that
rule, and it hid a second gap: with no criterion the SQL generator wrote invalid SQL (a trailing comma after
``b.index_date``). A public protocol that compiles to note criteria only was refused outright. Now the generator
writes the patients alive at each index date, and S1 passes every in-scope patient to the note stage with its index
date. The note stage then answers each patient as it does when the coded criteria pass: removing the coded criteria
changes no note outcome of a patient they let through. The cost guards stay (the scale gate, ``max_pairs``).
Synthetic fixture, stub judge.
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


def _run(env: dict[str, Any], rs: Any) -> Any:
    from embed_service.embedder import HashEmbedder
    from matching.cascade import run_cascade

    from tests.unit.test_cascade_pipeline import RecordingJudge
    from tools.cascade_e2e import _reviewer

    return run_cascade(
        env["lake"], rs, env["cfg"], judge=RecordingJudge(), embedder=HashEmbedder(), reviewer=_reviewer(None, rs)
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


def test_removing_the_coded_criteria_changes_no_note_outcome_of_a_patient_they_let_through(
    env: dict[str, Any],
) -> None:
    full = _run(env, env["rs"])
    only = _run(env, _notes_only(env["rs"]))
    note_ids = set(full.note_criteria)
    through = [p for p, t in full.traces.items() if t.in_scope and t.exit_stage != "S1"]
    assert through
    for p in through:
        a = {c: o.status for c, o in full.traces[p].outcomes.items() if c in note_ids}
        b = {c: o.status for c, o in only.traces[p].outcomes.items() if c in note_ids}
        assert a == b, p
