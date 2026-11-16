"""NIGHTLY-QUALITY (D-727): the nightly branch coverage runs in shards and one job combines them.

Runs 3, 4 and 5 of "TrialBox nightly quality" were cancelled: `branch-coverage` ran the whole unit suite with the
classic tracer in one job and was cut off by its 60-minute limit at about 11 % of the suite. These tests hold the
shape that fits: shards with the pull request's own tools, a time limit from the measurement, and one combining job
that keeps the name `branch-coverage`, runs when a shard failed too, checks that every test ran exactly once and
holds the branch ratchet."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-nightly-quality.yml"

pytestmark = pytest.mark.nodb


def _jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return jobs


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def _env(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("env", "")) for step in job.get("steps", []))


def test_no_job_runs_the_whole_suite_with_branches_alone() -> None:
    for name, job in _jobs().items():
        if "--cov-branch" in _env(job) and "make test" in _runs(job):
            assert "SHARD=" in _runs(job), f"{name} runs the whole unit suite with branches in one job"


def test_the_shards_use_the_pull_request_s_tools_and_record_what_they_ran() -> None:
    shard = _jobs()["branch-coverage-shard"]
    shards = shard["strategy"]["matrix"]["shard"]
    assert shards == list(range(1, len(shards) + 1)) and len(shards) >= 6
    assert shard["strategy"]["fail-fast"] is False
    run = _runs(shard)
    assert "SHARD=${{ matrix.shard }}/${{ strategy.job-total }}" in run and "SHARD_RECORD=" in run
    assert "--cov-branch" in _env(shard)
    assert shard["timeout-minutes"] <= 120  # a shard is measured to fit, with room (the decision record)
    uploads = [s for s in shard["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert uploads and uploads[0].get("if") == "always()"


def test_one_job_combines_them_under_the_old_name_and_holds_the_ratchet() -> None:
    jobs = _jobs()
    combine = jobs["branch-coverage"]
    assert combine["needs"] == "branch-coverage-shard" or combine["needs"] == ["branch-coverage-shard"]
    assert "!cancelled()" in str(combine.get("if", ""))  # red when a shard failed, not skipped
    run = _runs(combine)
    assert "needs.branch-coverage-shard.result" in run
    assert "tools.test_shard check" in run
    assert "coverage combine" in run and "coverage json" in run
    assert "tools.coverage_ratchet" in run
    assert "make test" not in run  # it runs no test itself


def test_the_mutation_shards_are_left_as_they_were() -> None:
    jobs = _jobs()
    assert jobs["mutation"]["timeout-minutes"] == 90  # D-973 (D-537): no job over 90 minutes; was 300
    assert jobs["mutation-score"]["needs"] == "mutation" or jobs["mutation-score"]["needs"] == ["mutation"]


def test_engine_py_runs_in_parts_and_the_score_waits_for_every_shard() -> None:
    """ENG-006: engine.py's shard ran out of its budget with 114 mutants not run (2026-11-15); its mutants are split
    in parts (tools/mutation.py --part), each mutant in one. D-973: two parts took 207 and 149 minutes, so six; the
    score job counts eight reports (six engine parts, evaluate, rules)."""
    jobs = _jobs()
    include = jobs["mutation"]["strategy"]["matrix"]["include"]
    engine = [i for i in include if "engine.py" in i["targets"]]
    assert sorted(i["targets"].split("--part ")[1] for i in engine) == [f"{k}/6" for k in range(1, 7)]
    assert len(include) == 8
    assert "-eq 8" in _runs(jobs["mutation-score"])
