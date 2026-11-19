"""Card 10E-5 (D-1335): a DGX Spark with under 96 GiB of memory (the 64 GB class) is refused, not guessed.

The gb10 profile is sized for the 128 GB Spark (its two model servers alone are capped at 42 + 32 GiB). Nothing of
the 64 GB class is measured, and a profile for it cannot be shown to fit from the numbers recorded in the repository,
so it has no profile, no overlay, no tier record and no serving record. ``deploy/gpu_profile.sh`` names it
``gb10-64`` from ``MemTotal`` (kB, no rounding); ``install.sh``, the one-command PoC and ``tools/tiers.py`` refuse
its GPU mode with a sentence that says why and what to do, however gb10 was chosen; the box plan makes it a stub box.
No GPU is needed: the arch, the card and the memory are given to the scripts, docker and nvidia-smi are stand-ins.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tb_common.box_answers import parse

from tools import pin_model, serving_config, tiers
from tools.box import plan as bp

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
GB10 = "NVIDIA GB10"
LINE_KIB = 96 * 1024 * 1024  # 96 GiB in kB
SMALL_KIB = 62_000_000  # a 64 GB Spark's MemTotal is under 64 GiB (illustrative, synthetic)
BIG_KIB = 124_000_000  # a 128 GB Spark's (illustrative, synthetic)
SENTENCE = "under 96 GiB of memory (the 64 GB class)"


def _profile(*args: str) -> str:
    out = subprocess.run(["sh", str(ROOT / "deploy/gpu_profile.sh"), *args], check=True, capture_output=True,
                         text=True)  # fmt: skip
    return out.stdout.strip()


# ------------------------------------------------------------------------------------------------ the detector
@pytest.mark.parametrize(
    ("arch", "card", "mig", "kib", "profile"),
    [
        ("aarch64", GB10, "", str(SMALL_KIB), "gb10-64"),
        ("arm64", GB10, "", str(SMALL_KIB), "gb10-64"),
        ("aarch64", GB10, "", str(LINE_KIB - 1), "gb10-64"),  # one kB under the line: compared in kB, never rounded
        ("aarch64", GB10, "", str(LINE_KIB), "gb10"),
        ("aarch64", GB10, "", str(BIG_KIB), "gb10"),
        ("aarch64", "[N/A]", "", str(SMALL_KIB), "gb10-64"),  # an unreadable name on Arm is the Spark, as before
        ("aarch64", GB10, "", "", "gb10"),  # memory unknown: as before
        ("aarch64", GB10, "", "n/a", "gb10"),
        ("aarch64", GB10, "Enabled", str(SMALL_KIB), "shared-quota"),  # MIG is still read first
        ("aarch64", "NVIDIA RTX A6000", "", str(SMALL_KIB), "arm64-dgpu"),  # memory decides only for a GB10
        ("x86_64", "NVIDIA RTX PRO 6000 Blackwell Server Edition", "", str(SMALL_KIB), "rtxpro6000"),
    ],
)
def test_a_spark_under_96_gib_is_the_64_gb_class(arch: str, card: str, mig: str, kib: str, profile: str) -> None:
    assert _profile(arch, card, mig, kib) == profile


def test_three_arguments_are_unchanged() -> None:
    assert _profile("aarch64", GB10) == "gb10" and _profile("aarch64", GB10, "") == "gb10"


def test_the_memory_class_alone() -> None:
    assert _profile("memory-class", str(SMALL_KIB)) == "gb10-64"
    assert _profile("memory-class", str(LINE_KIB)) == "gb10"
    assert _profile("memory-class") in ("gb10", "gb10-64")  # this host's own MemTotal


def test_nothing_of_the_class_exists_to_install() -> None:
    for rel in ("deploy/docker-compose.gb10-64.yml", "deploy/gb10-64-profile.yaml", "models/tiers/gb10-64.json",
                "deploy/measured/serving_config.gb10-64.json"):  # fmt: skip
        assert not (ROOT / rel).exists(), rel
    assert "gb10-64" not in pin_model.PROFILE_PAIRS and "gb10-64" not in serving_config.PROFILES
    assert "gb10-64" not in (*bp.PAIR_PROFILES, "rtx4090") and "gb10-64" not in tiers.TIERS.values()


# ------------------------------------------------------------------------------------------------ install.sh
def _bin(tmp: Path) -> Path:
    bindir = tmp / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text('#!/bin/sh\necho "$*" >> "$TB_TEST_LOG"\necho "Runtimes: nvidia runc"\nexit 0\n',
                                   encoding="utf-8")  # fmt: skip
    (bindir / "nvidia-smi").write_text(f'#!/bin/sh\necho "GPU 0: {GB10} (UUID: GPU-0)"\n', encoding="utf-8")
    for f in bindir.iterdir():
        f.chmod(0o755)
    return bindir


def _install(tmp: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    bundle = tmp / "trialbox-x.tar"
    bundle.write_bytes(b"")
    full = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    full.update(PATH=f"{_bin(tmp)}:{os.environ['PATH']}", TB_TEST_LOG=str(tmp / "docker.log"), **env)
    return subprocess.run(["bash", str(ROOT / "deploy/install.sh"), str(bundle), *args], capture_output=True,
                          text=True, env=full, timeout=120, check=False)  # fmt: skip


@pytest.mark.parametrize(
    ("args", "env"),
    [
        (["--mode", "gpu", "--gpu", "gb10"], {}),  # named by hand on a small Spark
        (["--mode", "gpu"], {"TB_GPU_PROFILE": "gb10"}),  # named in the environment
        (["--mode", "gpu", "--gpu", "gb10-64"], {}),  # its own word
        (["--mode", "gpu", "--gpu", "gb10", "--rehearsal"], {"TB_COMPOSE_OVERRIDE": ""}),  # a rehearsal box too
    ],
)
def test_install_refuses_the_small_spark_before_anything_is_written(
    tmp_path: Path, args: list[str], env: dict[str, str]
) -> None:
    state = [ROOT / "deploy" / n for n in (".env", "settings.yaml", "updates", "secrets", "site")]
    before = [q.exists() for q in state]
    res = _install(tmp_path, *args, TB_TEST_MEM_KIB=str(SMALL_KIB), **env)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"install: this DGX Spark has {SENTENCE}" in res.stderr
    assert "no profile of the 64 GB class is measured, so none is guessed" in res.stderr
    assert "--mode stub" in res.stderr and "D-1335" in res.stderr
    assert [q.exists() for q in state] == before
    log = (tmp_path / "docker.log").read_text(encoding="utf-8") if (tmp_path / "docker.log").exists() else ""
    assert "load" not in log.split() and " up " not in f" {log} "


def test_install_lets_a_128_gb_spark_past_the_profile_step(tmp_path: Path) -> None:
    res = _install(tmp_path, "--mode", "gpu", "--gpu", "gb10", TB_TEST_MEM_KIB=str(BIG_KIB))
    assert SENTENCE not in res.stderr and "--gpu must be" not in res.stderr


def test_install_tier_medium_refuses_the_small_spark(tmp_path: Path) -> None:
    res = _install(tmp_path, "--tier", "medium", "--tier-check", TB_TIER_TEST_CARD=GB10, TB_TIER_TEST_ARCH="aarch64",
                   TB_TEST_MEM_KIB=str(SMALL_KIB))  # fmt: skip
    assert res.returncode == 3, res.stdout + res.stderr
    assert "refused: tier medium" in res.stderr and "the 64 GB class, gb10-64 profile" in res.stderr


# ------------------------------------------------------------------------------------------------ tools/tiers.py
def test_the_tier_check_names_the_class() -> None:
    with pytest.raises(tiers.Refused, match="under 96 GiB of memory") as exc:
        tiers.resolve("medium", ROOT / "deploy", "aarch64", GB10, SMALL_KIB)
    assert "--mode stub" in str(exc.value) and "none is guessed" in str(exc.value)
    for tier in ("small", "large"):
        with pytest.raises(tiers.Refused, match="64 GB class"):
            tiers.resolve(tier, ROOT / "deploy", "aarch64", GB10, SMALL_KIB)
    # a 128 GB Spark gets as far as before: the record rule
    with pytest.raises(tiers.Refused, match="has no measured serving record"):
        tiers.resolve("medium", ROOT / "deploy", "aarch64", GB10, BIG_KIB)


def test_host_mem_kib_reads_memtotal_in_kb(tmp_path: Path) -> None:
    m = tmp_path / "meminfo"
    m.write_text(f"MemTotal:       {LINE_KIB - 1} kB\nMemFree: 1 kB\n", encoding="utf-8")
    assert tiers.host_mem_kib(m) == LINE_KIB - 1
    assert tiers.host_mem_kib(tmp_path / "none") is None


# ------------------------------------------------------------------------------------------------ the PoC
def _poc(tmp: Path, **env: str) -> subprocess.CompletedProcess[str]:
    root = tmp / "root"
    (root / "deploy").mkdir(parents=True)
    for rel in ("deploy/poc.sh", "deploy/gpu_profile.sh", ".env.example"):
        (root / rel).write_bytes((ROOT / rel).read_bytes())
    full = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    full.update(PATH=f"{_bin(tmp)}:/usr/bin:/bin", TB_TEST_LOG=str(tmp / "docker.log"), **env)
    return subprocess.run(["bash", str(root / "deploy/poc.sh")], capture_output=True, text=True, env=full,
                          timeout=60, check=False)  # fmt: skip


@pytest.mark.parametrize("named", ["gb10", "gb10-64"])
def test_the_poc_refuses_the_small_spark(tmp_path: Path, named: str) -> None:
    res = _poc(tmp_path, TB_LLM_MODE="gpu", TB_GPU_PROFILE=named, TB_TEST_MEM_KIB=str(SMALL_KIB))
    assert res.returncode == 1, res.stdout + res.stderr
    assert SENTENCE in res.stderr and "D-1335" in res.stderr
    assert not (tmp_path / "root/deploy/.env").exists()


# ------------------------------------------------------------------------------------------------ the box plan
def _hw(**over: Any) -> bp.Hardware:
    base: dict[str, Any] = {"arch": "aarch64", "cpu_count": 20, "ram_gib": 96.0, "disk_free_gib": 1800.0,
                            "gpu_name": GB10, "tpm": True, "lan": "192.0.2.0/24", "hostname": "box1",
                            "host_tz": "Asia/Tokyo"}  # fmt: skip
    return bp.Hardware(**(base | over))


def _answers() -> Any:
    a, problems = parse({"site_name": "Hospital A (synthetic)", "tz": "Asia/Tokyo", "language": "en",
                         "owner": {"full_name": "Dr Owner", "username": "owner", "email": "owner@hospa.test"},
                         "box_name": "trialbox", "backup": {"kind": "second_disk", "disk": "/dev/sdb"},
                         "source": "spreadsheet"}, disks=("/dev/sdb",))  # fmt: skip
    assert a is not None, problems
    return a


def test_the_box_plan_makes_the_small_spark_a_stub_box() -> None:
    # 96.0 GiB as shown, one kB under the line as read: the reading decides (review: rounding crossed the line)
    p = bp.plan(_answers(), _hw(mem_total_kib=LINE_KIB - 1))
    assert (p.profile, p.mode, p.install_args) == ("gb10-64", "stub", ["--mode", "stub"])
    assert bp.SMALL_SPARK in p.warnings
    big = bp.plan(_answers(), _hw(ram_gib=119.7, mem_total_kib=BIG_KIB))
    assert (big.profile, big.mode) == ("gb10", "gpu") and bp.SMALL_SPARK not in big.warnings
    # a hardware file without the reading falls back on ram_gib
    assert bp.plan(_answers(), _hw(ram_gib=59.6)).profile == "gb10-64"


# ------------------------------------------------------------------------------------------------ make spark-e2e
def test_the_spark_e2e_gpu_run_refuses_the_small_spark(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TB_")}
    env.update(TB_SPARK_OUT=str(tmp_path / "run"), TB_TEST_MEM_KIB=str(SMALL_KIB))
    res = subprocess.run(["bash", str(ROOT / "tools/spark_e2e.sh")], capture_output=True, text=True, env=env,
                         timeout=60, check=False)  # fmt: skip
    assert res.returncode == 2, res.stdout + res.stderr
    assert "under 96 GiB of memory (the 64 GB Spark class)" in res.stderr and "TB_LLM_MODE=stub" in res.stderr
    assert not (tmp_path / "run").exists()  # stopped before the run directory
