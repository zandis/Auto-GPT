"""The investigation ledger (bench/invest): byte-identical coded rows, row counts that reconcile with the candidate
list, and an exporter that refuses a planted patient id, quote and day-level date. Synthetic traces only."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from matching.cascade import CascadeResult
from matching.cascade.model import CascadeMetrics, Outcome, PatientTrace, StageLog
from tb_common.ruleset import Ruleset

from bench.invest import export, ledger, match_adapter, trial_adapter

ROOT = Path(__file__).resolve().parents[2]
SNAP = "2026-10-04"


def _ruleset() -> Ruleset:
    return Ruleset.load(ROOT / "rulesets" / "GZQO")


def _result(rs: Ruleset, n: int = 40) -> CascadeResult:
    """n patients: every 10th out of scope, the rest with one outcome per criterion (alternating verdicts)."""
    crits = [c for c in rs.active() if c.kind in ("inclusion", "exclusion")]
    traces: dict[str, PatientTrace] = {}
    for i in range(n):
        pid = f"P{i:05d}"
        t = PatientTrace(pid=pid, index_date=date(2026, 1, 31), in_scope=i % 10 != 0)
        t.scope_reason = "" if t.in_scope else "no encounter in the lookback"
        if t.in_scope:
            for j, c in enumerate(crits):
                status = ("pass", "fail", "unknown")[(i + j) % 3]
                t.outcomes[c.id] = Outcome(
                    c.id,
                    status,  # type: ignore[arg-type]
                    "S1",
                    unknown_kind="data_gap" if status == "unknown" else None,
                    evidence=[{"source": "lake", "record": f"Condition/{i}-{j}"}],
                )
            t.tier = "strong" if i % 4 == 0 else "potential:data_gap"
        traces[pid] = t
    final = [p for p, t in traces.items() if t.tier == "strong"][:5]
    stages = [StageLog("S0", n, n, 0, 0, "D3", "x")]
    return CascadeResult(
        study_id=rs.id,
        ruleset=rs.id,
        ruleset_version=rs.version,
        semantics="affirmative",
        ir_hash="sha256:ir",
        criterion_hashes={c.id: f"sha256:{c.id}" for c in crits},
        index_dates=[date(2026, 1, 31)],
        traces=traces,
        stages=stages,
        metrics=CascadeMetrics(),
        queue=[],
        final_list=final,
        applied=[c.id for c in crits],
        note_criteria=[],
        human_criteria=[],
    )


def _write(root: Path, rs: Ruleset, res: CascadeResult) -> tuple[Path, dict[str, Any], str]:
    header = {"code_sha": "c0de", "lake_snapshot_sha": ledger.sha_of_text(SNAP), "sets_json": {"synthetic": [rs.id]}}
    rid = ledger.run_id_of(header)
    w = ledger.LedgerWriter(root, rid, header)
    match_adapter.add_cascade(w, rs, res, lake_snapshot=SNAP, pid_salt="s")
    return w.dir, w.close(clock={"written": "now"}), rid


def test_second_identical_run_is_byte_identical_and_rows_reconcile(tmp_path: Path) -> None:
    rs, res = _ruleset(), None
    res = _result(rs)
    d1, m1, rid1 = _write(tmp_path / "a", rs, res)
    d2, m2, rid2 = _write(tmp_path / "b", rs, _result(rs))
    assert rid1 == rid2
    assert m1 == m2  # every file's sha256 and row count
    for rel in m1["files"]:
        assert (d1 / rel).read_bytes() == (d2 / rel).read_bytes()
    con = ledger.connect(tmp_path / "a", rid1)
    assert match_adapter.reconcile(con, res, rs) == []
    n_crit = len([c for c in rs.active() if c.kind in ("inclusion", "exclusion")])
    n_scope = len(res.in_scope())
    assert con.execute("select count(*) from match_stage").fetchone()[0] == 40 * 2 + n_scope * n_crit


def test_reconcile_names_a_row_count_that_does_not_match(tmp_path: Path) -> None:
    rs = _ruleset()
    res = _result(rs)
    _d, _m, rid = _write(tmp_path, rs, res)
    res.traces.pop("P00001")  # the candidate list now has one patient the ledger holds twice
    bad = match_adapter.reconcile(ledger.connect(tmp_path, rid), res, rs)
    assert any(m.startswith("S0 rows") for m in bad) and any(m.startswith("tier rows") for m in bad)


def test_pids_are_pseudonymised_and_the_row_key_is_the_row_content(tmp_path: Path) -> None:
    rs = _ruleset()
    _d, _m, rid = _write(tmp_path, rs, _result(rs))
    con = ledger.connect(tmp_path, rid)
    assert not [p for p in export.pids_of(con) if p.startswith("P0")]
    assert con.execute("select count(distinct row_key) = count(*) from match_stage").fetchone()[0]


def _agg(tmp_path: Path) -> tuple[dict[str, list[dict[str, Any]]], set[str], set[str]]:
    rs = _ruleset()
    _d, _m, rid = _write(tmp_path, rs, _result(rs, 400))
    con = ledger.connect(tmp_path, rid)
    known = {rs.id} | {c.id for c in rs.active()}
    return export.ledger_agg(con), export.pids_of(con), known


def test_the_exporter_writes_a_clean_table_with_small_cells_suppressed(tmp_path: Path) -> None:
    agg, pids, known = _agg(tmp_path)
    assert all(r["n"] is None or r["n"] >= export.MIN_CELL for r in agg["stage_verdict"])
    out = export.write_agg(tmp_path / "agg.json", agg, pids, known)
    assert json.loads(out.read_text("utf-8"))["stage_verdict"]


@pytest.mark.parametrize(
    "planted",
    [
        pytest.param("pid", id="a_patient_id"),
        pytest.param("quote", id="a_quote"),
        pytest.param("date", id="a_day_level_date"),
        pytest.param("small", id="an_unsuppressed_small_count"),
    ],
)
def test_the_exporter_refuses_what_must_not_leave(tmp_path: Path, planted: str) -> None:
    agg, pids, known = _agg(tmp_path)
    row = agg["family_reason"][0]
    if planted == "pid":
        row["reason_code"] = sorted(pids)[0]
    elif planted == "quote":
        row["reason_code"] = "the patient reports daily ankle pain since last March"
    elif planted == "date":
        row["reason_code"] = "2026-03-14"
    else:
        row["n"] = 3
    target = tmp_path / "leak.json"
    with pytest.raises(export.Refused):
        export.write_agg(target, agg, pids, known)
    assert not target.exists()


def test_a_pid_inside_an_identifier_is_refused() -> None:
    agg = {"data_gap": [{"protocol_id": "GZQO-p-0123456789abcdef", "reason_code": "data_gap", "n": 12}]}
    with pytest.raises(export.Refused):
        export.refuse(agg, {"p-0123456789abcdef"}, {"GZQO-p-0123456789abcdef"})


def test_trial_rows_are_keyed_by_line_and_stage_and_reject_an_unknown_status(tmp_path: Path) -> None:
    w = ledger.LedgerWriter(tmp_path, "run-t", {"code_sha": "c0de"})
    lines = [{"nct": "NCT00000001", "line": 1, "side": "inclusion", "text": "Age 18 or older"}]
    props = [{**lines[0], "proposal": {"cards": [{"card": "F01.age", "params": {}}], "coverage": "full"}}]
    assert trial_adapter.add_records(w, "split", lines) == 1
    assert trial_adapter.add_records(w, "card_proposal", props, gold={"NCT00000001:1": {"card": "F01.age"}}) == 1
    with pytest.raises(ValueError, match="status"):
        trial_adapter.add_records(w, "compile_sql", [{**lines[0], "status": "weird"}])
    w.close()
    con = ledger.connect(tmp_path, "run-t")
    rows = con.execute("select stage, status, gold is not null from trial_stage order by stage").fetchall()
    assert rows == [("card_proposal", "ok", True), ("split", "ok", False)]


def test_ddl_lists_every_ledger_column() -> None:
    sql = ledger.ddl_sql()
    for table, cols in {**ledger.TABLES, "run": ledger.RUN_COLS}.items():
        assert f"CREATE TABLE {table} (" in sql
        assert all(f"  {n} " in sql for n, _ in cols)


def test_every_stored_row_key_is_the_hash_of_its_row(tmp_path: Path) -> None:
    rs = _ruleset()
    _d, _m, rid = _write(tmp_path, rs, _result(rs))
    rows = ledger.connect(tmp_path, rid).execute("select * from match_stage").to_arrow_table().to_pylist()
    assert rows
    assert all(r["row_key"] == ledger.row_key_of(r) for r in rows)


@pytest.mark.parametrize("table", ["Patient-Jane-Doe", "P00001", "data_gap2"])
def test_the_exporter_refuses_a_table_name_that_is_not_one_of_ours(tmp_path: Path, table: str) -> None:
    for rows in ([{"n": 12}], []):  # an empty table is exported by name too
        target = tmp_path / "leak.json"
        with pytest.raises(export.Refused, match="aggregate table"):
            export.write_agg(target, {table: rows}, {"P00001"}, set())
        assert not target.exists()


def test_each_planted_leak_is_refused_by_its_own_check() -> None:
    """The value is a permitted identifier (known, a valid reason code) except for the one thing planted."""
    pid = "p-0123456789abcdef"
    cases = {
        "a_patient_id": (pid, "a patient id"),
        "a_day_level_date": ("GZQO-2026-03-14", "day-level date"),
        "a_quote": ("the patient reports pain", "closed identifier"),
    }
    for protocol_id, why in cases.values():
        agg = {"data_gap": [{"protocol_id": protocol_id, "reason_code": "data_gap", "n": 12}]}
        with pytest.raises(export.Refused, match=why):
            export.refuse(agg, {pid}, {protocol_id})
    clean = {"data_gap": [{"protocol_id": "GZQO", "reason_code": "data_gap", "n": 12}]}
    export.refuse(clean, {pid}, {"GZQO"})


def test_a_rewrite_with_fewer_partitions_leaves_no_old_partition(tmp_path: Path) -> None:
    def run(parts: list[str]) -> ledger.LedgerWriter:
        w = ledger.LedgerWriter(tmp_path, "run-x", {"code_sha": "c0de"})
        for part in parts:
            w.add("match_stage", part, {"pid": "p-1", "protocol_id": part, "criterion_id": "C1", "stage": "S1"})
        return w

    run(["A", "B"]).close()
    run(["A"]).close()
    names = sorted(p.parent.name for p in (tmp_path / "run-x").glob("match_stage/*/*.parquet"))
    assert names == ["protocol=A"]
    got = ledger.connect(tmp_path, "run-x").execute("select protocol_id from match_stage").fetchall()
    assert got == [("A",)]
    assert [p.name for p in tmp_path.iterdir()] == ["run-x"]  # no staging or trash left behind


def test_an_interrupted_rewrite_leaves_the_earlier_run_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def run(parts: list[str]) -> ledger.LedgerWriter:
        w = ledger.LedgerWriter(tmp_path, "run-x", {"code_sha": "c0de"})
        for part in parts:
            w.add("match_stage", part, {"pid": "p-1", "protocol_id": part, "criterion_id": "C1", "stage": "S1"})
        return w

    first = run(["A", "B"]).close()
    real, calls = ledger._write_parquet, []

    def dies_on_the_second_file(*a: Any) -> None:
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        real(*a)

    monkeypatch.setattr(ledger, "_write_parquet", dies_on_the_second_file)
    with pytest.raises(OSError):
        run(["C", "D"]).close()
    monkeypatch.undo()
    assert json.loads((tmp_path / "run-x" / "MANIFEST.json").read_text("utf-8")) == first
    got = ledger.connect(tmp_path, "run-x").execute("select protocol_id from match_stage order by 1").fetchall()
    assert got == [("A",), ("B",)]


def test_a_file_the_manifest_does_not_list_is_not_read(tmp_path: Path) -> None:
    w = ledger.LedgerWriter(tmp_path, "run-y", {"code_sha": "c0de"})
    w.add("match_stage", "Z", {"pid": "p-1", "protocol_id": "Z", "criterion_id": "C1", "stage": "S1"})
    w.close()
    good = tmp_path / "run-y" / "match_stage" / "protocol=Z" / "part-0.parquet"
    good.with_name("part-9.parquet").write_bytes(good.read_bytes())
    assert ledger.connect(tmp_path, "run-y").execute("select count(*) from match_stage").fetchone()[0] == 1


def test_the_criterion_input_hash_changes_with_the_lake_snapshot(tmp_path: Path) -> None:
    rs, res = _ruleset(), None
    res = _result(rs)

    def hashes(snap: str) -> set[str]:
        w = ledger.LedgerWriter(tmp_path / snap, "r", {"code_sha": "c0de"})
        match_adapter.add_cascade(w, rs, res, lake_snapshot=snap, pid_salt="s")
        w.close()
        rows = ledger.connect(tmp_path / snap, "r").execute("select inputs_hash from match_stage").fetchall()
        return {r[0] for r in rows}

    assert hashes("2026-10-04").isdisjoint(hashes("2026-10-05"))  # criterion rows, the not-evaluated ones, S0, tier


def test_the_run_id_changes_with_the_time_zone_and_the_run_date(tmp_path: Path) -> None:
    from bench.invest import dry_run

    rs = _ruleset()
    res = _result(rs)

    def rid(tz: str, run_date: str) -> str:
        return dry_run.write_ledger(tmp_path, {rs.id: rs}, {rs.id: res}, SNAP, tz=tz, run_date=run_date)[2]

    assert rid("UTC", "2026-10-05") == rid("UTC", "2026-10-05")
    assert len({rid("UTC", "2026-10-05"), rid("Asia/Tokyo", "2026-10-05"), rid("UTC", "2026-10-06")}) == 3
