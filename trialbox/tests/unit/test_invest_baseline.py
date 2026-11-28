"""The round-1 baseline runner (bench/invest/baseline): the repeat row tells identical coded rows from changed ones
and counts model verdicts that differ; a frozen-bench note set becomes one S3 row per case. Synthetic rows only."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest

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


def test_a_public_model_host_is_refused_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_send(*a: Any, **k: Any) -> Any:
        raise AssertionError("a request was made")

    monkeypatch.setattr(httpx.Client, "send", no_send)
    for other in ("http://8.8.8.8:8000", "http://10.255.255.1:8000"):  # public; private but another machine
        with pytest.raises(ValueError, match="not an address of this machine"):
            baseline._client(f"http://127.0.0.1:1,{other}", "m")
    baseline._client("http://127.0.0.1:1", "m")


def test_requests_are_counted_by_server_ordinal_never_by_address(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, **kw: seen.append(str(url)))
    c = baseline._client("http://user:pass@127.0.0.1:1,http://127.0.0.1:2", "m")
    assert c.http.trust_env is False
    for _ in range(3):
        c.http.post("http://user:pass@127.0.0.1:1/chat/completions", json={})
    shown = json.dumps(dict(c.http.posts))
    assert json.loads(shown) == {"server 1": 2, "server 2": 1}
    assert "user" not in shown and "pass" not in shown
    assert seen[1].startswith("http://127.0.0.1:2/")


def test_salt_is_created_private_once_and_an_existing_one_is_kept_and_tightened(tmp_path: Path) -> None:
    fresh = tmp_path / "sub" / "salt"
    value = baseline._salt(fresh)
    assert len(value) == 32 and stat.S_IMODE(fresh.stat().st_mode) == 0o600
    assert baseline._salt(fresh) == value  # never replaced
    old = tmp_path / "old"
    old.write_text("kept-salt\n", encoding="utf-8")
    old.chmod(0o644)
    assert baseline._salt(old) == "kept-salt"
    assert stat.S_IMODE(old.stat().st_mode) == 0o600


def test_aggregate_is_published_only_after_reconciliation_succeeded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    agg = tmp_path / "agg.json"
    baseline._publish(agg, {}, set(), set(), ["GZQO: x"])
    assert not agg.exists() and capsys.readouterr().out.count("WARN") == 1
    assert (tmp_path / "agg.json.DRAFT-reconcile-mismatch").exists()
    baseline._publish(agg, {}, set(), set(), [])
    assert agg.exists()
