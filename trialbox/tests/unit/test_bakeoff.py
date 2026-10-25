"""Bake-off as code (spec v4 §8.10, LLM-33; S1-14).

Done-criterion (MS0): ``--dry-run`` prints the plan and a cost estimate, and a D1 payload on ``bakeoff`` is refused.
The OpenRouter candidates are refused too, because no build is pinned (expected in MS0). No network: the dry run's
gateway has a transport that raises on any dispatch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import bakeoff
from tools.mlbench_tasks import load_tasks

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.req("S1-14", "LLM-33")
def test_dry_run_prints_plan_cost_and_refusals(capsys: pytest.CaptureFixture[str]) -> None:
    assert bakeoff.main(["--dry-run", "--n", "20", "--usd-per-1k", "0.2", "0.8"]) == 0
    out = capsys.readouterr().out
    assert "bake-off plan" in out and "role judge: task judge_ml via gateway role bakeoff" in out
    assert "20 items x 4 langs (en zh-TW ja mixed) x 3 seeds" in out
    assert "cost estimate $" in out and "cap $25.00" in out
    assert "REFUSED  j-workhorse@openrouter (D0)" in out and "build_unpinned" in out
    assert "REFUSED  bakeoff D1 payload" in out and "class_not_allowed_in_env" in out
    assert "ALLOWED  stub (TEST, dev-stub)" in out
    assert "no result is recorded before a live run" in out


@pytest.mark.req("S1-14", "LLM-33")
def test_preflight_never_dispatches_and_refuses_d1(tmp_path: Path) -> None:
    probes = {p.name: p for p in bakeoff.preflight(tmp_path)}
    for name in ("j-workhorse@openrouter (D0)", "v-verifier@openrouter (D0)"):
        assert not probes[name].allowed and probes[name].code == "build_unpinned"  # refused before any dispatch
    assert not probes["bakeoff D1 payload"].allowed
    assert probes["stub (TEST, dev-stub)"].allowed
    audit = [
        json.loads(x) for f in sorted((tmp_path / "audit_dev").glob("*.jsonl")) for x in f.read_text().splitlines()
    ]
    assert [r["event"] for r in audit] == ["llm.gateway.refuse"] * 3  # every DEV probe was refused and audited


@pytest.mark.req("S1-14")
def test_plan_uses_registry_candidates_and_cost_cap() -> None:
    p = bakeoff.plan(n=10, langs=["en"], prices=(1.0, 1.0))
    role = p["roles"][0]
    builds = {c["build_id"] for c in role["candidates"]}
    assert {"nemotron-3-nano-candidate", "qwen3.5-35b-a3b-candidate"} <= builds
    assert all(c["endpoint"] == "openrouter" and not c["pinned"] for c in role["candidates"])
    c0 = role["candidates"][0]
    assert c0["calls"] == 10 * 1 * 3 and c0["tokens_out"] == 30 * 80 and c0["cost_usd"] > 0
    assert p["cost_estimate_usd"] == pytest.approx(sum(c["cost_usd"] for c in role["candidates"]), abs=1e-3)
    assert p["within_cap"] is (p["cost_estimate_usd"] <= p["cost_cap_usd"])
    assert role["floors"]["zh-TW"] == 0.82 and role["data_class"] == "D0"


@pytest.mark.req("S1-14")
def test_live_run_is_refused_without_key_and_pinned_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert bakeoff.main(["--live", "--n", "5"]) == 2
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-not-a-key")
    monkeypatch.setenv("TB_GATEWAY_URL", "http://gateway.invalid/v1")
    assert bakeoff.main(["--live", "--n", "5"]) == 3  # no candidate is routable: nothing is pinned


def test_tasks_load() -> None:
    t = load_tasks()["judge_ml"]
    assert t.gateway_role == "bakeoff" and t.data_class == "D0" and t.langs == ("en", "zh-TW", "ja", "mixed")
