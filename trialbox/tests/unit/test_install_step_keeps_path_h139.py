"""H-139 (the integrator's 7163415503, item 2): the install steps of the runbook test keep every host folder on PATH.

H139-12 kept the bench host's graphics card out of these steps by dropping each PATH folder that holds
``nvidia-smi``. On a GPU host that folder is ``/usr/bin``, beside ``bash``, so the step could not start
``bash`` (FileNotFoundError: 'bash', three cases on the bench). Here a host PATH is laid out the same way: its one
``bash`` sits beside an ``nvidia-smi`` that reports a card. The step must run, and must not see that card.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.unit.test_runbook_install_commands import _install_to_the_host_step

pytestmark = pytest.mark.nodb


def test_on_a_gpu_host_the_install_step_still_finds_bash_and_never_the_hosts_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bash = shutil.which("bash")
    assert bash, "the runbook steps need bash"
    holds_bash = {
        os.path.realpath(d) for d in os.environ["PATH"].split(os.pathsep) if d and (Path(d) / "bash").exists()
    }
    gpu_host = tmp_path / "gpu-host-bin"  # the bench host's /usr/bin: bash, the rest, and the card's tool
    gpu_host.mkdir()
    for d in holds_bash:
        for entry in os.scandir(d):
            if not (gpu_host / entry.name).exists():
                (gpu_host / entry.name).symlink_to(entry.path)
    card = gpu_host / "nvidia-smi"
    card.unlink(missing_ok=True)
    seen = tmp_path / "host-card-was-asked"
    card.write_text(f"#!/bin/sh\ntouch {seen}\necho 'NVIDIA GeForce GT 1030'\n", encoding="utf-8")
    card.chmod(0o755)
    rest = [d for d in os.environ["PATH"].split(os.pathsep) if d and os.path.realpath(d) not in holds_bash]
    monkeypatch.setenv("PATH", os.pathsep.join([str(gpu_host), *rest]))
    out = _install_to_the_host_step(tmp_path / "step", "--mode", "stub")  # its own checks: the host step reached
    assert "==> host" in out.stdout
    assert not seen.exists(), "the step asked the host's card"
