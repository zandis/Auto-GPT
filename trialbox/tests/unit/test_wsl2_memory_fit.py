"""NEW-WIN-3 (D-601): ``.wslconfig`` from the hardware, and the doctor line that the compose memory caps fit WSL2's share.

The installer's arithmetic is tested with Pester (``tests/windows``); here the declared setting it shares with the
product, and ``trialbox doctor``'s ``wsl2_memory`` on a fake ``/proc``. That the models load and answer under the
share is the measurement P-12 on the reference workstation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tb_common.config import DECLARED

from tools.trialbox.doctor import DoctorInputs, _mem_gib, check_wsl2_memory

ROOT = Path(__file__).resolve().parents[2]
WSL2 = "6.6.87.2-microsoft-standard-WSL2"
COMPOSE = """services:
  lake:
    mem_limit: ${TB_MEM_LAKE:-16g}
  llm:
    profiles: [gpu]
    mem_limit: ${TB_MEM_LLM:-24g}
  llm-stub:
    profiles: [stub]
    mem_limit: 1g
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
    return DoctorInputs(env={"COMPOSE_PROFILES": "gpu", **(env or {})}, deploy=deploy, proc=proc)


def test_the_installers_default_share_is_the_declared_setting() -> None:
    ps1 = (ROOT / "deploy/windows/box-install.ps1").read_text(encoding="utf-8")
    default = re.search(r"\[int\]\$DesktopSharePercent = (\d+)", ps1)
    assert default and default.group(1) == DECLARED["TB_WSL_DESKTOP_SHARE_PCT"].default


def test_no_memory_or_processor_figure_is_written_in_the_installer_or_the_example() -> None:
    ps1 = (ROOT / "deploy/windows/box-install.ps1").read_text(encoding="utf-8")
    assert not re.search(r"memory=\d|processors=\d", ps1)
    assert not re.search(r"(?m)^(memory|processors)=\d", (ROOT / "deploy/windows/wslconfig.example").read_text())


def test_a_plain_linux_host_and_wsl1_have_nothing_to_fit(tmp_path: Path) -> None:
    c = check_wsl2_memory(_box(tmp_path / "a", kernel="6.8.0-48-generic", mem_gib=8))
    assert (c.name, c.status) == ("wsl2_memory", "PASS") and "not WSL2" in c.detail
    assert check_wsl2_memory(_box(tmp_path / "b", kernel="4.4.0-19041-Microsoft", mem_gib=8)).status == "PASS"


def test_without_the_boxs_env_file_nothing_is_judged_and_nothing_passes(tmp_path: Path) -> None:
    """Review M6: a developer's WSL2 machine running the default doctor is not failed, and not passed either."""
    inp = _box(tmp_path, kernel=WSL2, mem_gib=4)
    inp.deploy = None
    c = check_wsl2_memory(inp)
    assert c.status == "WARN" and "--env-file" in c.detail


def test_caps_that_fit_wsl2s_share_pass_with_both_figures(tmp_path: Path) -> None:
    c = check_wsl2_memory(_box(tmp_path, kernel=WSL2, mem_gib=144))
    assert c.status == "PASS" and "40.5 GiB" in c.detail and "144.0 GiB" in c.detail


def test_caps_above_wsl2s_share_fail_and_name_the_largest(tmp_path: Path) -> None:
    c = check_wsl2_memory(_box(tmp_path, kernel=WSL2, mem_gib=32))
    assert c.status == "FAIL" and "llm 24.0" in c.detail and "32.0 GiB" in c.detail


def test_the_boxs_own_caps_are_the_ones_summed(tmp_path: Path) -> None:
    env = {"TB_MEM_LAKE": "4096m", "TB_MEM_LLM": "20g"}
    c = check_wsl2_memory(_box(tmp_path, kernel=WSL2, mem_gib=32, env=env))
    assert c.status == "PASS" and "24.5 GiB" in c.detail


@pytest.mark.parametrize(("profiles", "need"), [("stub", "17.5"), ("", "16.5"), ("gpu", "40.5"), ("gpu,oidc", "40.5")])
def test_a_model_server_that_does_not_run_is_not_counted(tmp_path: Path, profiles: str, need: str) -> None:
    """Review H1: in stub mode, or with no model profile, the model server's cap is no part of the sum."""
    c = check_wsl2_memory(_box(tmp_path, kernel=WSL2, mem_gib=20, env={"COMPOSE_PROFILES": profiles}))
    assert f"{need} GiB" in c.detail, c.detail
    assert c.status == ("FAIL" if float(need) > 20 else "PASS"), c.detail


