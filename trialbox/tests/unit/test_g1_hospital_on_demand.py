"""G1 bug A3 (D-468): a pre-empted hospital part restarts from zero.

The spot VM was pre-empted 5.5 h into G1 attempt 2, just after hospital-ja ended; two hours earlier it would have
lost the whole 5 h part (``part_hospital`` removes its work folder at start: no stage resumes). D-468 runs a VM whose
shard holds a hospital part on demand (no pre-emption; about 3x the spot price for those hours) and keeps every other
VM on spot. A resumed shard re-computes its hard cap from the parts it has left, not the launch plan's."""

from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools import complete_run as cr

ROOT = Path(__file__).resolve().parents[2]
GCP = ROOT / "deploy" / "gcp"
HEAD = "b" * 40


def _q(metric: str, limit: float, usage: float = 0) -> dict[str, Any]:
    return {"metric": metric, "limit": limit, "usage": usage}


def test_a_shard_with_a_hospital_part_runs_on_demand() -> None:
    p = cr.shard_plan(cr.estimate(50000, parts=("g1", "embed", "profile")), 4)
    for s in p["shards"]:
        hosp = any(t.startswith("hospital-") for t in s["tags"])
        assert s["provisioning"] == ("STANDARD" if hosp else "SPOT"), s
        price = cr.ON_DEMAND_PRICE_PER_HOUR if hosp else cr.PRICE_PER_HOUR
        assert s["price_per_hour"] == price and abs(s["usd"] - s["hours"] * price) < 0.02
        assert abs(s["cap_usd"] - s["cap_hours"] * price) < 0.02
    assert round(3 * cr.PRICE_PER_HOUR, 2) == cr.ON_DEMAND_PRICE_PER_HOUR  # the owner's figure: about 3x spot


def test_one_vm_with_a_hospital_part_is_on_demand_and_its_estimate_says_so() -> None:
    e = cr.restrict(cr.estimate(50000), ["hospital-ja"])
    assert e["provisioning"] == "STANDARD" and abs(e["usd"] - e["hours"] * cr.ON_DEMAND_PRICE_PER_HOUR) < 0.02
    assert "on demand" in cr.print_estimate(e)
    spot = cr.restrict(cr.estimate(50000), ["scenario-gateway"])
    assert spot["provisioning"] == "SPOT" and spot["price_per_hour"] == cr.PRICE_PER_HOUR


def _doc(only: list[str]) -> dict[str, Any]:
    e = cr.restrict(cr.estimate(50000), only)
    e["plan"] = cr.shard_plan(e, 1)
    return e


def _part(d: Path, tag: str, run_id: str, head: str = HEAD, ok: bool = True) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tag}.json").write_text(json.dumps({"stages": [{"name": "s", "ok": ok, "seconds": 1,
                                                           "checks": [["c", ok, ""]]}],
                                               "run": {"id": run_id, "head": head}}), encoding="utf-8")  # fmt: skip


def test_a_resumed_shard_recomputes_its_cap_from_the_parts_left(tmp_path: Path) -> None:
    doc = _doc(["install", "hospital-ja", "scenario-gateway", "scenario-it-dump"])
    fresh = cr.shard_now(doc, 1, [tmp_path / "parts"], "R", HEAD)
    assert fresh["cap_hours"] == doc["plan"]["shards"][0]["cap_hours"] and fresh["provisioning"] == "STANDARD"
    for tag in ("install", "prepare", "hospital-ja"):  # done before the pre-emption, in this run at this HEAD
        _part(tmp_path / "parts", tag, "R-s1")
    now = cr.shard_now(doc, 1, [tmp_path / "parts"], "R", HEAD)
    assert sorted(now["left"]) == ["scenario-gateway", "scenario-it-dump"] and now["provisioning"] == "SPOT"
    assert now["cap_hours"] == math.ceil(now["hours"] * 1.3) and now["cap_hours"] < fresh["cap_hours"]
    assert now["price_per_hour"] == cr.PRICE_PER_HOUR


def test_a_part_of_another_run_head_or_failed_is_not_done(tmp_path: Path) -> None:
    doc = _doc(["install", "hospital-ja", "scenario-gateway"])
    _part(tmp_path / "a", "hospital-ja", "OTHER-s1")
    _part(tmp_path / "b", "hospital-ja", "R-s1", head="c" * 40)
    _part(tmp_path / "c", "hospital-ja", "R-s1", ok=False)
    for d in ("a", "b", "c"):
        assert "hospital-ja" in cr.shard_now(doc, 1, [tmp_path / d], "R", HEAD)["left"]
    assert "hospital-ja" in cr.shard_now(doc, 1, [tmp_path / "x"], "R", "")["left"]  # no HEAD known: nothing done
    _part(tmp_path / "d", "hospital-ja", "R-s1")  # either folder: the shard's own results or the merged ones
    assert "hospital-ja" not in cr.shard_now(doc, 1, [tmp_path / "empty", tmp_path / "d"], "R", HEAD)["left"]


