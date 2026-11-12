"""NEW-WIN-3 (D-601): ``.wslconfig`` from the hardware, and the doctor line that the compose memory caps fit WSL2's share.

The installer's arithmetic is tested with Pester (``tests/windows``); here the declared setting it shares with the
product, and ``trialbox doctor``'s ``wsl2_memory`` on a fake ``/proc``. That the models load and answer under the
share is the measurement P-12 on the reference workstation."""

from __future__ import annotations

import re
from pathlib import Path

from tb_common.config import DECLARED

from tools.trialbox.doctor import DoctorInputs, check_wsl2_memory

ROOT = Path(__file__).resolve().parents[2]
WSL2 = "6.6.87.2-microsoft-standard-WSL2"
COMPOSE = """services:
  lake:
    mem_limit: ${TB_MEM_LAKE:-16g}
  llm:
    mem_limit: ${TB_MEM_LLM:-24g}
  proxy:
    mem_limit: 512m
"""


def _box(tmp: Path, *, kernel: str, mem_gib: float, env: dict[str, str] | None = None) -> DoctorInputs:
    proc = tmp / "proc"
    (proc / "sys/kernel").mkdir(parents=True)
    (proc / "sys/kernel/osrelease").write_text(kernel + "\n")
    (proc / "meminfo").write_text(f"MemTotal:       {int(mem_gib * 1048576)} kB\nMemFree: 1 kB\n")
    deploy = tmp / "deploy"
    deploy.mkdir()
    (deploy / "docker-compose.yml").write_text(COMPOSE)
    return DoctorInputs(env=env or {}, deploy=deploy, proc=proc)


def test_the_installers_default_share_is_the_declared_setting() -> None:
    ps1 = (ROOT / "deploy/windows/box-install.ps1").read_text(encoding="utf-8")
    default = re.search(r"\[int\]\$DesktopSharePercent = (\d+)", ps1)
    assert default and default.group(1) == DECLARED["TB_WSL_DESKTOP_SHARE_PCT"].default


def test_no_memory_or_processor_figure_is_written_in_the_installer_or_the_example() -> None:
    ps1 = (ROOT / "deploy/windows/box-install.ps1").read_text(encoding="utf-8")
    assert not re.search(r"memory=\d|processors=\d", ps1)
    assert not re.search(r"(?m)^(memory|processors)=\d", (ROOT / "deploy/windows/wslconfig.example").read_text())


def test_a_plain_linux_host_has_nothing_to_fit(tmp_path: Path) -> None:
    c = check_wsl2_memory(_box(tmp_path, kernel="6.8.0-48-generic", mem_gib=8))
    assert (c.name, c.status) == ("wsl2_memory", "PASS") and "not WSL2" in c.detail


def test_caps_that_fit_wsl2s_share_pass_with_both_figures(tmp_path: Path) -> None:
    c = check_wsl2_memory(_box(tmp_path, kernel=WSL2, mem_gib=144))
    assert c.status == "PASS" and "40.5 GiB" in c.detail and "144.0 GiB" in c.detail


def test_caps_above_wsl2s_share_fail_and_name_the_largest(tmp_path: Path) -> None:
    c = check_wsl2_memory(_box(tmp_path, kernel=WSL2, mem_gib=32))
    assert c.status == "FAIL" and "TB_MEM_LLM 24.0" in c.detail and "32.0 GiB" in c.detail


def test_the_boxs_own_caps_are_the_ones_summed(tmp_path: Path) -> None:
    env = {"TB_MEM_LAKE": "4096m", "TB_MEM_LLM": "20g"}
    c = check_wsl2_memory(_box(tmp_path, kernel=WSL2, mem_gib=32, env=env))
    assert c.status == "PASS" and "24.5 GiB" in c.detail


def test_every_compose_file_of_the_box_is_summed(tmp_path: Path) -> None:
    inp = _box(tmp_path, kernel=WSL2, mem_gib=48, env={"COMPOSE_FILE": "docker-compose.yml:extra.yml"})
    assert inp.deploy is not None
    (inp.deploy / "extra.yml").write_text("services:\n  verifier:\n    mem_limit: ${TB_MEM_VERIFIER:-12g}\n")
    c = check_wsl2_memory(inp)
    assert c.status == "FAIL" and "52.5 GiB" in c.detail


def test_a_cap_that_is_not_a_size_and_an_unreadable_share_fail(tmp_path: Path) -> None:
    assert check_wsl2_memory(_box(tmp_path, kernel=WSL2, mem_gib=64, env={"TB_MEM_LAKE": "lots"})).status == "FAIL"
    inp = _box(tmp_path / "b", kernel=WSL2, mem_gib=64)
    (inp.proc / "meminfo").write_text("garbage\n")
    assert check_wsl2_memory(inp).status == "FAIL"


def test_the_real_compose_set_fits_the_share_the_box_plan_caps_it_to(tmp_path: Path) -> None:
    """tools.box plan caps the services to the memory it sees inside WSL2, so on a planned box the line passes."""
    from tools.box import plan

    ram = 144.0  # a 192 GB workstation less the declared quarter
    caps, _ = plan.memory_caps(ram, "rtxpro6000", ROOT / "deploy")
    proc = tmp_path / "proc"
    (proc / "sys/kernel").mkdir(parents=True)
    (proc / "sys/kernel/osrelease").write_text(WSL2 + "\n")
    (proc / "meminfo").write_text(f"MemTotal: {int(ram * 1048576)} kB\n")
    files = "docker-compose.yml:docker-compose.identity.yml:docker-compose.rtxpro6000.yml"
    c = check_wsl2_memory(DoctorInputs(env={**caps, "COMPOSE_FILE": files}, deploy=ROOT / "deploy", proc=proc))
    assert c.status == "PASS", c.detail