def test_a_later_compose_file_overrides_a_cap_and_adds_services(tmp_path: Path) -> None:
    """Review M7: an overlay that sets a service's cap again replaces it; it is not counted twice."""
    inp = _box(tmp_path, kernel=WSL2, mem_gib=48, env={"COMPOSE_FILE": "docker-compose.yml:extra.yml"})
    assert inp.deploy is not None
    (inp.deploy / "extra.yml").write_text(
        "services:\n  proxy:\n    mem_limit: 1g\n  verifier:\n    profiles: [gpu]\n"
        "    deploy:\n      resources:\n        limits:\n          memory: ${TB_MEM_VERIFIER:-12g}\n"
    )
    c = check_wsl2_memory(inp)
    assert c.status == "FAIL" and "53.0 GiB" in c.detail, c.detail  # 16 + 24 + 1 (not 0.5 + 1) + 12


def test_a_compose_file_that_is_missing_is_never_a_pass(tmp_path: Path) -> None:
    inp = _box(tmp_path, kernel=WSL2, mem_gib=512, env={"COMPOSE_FILE": "docker-compose.yml:gone.yml"})
    c = check_wsl2_memory(inp)
    assert c.status == "FAIL" and "gone.yml" in c.detail


def test_a_service_without_a_cap_is_named(tmp_path: Path) -> None:
    inp = _box(tmp_path, kernel=WSL2, mem_gib=512)
    assert inp.deploy is not None
    (inp.deploy / "docker-compose.yml").write_text(COMPOSE + "  loose:\n    image: x\n")
    c = check_wsl2_memory(inp)
    assert c.status == "WARN" and "no cap on loose" in c.detail


@pytest.mark.parametrize(
    ("raw", "gib"),
    [
        ("16g", 16.0),
        ("16G", 16.0),
        ("16gb", 16.0),
        ("4096m", 4.0),
        ("2097152k", 2.0),
        ("1073741824", 1.0),
        ("1.5g", 1.5),
    ],
)
def test_memory_sizes_are_read_as_compose_reads_them(raw: str, gib: float) -> None:
    assert _mem_gib(raw) == pytest.approx(gib)


def test_a_quoted_or_plain_bytes_cap_counts_and_a_bad_one_fails(tmp_path: Path) -> None:
    inp = _box(tmp_path, kernel=WSL2, mem_gib=64)
    assert inp.deploy is not None
    (inp.deploy / "docker-compose.yml").write_text(
        'services:\n  a:\n    mem_limit: "8g"\n  b:\n    mem_limit: 2147483648\n  c:\n    mem_limit: ${TB_MEM_D2:-4g}\n'
    )
    c = check_wsl2_memory(inp)
    assert c.status == "PASS" and "14.0 GiB" in c.detail, c.detail
    bad = _box(tmp_path / "b", kernel=WSL2, mem_gib=64, env={"TB_MEM_LAKE": "lots"})
    c = check_wsl2_memory(bad)
    assert c.status == "FAIL" and "TB_MEM_LAKE" in c.detail
    unreadable = _box(tmp_path / "c", kernel=WSL2, mem_gib=64)
    (unreadable.proc / "meminfo").write_text("garbage\n")
    assert check_wsl2_memory(unreadable).status == "FAIL"


@pytest.mark.parametrize(
    ("profile", "mode", "ram"),
    [("rtxpro6000", "gpu", 144.0), ("rtxpro6000", "gpu", 94.0), ("stub", "stub", 30.0), ("stub", "stub", 62.0),
     ("none", "", 62.0)],
)  # fmt: skip
def test_the_real_compose_set_fits_the_share_the_box_plan_caps_it_to(
    tmp_path: Path, profile: str, mode: str, ram: float
) -> None:
    """tools.box plan caps the services to the memory it sees inside WSL2, so a planned box passes in every profile
    (review H1: stub and none failed before, because servers that do not run were counted). The rtx4090 profile
    is left out on purpose: its plan sets no cap for the verifier, which the overlay it names runs at its default;
    that is a question for the box plan (lane D), and the doctor line rightly fails such a box."""
    from tools.box import plan

    caps, _ = plan.memory_caps(ram, profile, ROOT / "deploy")
    proc = tmp_path / "proc"
    (proc / "sys/kernel").mkdir(parents=True)
    (proc / "sys/kernel/osrelease").write_text(WSL2 + "\n")
    (proc / "meminfo").write_text(f"MemTotal: {int(ram * 1048576)} kB\n")
    overlay = {"rtxpro6000": ":docker-compose.rtxpro6000.yml", "rtx4090": ":docker-compose.rtx5090.yml"}.get(
        profile, ""
    )
    env = {**caps, "COMPOSE_FILE": "docker-compose.yml:docker-compose.identity.yml" + overlay, "COMPOSE_PROFILES": mode}
    c = check_wsl2_memory(DoctorInputs(env=env, deploy=ROOT / "deploy", proc=proc))
    assert c.status == "PASS", c.detail