def test_on_demand_draws_on_the_regular_quota() -> None:
    project = {"quotas": [_q("GPUS_ALL_REGIONS", 4)]}
    pre_only = {"quotas": [_q("PREEMPTIBLE_NVIDIA_RTX_PRO_6000_GPUS", 2), _q("NVIDIA_RTX_PRO_6000_GPUS", 0),
                           _q("CPUS", 0), _q("PREEMPTIBLE_CPUS", 96)]}  # fmt: skip
    assert cr.quota_problems(project, {"asia-east1": pre_only}, ["asia-east1-a"]) == []
    bad = cr.quota_problems(project, {"asia-east1": pre_only}, ["asia-east1-a"], standard=["asia-east1-a"])
    assert any("on-demand" in b and "GPUs" in b for b in bad) and any("on-demand" in b and "CPUs" in b for b in bad)


def _dry(tmp_path: Path, *args: str, **env_kw: str) -> str:
    env = dict(os.environ, TB_COMPLETE_DIR=str(tmp_path / "out"), PY=str(ROOT / ".venv" / "bin" / "python"), **env_kw)
    env.pop("TB_ZONES", None)
    r = subprocess.run([str(GCP / "complete-run.sh"), "--dry-run", *args], cwd=ROOT, env=env, capture_output=True,
                       text=True, check=False, timeout=300)  # fmt: skip
    assert r.returncode == 0, r.stderr[-800:]
    return r.stdout


def test_the_driver_sets_each_vms_provisioning_model(tmp_path: Path) -> None:
    out = _dry(tmp_path, "--patients", "50000", "--vms", "3", "--zones", "asia-east1-a,us-central1-b,europe-west4-a")
    lines = [ln for ln in out.splitlines() if "set-scheduling" in ln and "max-run-duration=" in ln]
    assert len(lines) == 3, out[-2000:]
    assert sum("--provisioning-model=STANDARD" in ln for ln in lines) == 2  # the two hospital VMs
    # GCE refuses STANDARD on a preemptible VM unless --no-preemptible goes with it (G1 2026-11-12)
    assert all("--no-preemptible" in ln for ln in lines if "--provisioning-model=STANDARD" in ln)
    assert all(
        "--preemptible" in ln and "--no-preemptible" not in ln for ln in lines if "--provisioning-model=SPOT" in ln
    )
    assert sum("--provisioning-model=SPOT" in ln for ln in lines) == 1
    assert "on demand" in out


def test_the_driver_says_when_the_owner_forced_the_provisioning_model(tmp_path: Path) -> None:
    out = _dry(tmp_path, "--patients", "50000", "--only", "scenario-gateway", TB_PROVISIONING="STANDARD")
    line = next(ln for ln in out.splitlines() if ln.startswith("VM 1/"))
    assert "on demand (forced by TB_PROVISIONING)" in line and "a hospital part" not in line, line
    out = _dry(tmp_path, "--patients", "50000", "--only", "install,hospital-ja", TB_PROVISIONING="SPOT")
    line = next(ln for ln in out.splitlines() if ln.startswith("VM 1/"))
    assert "spot (forced by TB_PROVISIONING)" in line, line


def test_a_resumed_shard_gets_a_recomputed_cap(tmp_path: Path) -> None:
    only = "install,hospital-ja,scenario-gateway"
    # one call in flight, as G1 measured it (not given, the run takes the serving record's 16: test_g3_throughput_curve)
    out = _dry(tmp_path, "--patients", "50000", "--only", only, "--llm-concurrency", "1", TB_RUN_ID="R")
    assert "--max-run-duration=8h" in out and "--provisioning-model=STANDARD" in out
    o = tmp_path / "out"
    (o / "TB_HEAD.json").write_text(json.dumps({"head": HEAD}), encoding="utf-8")
    for tag in ("install", "prepare", "hospital-ja"):
        _part(o / "shard-1" / "parts", tag, "R-s1")
    again = _dry(tmp_path, "--shard", "1", TB_RUN_ID="R")
    sched = [ln for ln in again.splitlines() if "set-scheduling" in ln and "max-run-duration=" in ln]
    assert sched and "--max-run-duration=1h" in sched[0] and "--provisioning-model=SPOT" in sched[0], again[-1500:]
    assert "parts left: scenario-gateway" in again


def test_the_owner_can_force_one_provisioning_model(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setenv("TB_PROVISIONING", "spot")
    assert cr.provisioning(["hospital-zh-TW"]) == "SPOT"
    monkeypatch.setenv("TB_PROVISIONING", "STANDARD")
    assert cr.provisioning(["scenario-gateway"]) == "STANDARD"
    monkeypatch.setenv("TB_PROVISIONING", "cheap")
    with pytest.raises(ValueError):
        cr.provisioning(["embed"])
    monkeypatch.delenv("TB_PROVISIONING")
    assert cr.provisioning(["hospital-ja"]) == "STANDARD" and cr.provisioning(["embed"]) == "SPOT"
