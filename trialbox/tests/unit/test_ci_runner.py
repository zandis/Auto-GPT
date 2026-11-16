"""Fail-closed runner for the two nightlies (private ARM host, not enabled here).

``.github/workflows/trialbox-e2e.yml`` (TrialBox nightly) and
``.github/workflows/trialbox-nightly-quality.yml`` (TrialBox nightly quality) keep their
GitHub-hosted image unless the event is ``schedule`` or ``workflow_dispatch``, the event
repository is private, and ``vars.TB_PRIVATE_RUNNER`` is exactly ``enabled``. A public
repository, a pull request, and any other variable value stay on the hosted image.
``scale-50k`` and the two artifact-combining jobs are not in the gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT.parent / ".github" / "workflows"

pytestmark = pytest.mark.nodb

HOSTED = "ubuntu-24.04"
LABELS = ["self-hosted", "Linux", "ARM64", "trialbox"]
EXPRESSION = (
    "${{ ((github.event_name == 'schedule' || github.event_name == 'workflow_dispatch') "
    "&& github.event.repository.private == true && github.event.repository.visibility == 'private' "
    "&& vars.TB_PRIVATE_RUNNER == 'enabled') "
    '&& fromJSON(\'["self-hosted","Linux","ARM64","trialbox"]\') || \'ubuntu-24.04\' }}'
)
GATED = {
    "trialbox-e2e.yml": ("nightly", "random-order", "compose"),
    "trialbox-nightly-quality.yml": ("mutation", "branch-coverage-shard"),
}
LITERAL = {
    "trialbox-e2e.yml": {"scale-50k": "ubuntu-24.04"},
    "trialbox-nightly-quality.yml": {"mutation-score": "ubuntu-latest", "branch-coverage": "ubuntu-latest"},
}


def _doc(name: str) -> dict[Any, Any]:
    loaded: Any = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _on(doc: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the key `on` as True.
    trigger = doc.get("on", doc.get(True))
    assert isinstance(trigger, dict)
    return trigger


def _jobs(doc: dict[Any, Any]) -> dict[str, Any]:
    jobs = doc["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def select(event: str, private: object, visibility: object, variable: object) -> str | list[str]:
    """The same clauses as EXPRESSION. Missing fields are not True and not 'private'."""
    allowed = event in ("schedule", "workflow_dispatch") and private is True and visibility == "private"
    if allowed and variable == "enabled":
        return LABELS
    return HOSTED


def test_only_schedule_and_workflow_dispatch_and_the_expression_is_exact() -> None:
    for name, gated in GATED.items():
        doc = _doc(name)
        assert set(_on(doc)) == {"schedule", "workflow_dispatch"}
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "vars.TB_RUNNER" not in text
        assert "pull_request:" not in text
        jobs = _jobs(doc)
        assert set(jobs) == set(gated) | set(LITERAL[name])
        for job_name in gated:
            assert jobs[job_name]["runs-on"] == EXPRESSION
            assert isinstance(jobs[job_name]["timeout-minutes"], int)
            assert jobs[job_name]["timeout-minutes"] > 0
            assert "services" not in jobs[job_name]
            assert "container" not in jobs[job_name]
        for job_name, image in LITERAL[name].items():
            assert jobs[job_name]["runs-on"] == image
            assert "self-hosted" not in str(jobs[job_name]["runs-on"])


def test_the_matrices_and_timeouts_stay_what_master_measured() -> None:
    nightly = _jobs(_doc("trialbox-e2e.yml"))
    assert nightly["nightly"]["strategy"]["matrix"]["run"] == [
        "public-e2e",
        "backup-drill",
        "update-drill",
        "perf-5k",
        "pure",
    ]
    assert nightly["nightly"]["timeout-minutes"] == 45
    assert nightly["random-order"]["strategy"]["matrix"]["shard"] == [1, 2, 3, 4, 5, 6]
    assert nightly["random-order"]["timeout-minutes"] == 40
    assert nightly["compose"]["timeout-minutes"] == 150
    assert nightly["scale-50k"]["timeout-minutes"] == 340
    quality = _jobs(_doc("trialbox-nightly-quality.yml"))
    assert len(quality["mutation"]["strategy"]["matrix"]["include"]) == 4
    assert quality["mutation"]["timeout-minutes"] == 300
    assert quality["branch-coverage-shard"]["strategy"]["matrix"]["shard"] == list(range(1, 13))
    assert quality["branch-coverage-shard"]["timeout-minutes"] == 90
    assert quality["mutation-score"]["timeout-minutes"] == 10
    assert quality["branch-coverage"]["timeout-minutes"] == 15


@pytest.mark.parametrize(
    ("event", "private", "visibility", "variable", "want"),
    [
        ("schedule", True, "private", "enabled", LABELS),
        ("workflow_dispatch", True, "private", "enabled", LABELS),
        ("schedule", False, "public", "enabled", HOSTED),
        ("schedule", True, "public", "enabled", HOSTED),
        ("schedule", False, "private", "enabled", HOSTED),
        ("schedule", True, "private", "trialbox", HOSTED),
        ("schedule", True, "private", "", HOSTED),
        ("schedule", True, "private", None, HOSTED),
        ("schedule", True, "private", "Enabled", HOSTED),
        ("pull_request", True, "private", "enabled", HOSTED),
        ("pull_request_target", True, "private", "enabled", HOSTED),
        ("push", True, "private", "enabled", HOSTED),
        ("workflow_dispatch", None, None, "enabled", HOSTED),
        ("schedule", True, None, "enabled", HOSTED),
    ],
)
def test_the_gate_fails_closed(event: str, private: object, visibility: object, variable: object, want: object) -> None:
    assert select(event, private, visibility, variable) == want


def test_no_job_container_and_no_docker_socket_in_either_nightly() -> None:
    for name in GATED:
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "docker.sock" not in text
        for job in _jobs(_doc(name)).values():
            assert "services" not in job
            assert "container" not in job
