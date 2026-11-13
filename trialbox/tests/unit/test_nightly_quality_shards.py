"""The nightly branch coverage runs in the gate's shards and inside a limit it can meet (deep review `architecture`).

Both scheduled runs of `branch-coverage` (2026-11-11, 2026-11-12) were cancelled at the job's 60-minute limit: the
whole unit suite on one runner, under the classic tracer that measures branches. The ratchet step never ran, so the
branch baseline was never checked. The random-order run had the same fault and was moved to the gate's shards (D-560,
`test_nightly_green.py`); this holds branch coverage to the same rule, with a limit scaled by the tracer's measured
cost, and a job that combines the shards before the ratchet and turns red when a shard did not pass."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT.parent / ".github" / "workflows"
QUALITY = WORKFLOWS / "trialbox-nightly-quality.yml"
GATE = WORKFLOWS / "trialbox-ci.yml"

#: how much longer the classic tracer with branches takes than the gate's line tracer (sys.monitoring): 40.6 s
#: against 17.8 s for tests/unit/test_safety_properties.py, test_dates.py, test_labvalue.py and test_encoding.py on a
#: 4-core machine, 2026-11-13. CPU-bound tests are the worst case; a test that waits on PostgreSQL pays less.
BRANCH_TRACER_FACTOR = 2.2

pytestmark = pytest.mark.nodb


def _jobs(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    jobs = doc["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _runs(job: dict[str, Any]) -> list[str]:
    return [str(s.get("run", "")) for s in job["steps"]]


def check_shards(quality: dict[str, Any], gate: dict[str, Any]) -> None:
    """One job per shard of the gate's `unit-shard`, each running its own shard with branches measured."""
    job = quality["branch-coverage"]
    shard = gate["unit-shard"]
    assert job.get("strategy", {}).get("matrix", {}).get("shard") == shard["strategy"]["matrix"]["shard"]
    assert job["strategy"]["fail-fast"] is False
    run = next(r for r in _runs(job) if "make test " in r)
    assert "SHARD=${{ matrix.shard }}/${{ strategy.job-total }}" in run
    env = next(s.get("env", {}) for s in job["steps"] if "make test " in str(s.get("run", "")))
    assert "--cov-branch" in env["PYTEST_ADDOPTS"]


def check_limit(quality: dict[str, Any], gate: dict[str, Any]) -> None:
    """A shard's limit is at least the gate shard's limit times the tracer's measured cost."""
    need = math.ceil(gate["unit-shard"]["timeout-minutes"] * BRANCH_TRACER_FACTOR)
    assert quality["branch-coverage"]["timeout-minutes"] >= need


def check_ratchet(quality: dict[str, Any]) -> None:
    """The ratchet runs once, on the combined data of every shard, and fails when a shard did not pass."""
    assert not any("coverage_ratchet" in r for r in _runs(quality["branch-coverage"]))
    job = quality["branch-coverage-ratchet"]
    assert job["needs"] == "branch-coverage" or "branch-coverage" in job["needs"]
    assert "!cancelled()" in str(job.get("if", ""))
    runs = "\n".join(_runs(job))
    assert 'needs.branch-coverage.result }}" != "success"' in runs
    assert runs.index("coverage combine") < runs.index("coverage_ratchet")


def test_the_branch_coverage_runs_in_the_gates_shards() -> None:
    check_shards(_jobs(QUALITY), _jobs(GATE))


def test_a_branch_coverage_shard_has_a_limit_it_can_meet() -> None:
    check_limit(_jobs(QUALITY), _jobs(GATE))


def test_the_ratchet_reads_every_shard_and_a_failed_shard_is_red() -> None:
    check_ratchet(_jobs(QUALITY))
