"""D-1001: in the branch-coverage shards the per-test hang guard is twice the project's, for the tracer.

The project's pytest-timeout (``timeout = 900`` in pyproject.toml) is a hang guard: a test that runs longer has stopped
making progress. The nightly's branch-coverage shards run the same tests under the coverage tracer, which roughly
doubles a test's time. ``tests/integration/test_e2e_simple.py::test_e2e_simple`` took 816 s in shard 3 on 2026-11-17
and passed 900 s on 2026-11-18 (run 44352122514, job 134970304788): the guard fired on a test that was working, and the
shard and so the whole coverage gate went red. The shards set ``--timeout`` to twice the project's value; every other
run keeps 900 s. The job's own limit (D-537, 90 minutes) is unchanged.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-nightly-quality.yml"


def _project_timeout() -> int:
    return int(
        tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]["timeout"]
    )


def _shard_job() -> dict[str, Any]:
    job: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["branch-coverage-shard"]
    return job


def test_the_coverage_shards_double_the_hang_guard() -> None:
    step = next(s for s in _shard_job()["steps"] if "--cov" in str((s.get("env") or {}).get("PYTEST_ADDOPTS", "")))
    m = re.search(r"--timeout[ =](\d+)", step["env"]["PYTEST_ADDOPTS"])
    assert m, "the coverage shards keep the project's hang guard, which the tracer outruns"
    assert int(m.group(1)) == 2 * _project_timeout()


def test_the_job_limit_is_unchanged() -> None:
    assert _shard_job()["timeout-minutes"] == 90  # D-537


def test_no_other_run_changes_the_guard() -> None:
    assert _project_timeout() == 900
    others = [p for p in (ROOT.parent / ".github" / "workflows").glob("*.yml") if p != WORKFLOW]
    assert not [p.name for p in others if re.search(r"--timeout[ =]\d", p.read_text(encoding="utf-8"))]
