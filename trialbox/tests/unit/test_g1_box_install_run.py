"""The box run's VM script (deploy/gcp/box-install-run.sh: R2's build, G-2, G-6, G-9, G-10 of plan v7 §7.1).

Each test runs one case of the local rehearsal (tests/rehearsal/box-run/rehearse-box-run.sh): the real VM script and
its helper, the real signer and verifier over the real host tree, the real deploy/box-install.sh and the console's
real first-run pages; stand-ins only for the cloud, systemd, docker and the installed box's containers (the
rehearsal's header names each and what the paid run replaces it with). No network, no GCP call, no container.
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
DRIVER = ROOT / "deploy" / "gcp" / "box-run.sh"
SHELL_FILES = [
    VM_SCRIPT,
    DRIVER,
    RUNNER,
    *sorted((BOX_RUN / "shims").iterdir()),
    *sorted((BOX_RUN / "standins").glob("*.sh")),
]
CASES = [
    "build",
    "build-gate-fails",
    "build-refused",
    "build-preempt",
    "happy",
    "step-fails",
    "reboot",
    "cap",
    "bad-hash",
    "bad-tar-hash",
    "refused-rehearsal",
    "wizard-refused",
    "oom",
    "list-differs",
    "identity-differs",
    "gate-closed",
    "gate-401",
    "gate-never",
    "acc-cut-resume",  # D-1129 (card H-14): a set that ended on its own budget, taken up by a resume with a new one
    # the owner's live session (D-1130 to D-1133)
    "session",
    "session-stop",
    "session-cut",
    "session-wide",
    "session-egress",
    "session-dev-refused",
    "session-skip",
    "session-resume",
    "session-ssh",
    "session-then-acc",
    "session-close-fails",
    "session-update-fails",
    # the re-review's round 3: findings 1 (lane D's trialbox.service) and 4 (a later boot without tb-retry)
    "session-cut-56",
    "session-unit",
    "session-unit-race",
    "session-unit-fails",
]

pytestmark = pytest.mark.skipif(
    any(shutil.which(c) is None for c in ("bash", "curl", "openssl", "setsid", "tar", "git", "make")),
    reason="the box-run rehearsal needs bash, curl, openssl, setsid, tar, git and make",
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
    """On the VM, gcloud only reads secrets (by name) and copies to or from the bucket; it never touches a VM."""
    text = "\n".join(line for line in VM_SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#"))
    calls = re.findall(r"\bgcloud\s+(\w+)\s+(\w+)", text)
    assert calls, "the script reads its door from Secret Manager"
    assert set(calls) <= {("secrets", "versions"), ("storage", "cp")}, calls
    assert "set -x" not in text  # nothing prints a key


def test_every_box_call_is_one_function() -> None:
    """The installer and the box's tools are called only inside the d_* functions (one place each to change)."""
    code = [line for line in VM_SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")]
    call = re.compile(r'"\$INSTALLER" [^\]]|\bbox_tool \w|\bin_svc \w')
    outside = [line for line in code if call.search(line) and not re.match(r"\s*(d_\w+|box_tool|in_svc)\(\)", line)]
    assert not outside, outside


def test_the_vm_script_starts_no_model_server() -> None:
    """Audit C (2026-11-14): the models are started only by the installed box's compose; no private vLLM start."""
    code = "\n".join(line for line in VM_SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#"))
    assert "vllm/vllm-openai" not in code and "vllm serve" not in code and "vllm.entrypoints" not in code
    # every other container is a one-shot tool: off the network, or the box's own python image (img_tool, whose
    # network is none unless a call names the box's own network); the token half's tokenizer runs in the judge's
    # image with python3 as its entrypoint (no server) and no network
    for line in (x for x in code.splitlines() if "docker run" in x):
        assert "docker run --rm --network none" in line or ('"$(img_py)"' in line and "IMG_NET:-none" in line), line
    assert code.count("--entrypoint") == 1 and "--entrypoint python3" in code
    assert "--chat-template" in code  # read from the running judge, never passed


def test_the_vendor_key_never_reaches_stdout_or_the_disk() -> None:
    """b05: the key is written by gcloud itself to a tmpfs file (0600), its output thrown away, removed by a trap."""
    text = VM_SCRIPT.read_text()
    sign = text[text.index("d_sign() {") : text.index("step_b_sign() {")]
    assert '--out-file="$k/vendor.key" >/dev/null 2>&1' in sign
    assert 'mktemp -d "$SHM/tbk.XXXXXX"' in sign and "trap 'shred -u" in sign and "umask 077" in sign
    assert sign.index("trap") < sign.index("secrets versions access")
    gates = text.index("run_step b04-gates"), text.index("run_step b05-sign")
    assert gates[0] < gates[1]  # the gates pass before the key is read


def test_the_rehearsal_probes_the_door_only_while_the_run_waits_for_its_power_cycle() -> None:
    """The happy case's door probe raced the VM's own power-off (2026-11-15: "the door refuses a call without the key"
    read 000, not 401, because the probe ran after the done marker, and the VM powers off tb-done-grace seconds later).
    The probe now runs at the one moment the run is known to be up: it has asked for its power cycle and waits for the
    harness to give it. No other curl call to the door runs once the done marker is written."""
    text = RUNNER.read_text()
    happy = text[text.index("    happy)") : text.index("    step-fails)")]
    order = ["TB-DOOR-UP", "asks_power", "door_probe", "power_cycle; to_the_end"]
    at = [happy.index(s) for s in order]
    assert at == sorted(at), happy
    after_done = text[text.index("collect() {") : text.index("door_probe() {")] + text[text.index("to_the_end() {") :]
    after_done = after_done[: after_done.index("\n", after_done.index("to_the_end() {"))]
    assert "curl" not in after_done and "tb-door" not in after_done, after_done
