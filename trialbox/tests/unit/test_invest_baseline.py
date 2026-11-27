"""The round-1 baseline runner (bench/invest/baseline): the repeat row tells identical coded rows from changed ones
and counts model verdicts that differ; a frozen-bench note set becomes one S3 row per case. Synthetic rows only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bench.invest import baseline, ledger


def _run(root: Path, name: str, coded_verdict: str, model_verdict: str) -> Path:
    w = ledger.LedgerWriter(root, name, {"code_sha": name})
    for i in range(3):
        base: dict[str, Any] = {"pid": f"p-{i}", "protocol_id": "GZQO", "criterion_id": "C1", "attempt": 0}
        w.add("match_stage", "GZQO", {**base, "stage": "S1", "verdict": coded_verdict if i == 0 else "T"})
        w.add("match_stage", "GZQO", {**base, "criterion_id": "C2", "stage": "S3", "verdict": "T"})
        w.add("match_stage", "GZQO", {**base, "criterion_id": "C2", "stage": "S4", "verdict": model_verdict})
        w.add("match_stage", "GZQO", {**base, "criterion_id": None, "stage": "tier", "final": model_verdict == "T"})
    w.close()
    return root / name


def test_repeat_same_rows_are_identical_whatever_the_run_id(tmp_path: Path) -> None:
    got = baseline.compare(_run(tmp_path, "run-a", "F", "T"), _run(tmp_path, "run-b", "F", "T"))
    assert got["coded_identical"] is True
    assert (got["coded_rows"], got["model_criteria"], got["model_differ"], got["final_differ"]) == (3, 3, 0, 0)


def test_repeat_counts_a_changed_coded_row_and_the_last_model_stage(tmp_path: Path) -> None:
    got = baseline.compare(_run(tmp_path, "run-a", "F", "T"), _run(tmp_path, "run-b", "U", "U"))
    assert got["coded_identical"] is False
    assert (got["coded_only_a"], got["coded_only_b"]) == (1, 1)
    # the S4 verdict decides (S3 is T in both runs), so every model criterion differs, and every final membership
    assert (got["model_differ"], got["model_differ_pct"], got["final_differ"]) == (3, 100.0, 3)


def test_noteset_writes_one_s3_row_per_case_with_the_gold(tmp_path: Path) -> None:
    cases = tmp_path / "cases.jsonl"
    final = tmp_path / "out" / "final.jsonl"
    final.parent.mkdir()
    rows = [{"id": "c1", "criterion_text": "x", "excerpts": [], "truth": "yes", "kind": "00_control"},
            {"id": "c2", "criterion_text": "y", "excerpts": [], "truth": "unknown", "kind": "06_conflict"}]  # fmt: skip
    cases.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    answers = [{"id": "c1", "answer": "yes", "why": "pair", "quotes": [], "pair": "yes"},
               {"id": "c2", "answer": "no", "why": "code:status", "quotes": [], "pair": "unknown"}]  # fmt: skip
    final.write_text("".join(json.dumps(r) + "\n" for r in answers), encoding="utf-8")
    out = tmp_path / "ledger"
    rc = baseline.main(["noteset", "--name", "held", "--cases", str(cases), "--final", str(final), "--out", str(out)])
    assert rc == 0
    (run_dir,) = [p for p in out.iterdir() if p.is_dir()]
    got = (
        ledger.connect(out, run_dir.name)
        .execute("SELECT criterion_id, stage, verdict, gold, basis FROM match_stage ORDER BY criterion_id")
        .fetchall()
    )
    assert got == [("c1", "S3", "T", "T", "pair"), ("c2", "S3", "F", "U", "pair")]
