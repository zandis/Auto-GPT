"""CI-GATES (D-725): every check the owner requires on master is a job with a plain name that always reports.

A matrix job's name is an expression (``goldens`` and ``goldens (omop)``). When the ``changes`` job skips it, GitHub
never expands the expression and reports the check as ``matrix.lake_source == 'legacy' && 'goldens' || ...``: a
required check named ``goldens`` then never reports, and every pull request the filter skips waits for ever (read
from the check runs of #381, #545 and #551, 2026-11-13). One gate job per matrix pair runs always, under a plain
name, and passes when its matrix passed or was skipped."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml"
#: what the owner requires on master once this is on master (the integrator tells him)
REQUIRED = ("goldens-gate", "e2e-simple-gate", "property", "security")
GATES = {"goldens-gate": "goldens", "e2e-simple-gate": "e2e-simple"}

pytestmark = pytest.mark.nodb


def _jobs() -> dict[str, Any]:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return dict(doc["jobs"])


@pytest.mark.parametrize("name", REQUIRED)
def test_every_required_check_is_a_job_with_a_plain_name(name: str) -> None:
    job = _jobs()[name]
    shown = str(job.get("name", name))
    assert shown == name and "${{" not in shown  # the check reports under exactly this name, run or skipped
    assert "matrix" not in job.get("strategy", {})


@pytest.mark.parametrize(("gate", "leg"), sorted(GATES.items()))
def test_a_gate_always_runs_after_its_matrix_and_the_changes_job(gate: str, leg: str) -> None:
    job = _jobs()[gate]
    assert job["if"] == "always()"
    assert set(job["needs"]) == {"changes", leg}
    assert "matrix" in _jobs()[leg]["strategy"]  # the leg it stands for is the matrix pair
    assert job["defaults"]["run"]["working-directory"] == "."  # it checks nothing out: no trialbox/ folder
    assert "uses" not in str(job["steps"])  # no action, no checkout: nothing to pin, seconds of a runner


def _gate_script(gate: str) -> tuple[str, dict[str, str]]:
    (step,) = _jobs()[gate]["steps"]
    return str(step["run"]), dict(step["env"])


@pytest.mark.parametrize("gate", sorted(GATES))
@pytest.mark.parametrize(
    ("changes", "leg", "ok"),
    [
        ("success", "success", True),
        ("success", "skipped", True),  # the changes job said this pull request needs no full tier
        ("success", "failure", False),  # one leg of the pair failed
        ("success", "cancelled", False),
        ("failure", "skipped", False),  # the leg was skipped because the changes job failed: not a pass
        ("cancelled", "skipped", False),
        ("skipped", "skipped", False),
    ],
)
def test_the_gate_passes_only_when_its_matrix_passed_or_was_rightly_skipped(
    gate: str, changes: str, leg: str, ok: bool, tmp_path: Path
) -> None:
    script, env = _gate_script(gate)
    assert set(env) == {"CHANGES", "RESULT"}
    assert env["CHANGES"] == "${{ needs.changes.result }}" and env["RESULT"] == f"${{{{ needs.{GATES[gate]}.result }}}}"
    r = subprocess.run(["bash", "-e", "-c", script], env={"CHANGES": changes, "RESULT": leg, "PATH": "/usr/bin:/bin"},
                       capture_output=True, text=True, cwd=tmp_path, check=False)  # fmt: skip
    assert (r.returncode == 0) is ok, r.stdout + r.stderr
    assert GATES[gate] in r.stdout + r.stderr and leg in r.stdout + r.stderr  # it says what it saw


def test_the_workflow_and_the_runbook_name_the_checks_the_owner_requires() -> None:
    head = CI.read_text(encoding="utf-8").split("\njobs:", 1)[0]
    runbook = (ROOT / "docs" / "runbook" / "03-accounts.md").read_text(encoding="utf-8")
    for name in REQUIRED:
        assert name in head, name
        assert f"`{name}`" in runbook, name
