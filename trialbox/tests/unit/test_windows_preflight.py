"""D-125 / D-138 groundwork: the WSL2 pre-flight check prints plain PASS / FAIL lines and fails when a check fails.

The bash check runs here on a fake /proc and fake ``cmd.exe`` / ``nvidia-smi`` / ``df``; the PowerShell check cannot
run on Linux, so its checks are read from the file."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SH = ROOT / "deploy/windows/preflight.sh"
PS1 = ROOT / "deploy/windows/preflight.ps1"


def _fake(tmp: Path, *, kernel: str, build: str, gpu: bool, free_kb: int, mem_kb: int, pid1: str) -> dict[str, str]:
    proc = tmp / "proc"
    (proc / "sys/kernel").mkdir(parents=True)
    (proc / "1").mkdir()
    (proc / "sys/kernel/osrelease").write_text(kernel + "\n")
    (proc / "meminfo").write_text(f"MemTotal:       {mem_kb} kB\n")
    (proc / "cpuinfo").write_text("flags\t: fpu vme hypervisor\n")
    (proc / "1/comm").write_text(pid1 + "\n")
    bin_ = tmp / "bin"
    bin_.mkdir()
    stubs = {
        "cmd.exe": f"printf '\\r\\nMicrosoft Windows [Version 10.0.{build}.4317]\\r\\n'",
        "nvidia-smi": "echo 'NVIDIA RTX PRO 6000 Blackwell Workstation Edition, 581.15, 97887 MiB'"
        if gpu
        else "exit 9",
        "df": f"echo 'Filesystem 1024-blocks Used Available Capacity Mounted'; echo 'x 1 1 {free_kb} 1% /'",
    }
    for name, body in stubs.items():
        (bin_ / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_ / name).chmod(0o755)
    return {**os.environ, "PATH": f"{bin_}:/usr/bin:/bin", "TB_PREFLIGHT_PROC": str(proc)}


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SH), "/"], capture_output=True, text=True, env=env, check=False, timeout=30)


def test_a_ready_workstation_passes_every_line(tmp_path: Path) -> None:
    env = _fake(tmp_path, kernel="6.6.87.2-microsoft-standard-WSL2", build="26100", gpu=True,
                free_kb=900 * 1048576, mem_kb=96 * 1048576, pid1="systemd")  # fmt: skip
    out = _run(env)
    lines = out.stdout.splitlines()
    assert out.returncode == 0, out.stdout
    checks = ["WSL2", "Windows build", "CPU virtualisation", "GPU driver", "Disk space", "Memory", "systemd"]
    assert [ln.split(":")[0] for ln in lines[:-1]] == [f"PASS  {c}" for c in checks]
    assert "10.0.26100" in out.stdout and "RTX PRO 6000" in out.stdout and lines[-1] == "all checks passed"


def test_each_missing_piece_is_a_fail_line(tmp_path: Path) -> None:
    env = _fake(tmp_path, kernel="5.15.0-generic", build="19045", gpu=False,
                free_kb=50 * 1048576, mem_kb=8 * 1048576, pid1="init")  # fmt: skip
    out = _run(env)
    assert out.returncode == 1
    fails = [ln for ln in out.stdout.splitlines() if ln.startswith("FAIL")]
    assert {ln.split(":")[0].removeprefix("FAIL  ") for ln in fails} == {
        "WSL2", "Windows build", "GPU driver", "Disk space", "Memory", "systemd"}  # fmt: skip
    assert "check(s) FAILED" in out.stdout.splitlines()[-1]


def test_the_powershell_check_covers_the_same_ground() -> None:
    ps = PS1.read_text(encoding="utf-8")
    for what in ("Windows build", "CPU virtualisation", "WSL2", "GPU driver", "Disk space", "Memory"):
        assert f'"{what}"' in ps
    assert "Win32_OperatingSystem" in ps and "VirtualizationFirmwareEnabled" in ps and "wsl.exe" in ps
    assert "nvidia-smi.exe" in ps and "exit 1" in ps and "Invoke-WebRequest" not in ps  # offline: no download
