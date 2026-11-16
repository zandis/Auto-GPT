"""D-891: the box rehearsal can be a required check. Every pull request runs the workflow; the `changes` job says
whether it touches the installer path, the two legs run only then, and `rehearse-result` (the one name a branch rule
requires) passes when the legs passed or were skipped and fails otherwise. The Maven plugin of the JVM fetch is named
with its version, so Central is never asked which version is the newest."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT.parent / ".github" / "workflows" / "trialbox-rehearse-box.yml"

pytestmark = pytest.mark.nodb


def _jobs() -> dict[str, Any]:
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _changes(tmp: Path, files: list[str], event: str = "pull_request") -> str:
    """The changes job's own script, with a stand-in `gh` that lists the pull request's files."""
    step = _jobs()["changes"]["steps"][0]
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/bin/sh\nprintf '%s\\n' " + " ".join(f"'{f}'" for f in files) + "\n", encoding="utf-8")
    gh.chmod(0o755)
    out = tmp / "out"
    env = {
        **os.environ,
        **{k: str(v) for k, v in step["env"].items() if not str(v).startswith("${{")},
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "EVENT": event,
        "PR": "1",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_OUTPUT": str(out),
    }
    r = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr
    return out.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize(
    ("files", "want"),
    [
        (["trialbox/deploy/install.sh"], "installer=true"),
        (["trialbox/tools/trialbox/doctor.py", "README.md"], "installer=true"),  # ** crosses folders
        (["trialbox/deploy/docker-compose.gb10.yml"], "installer=true"),
        (["trialbox/tools/fetch_jvm_deps.sh"], "installer=true"),
        ([".github/workflows/trialbox-rehearse-box.yml"], "installer=true"),
        (["trialbox/services/console/app.py", "trialbox/docs/runbook/01-install-a-new-site.md"], "installer=false"),
        ([], "installer=false"),
    ],
)
def test_the_changes_job_says_whether_the_installer_path_is_touched(
    tmp_path: Path, files: list[str], want: str
) -> None:
    assert _changes(tmp_path, files) == want


def test_by_hand_the_legs_always_run(tmp_path: Path) -> None:
    assert _changes(tmp_path, [], event="workflow_dispatch") == "installer=true"


def test_the_legs_run_only_on_an_installer_change() -> None:
    legs = _jobs()["rehearse"]
    assert legs["needs"] == "changes" and legs["if"] == "needs.changes.outputs.installer == 'true'"


def _result(changes: str, installer: str, legs: str) -> int:
    step = _jobs()["rehearse-result"]["steps"][0]
    env = {**os.environ, "CHANGES": changes, "INSTALLER": installer, "LEGS": legs}
    return subprocess.run(["bash", "-e", "-c", step["run"]], env=env, capture_output=True, check=False).returncode


@pytest.mark.parametrize(
    ("changes", "installer", "legs", "ok"),
    [
        ("success", "true", "success", True),
        ("success", "false", "skipped", True),  # no installer change: the required check passes at once
        ("success", "true", "failure", False),
        ("success", "true", "cancelled", False),
        ("success", "true", "skipped", False),  # an installer change whose legs did not run is never a pass
        ("success", "false", "failure", False),
        ("failure", "", "skipped", False),  # the changes job could not say
        ("cancelled", "", "skipped", False),
    ],
)
def test_the_aggregate_passes_on_pass_or_skip_only(changes: str, installer: str, legs: str, ok: bool) -> None:
    assert (_result(changes, installer, legs) == 0) is ok


def test_the_aggregate_always_runs_after_both() -> None:
    agg = _jobs()["rehearse-result"]
    assert agg["needs"] == ["changes", "rehearse"] and agg["if"] == "always()"


def test_the_maven_plugin_is_named_with_its_version() -> None:
    script = (ROOT / "tools" / "fetch_jvm_deps.sh").read_text(encoding="utf-8")
    assert 'DEP_PLUGIN="3.7.0"' in script
    assert '"org.apache.maven.plugins:maven-dependency-plugin:$DEP_PLUGIN:copy-dependencies"' in script
    assert " dependency:copy-dependencies" not in script  # the bare prefix asks Central for the newest version
