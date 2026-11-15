"""The product-on-GPU run's VM script (deploy/gcp/box-install-run.sh; gap X-10, tests G-2, G-9, G-10 of plan v7 §7.1).

Each test runs one case of the local rehearsal (tests/rehearsal/box-run/rehearse-box-run.sh): the real VM script,
unchanged, against stand-ins for the cloud, systemd, docker and lane D's installer, wizard and qualification path. No
network, no GCP call, no container, no root: seconds per case on the script's short clock.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VM_SCRIPT = ROOT / "deploy" / "gcp" / "box-install-run.sh"
BOX_RUN = ROOT / "tests" / "rehearsal" / "box-run"
RUNNER = BOX_RUN / "rehearse-box-run.sh"
SHELL_FILES = [VM_SCRIPT, RUNNER, *sorted((BOX_RUN / "shims").iterdir()), *sorted((BOX_RUN / "standins").glob("*.sh"))]
CASES = ["happy", "step-fails", "reboot", "cap", "bad-hash", "bad-tar-hash", "paid-twice"]

pytestmark = pytest.mark.skipif(
    any(shutil.which(c) is None for c in ("bash", "curl", "openssl", "setsid", "tar")),
    reason="the box-run rehearsal needs bash, curl, openssl, setsid and tar",
)


@pytest.mark.parametrize("case", CASES)
def test_rehearsal_case(case: str, tmp_path: Path) -> None:
    env = {**os.environ, "TB_BOXRUN_REHEARSAL_DIR": str(tmp_path)}
    run = subprocess.run([str(RUNNER), case], env=env, capture_output=True, text=True, check=False)
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert f"check {case}: passed" in out, out
    assert "  FAIL " not in out, out


@pytest.mark.parametrize("path", SHELL_FILES, ids=lambda p: p.name)
def test_shell_syntax(path: Path) -> None:
    run = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr


def test_vm_script_makes_no_cloud_call_that_costs() -> None:
    """On the VM, gcloud only reads the two secrets and copies to or from the bucket; it never touches a VM."""
    text = "\n".join(line for line in VM_SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#"))
    calls = re.findall(r"\bgcloud\s+(\w+)\s+(\w+)", text)
    assert calls, "the script reads its door from Secret Manager"
    assert set(calls) <= {("secrets", "versions"), ("storage", "cp")}, calls
    assert "set -x" not in text  # nothing prints a key


def test_every_lane_d_call_is_one_function() -> None:
    """The installer, the wizard and the box's tools are called only inside the d_* functions (the assumed interface)."""
    code = [line for line in VM_SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")]
    # a call: the installer followed by an argument (not the `[ -x "$INSTALLER" ]` test), or box_tool with a module
    call = re.compile(r'"\$INSTALLER" [^\]]|\bbox_tool \w')
    outside = [line for line in code if call.search(line) and not re.match(r"\s*d_\w+\(\)", line)]
    assert not outside, outside
    functions = [line for line in code if re.match(r"\s*d_\w+\(\)", line)]
    assert len(functions) == 11, functions  # the interface listed in the script's header
