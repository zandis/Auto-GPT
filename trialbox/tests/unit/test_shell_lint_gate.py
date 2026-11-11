"""OPS-076: shellcheck gates on warnings for every shell script, in CI and in ``make ci``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml"


def _shell_steps() -> list[str]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [str(s.get("run") or "") for s in doc["jobs"]["shell"]["steps"] if s.get("name") == "shellcheck"]


def test_ci_shell_job_gates_on_warnings() -> None:
    (run,) = _shell_steps()
    lines = [ln.strip() for ln in run.splitlines() if "shellcheck" in ln]
    assert lines, run
    for ln in lines:
        assert "--severity=warning" in ln and "|| true" not in ln, ln
        assert "--severity=error" not in ln, ln


def test_make_ci_gates_on_warnings() -> None:
    make = (ROOT / "Makefile").read_text(encoding="utf-8")
    lines = [ln for ln in make.splitlines() if "xargs -0 shellcheck" in ln]
    assert lines and all("--severity=warning" in ln and "|| true" not in ln for ln in lines), lines


def test_every_shell_script_is_clean_at_warning_level() -> None:
    """The scripts themselves (deploy/*.sh and tools/apply_update.sh among them); CI's shell job runs the same."""
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not installed here (the shell job runs it)")
    files = subprocess.run(["git", "ls-files", "*.sh"], cwd=ROOT, capture_output=True, text=True, check=True)
    names = files.stdout.split()
    assert "deploy/install.sh" in names and "tools/apply_update.sh" in names
    r = subprocess.run(["shellcheck", "--severity=warning", "--format=gcc", *names], cwd=ROOT,
                       capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode == 0, r.stdout + r.stderr
