"""Card 10E-5: a 64 GB GB10 is profile gb10-64, and its planning caps fit that host.

A larger host, or a GB10 whose memory is unknown, stays gb10. Nothing in the 64 GB profile is a measurement.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common.box_answers import parse

from tools import pin_model, serving_config as sc
from tools import tiers
from tools import two_device as td
from tools.box import plan as bp

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
A6000 = "NVIDIA RTX A6000"

pytestmark = pytest.mark.nodb


def _profile(*args: str) -> str:
    out = subprocess.run(
        ["sh", str(DEPLOY / "gpu_profile.sh"), *args], check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.mark.parametrize(
    ("args", "want"),
    [
        (("aarch64", "NVIDIA GB10", "", "64"), "gb10-64"),
        (("arm64", "NVIDIA GB10", "", "64"), "gb10-64"),
        (("aarch64", "NVIDIA GB10", "", "63"), "gb10-64"),
        (("aarch64", "NVIDIA GB10", "", "95"), "gb10-64"),
        (("aarch64", "NVIDIA GB10", "", "96"), "gb10"),
        (("aarch64", "NVIDIA GB10", "", "128"), "gb10"),
        (("aarch64", "NVIDIA GB10"), "gb10"),
        (("aarch64", "NVIDIA GB10", "", "0"), "gb10"),
        (("aarch64", "NVIDIA GB10", "", ""), "gb10"),
        (("aarch64", "", "", "64"), "gb10"),
        (("aarch64", "[N/A]", "", "64"), "gb10"),
        (("aarch64", "Unknown", "", "64"), "gb10"),
        (("aarch64", "NVIDIA RTX A6000", "", "64"), "arm64-dgpu"),
        (("x86_64", "NVIDIA GeForce RTX 5090", "", "64"), "rtx5090"),
        (("x86_64", "NVIDIA RTX PRO 6000 Blackwell Server Edition", "", "64"), "rtxpro6000"),
        (("aarch64", "NVIDIA GB10", "Enabled", "64"), "shared-quota"),
    ],
)
def test_a_64_gb_host_is_gb10_64_and_a_larger_or_unknown_host_stays_gb10(args: tuple[str, ...], want: str) -> None:
    assert _profile(*args) == want


def _load() -> dict[str, Any]:
    return td.load_profile(DEPLOY / "gb10-64-profile.yaml")


def test_the_64_gb_caps_fit_and_nothing_is_measured() -> None:
    profile = _load()
    assert td.profile_problems(profile) == []
    limits = td.memory_limits(profile)
    assert limits["llm-service"] == 23 and limits["llm-verifier"] == 13
    one = sum(v for name, v in limits.items() if name != "link")
    spark = sum(limits[name] for name in profile["devices"]["spark"])
    reserve = float(profile["device"]["os_reserve_gib"])
    assert one == pytest.approx(55.75) and spark == pytest.approx(38.5)
    assert one + reserve <= 64 and spark + reserve <= 64
    assert profile["status"] == "unmeasured" and profile["record"] is None
    assert profile["device"]["unified_memory_gib"] == 64
    assert profile["device"]["unified_memory_measured_gib"] is None
    assert all(row["measured_peak_gib"] is None for row in profile["memory"].values())
    assert all(row["result"] is None for row in profile["decision_gate"])
    assert all(value is None for value in profile["serving"].values())
    assert profile["driver_hold"]["version"] == "580.142"  # the existing hold, not a new measurement


def test_the_overlay_sets_those_caps_and_does_not_invent_serving_knobs() -> None:
    profile = _load()
    text = (DEPLOY / "docker-compose.gb10-64.yml").read_text(encoding="utf-8")
    overlay = yaml.safe_load(text)["services"]
    for name, row in profile["memory"].items():
        if name == "link":
            assert name not in overlay  # two-device only
            continue
        assert td._gib(overlay[name]["mem_limit"]) == row["limit_gib"], name
    assert overlay["gateway"]["environment"]["TB_PROFILE"] == "P-GB10-64"
    assert "-Xmx${HAPI_XMX:-2g}" in overlay["fhir-store"]["environment"]["JAVA_TOOL_OPTIONS"]
    assert overlay["embed-service"]["mem_limit"] == "2.5g"
    assert "max-model-len" not in text and "gpu-memory-utilization" not in text
    heap = 2
    assert td._gib(overlay["fhir-store"]["mem_limit"]) >= heap + 1


def test_install_selects_the_overlay_and_keeps_the_128_gb_profile() -> None:
    sh = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "auto|default|rtxpro6000|gb10|rtx5090|rtx4090)" in sh
    assert "gpu:gb10) COMPOSE+=(-f deploy/docker-compose.gb10.yml)" in sh
    assert "gpu:gb10-64) PROFILE=P-GB10-64" in sh
    assert "deploy/docker-compose.gb10-64.yml" in sh
    assert "gb10|gb10-64) GB10=1" in (DEPLOY / "check_host.sh").read_text(encoding="utf-8")
    assert pin_model.PROFILE_PAIRS["gb10-64"] == pin_model.PROFILE_PAIRS["gb10"]
    syntax = subprocess.run(["bash", "-n", str(DEPLOY / "install.sh")], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr


def _hw(**over: Any) -> bp.Hardware:
    base: dict[str, Any] = {
        "arch": "aarch64", "cpu_count": 20, "ram_gib": 128.0, "disk_free_gib": 1800.0,
        "gpu_name": "NVIDIA GB10", "gpu_mem_gib": 128.0, "tpm": False,
        "disks": (bp.Disk("/dev/sdb", 3726.0, "sata"),), "lan": "192.0.2.0/24",
        "hostname": "box1", "host_tz": "Asia/Tokyo",
    }  # fmt: skip
    return bp.Hardware(**(base | over))


def _answers() -> Any:
    owner = {
        "site_name": "示範醫院A (synthetic)", "tz": "Asia/Tokyo", "language": "ja",
        "owner": {"full_name": "Dr Owner", "username": "owner", "email": "owner@hospa.test"},
        "box_name": "trialbox", "backup": {"kind": "second_disk", "disk": "/dev/sdb"}, "source": "spreadsheet",
    }  # fmt: skip
    got, problems = parse(owner, disks=("/dev/sdb",))
    assert got is not None, problems
    return got


def test_the_box_plan_uses_the_host_memory() -> None:
    small = bp.plan(_answers(), _hw(ram_gib=64))
    assert (small.profile, small.mode) == ("gb10-64", "gpu")
    assert small.install_args == ["--mode", "gpu", "--gpu", "gb10-64"]
    assert bp.memory_caps(64, "gb10-64") == ({}, [])
    assert bp.plan(_answers(), _hw(ram_gib=128)).profile == "gb10"
    assert bp.plan(_answers(), _hw(ram_gib=64, gpu_name=A6000)).profile == "arm64-dgpu"


def _rec(memory_total_mib: int, ctx: int = 16384) -> dict[str, Any]:
    files = [{"path": "a", "bytes": 1, "sha256": "0" * 64}]
    srv = {
        "image": "vllm/vllm-openai:v0.32.0", "vllm_version": "0.32.0", "model": "/models/m", "max_model_len": ctx,
        "max_num_seqs": 8, "enforce_eager": True, "gpu_memory_utilization": 0.3, "model_files": files,
        "model_files_sha256": sc.files_digest(files), "extra_args": [],
    }  # fmt: skip
    return {
        "schema": sc.SCHEMA,
        "card": {"name": "NVIDIA GB10", "memory_total_mib": memory_total_mib, "driver": "580.142", "capped_to": None},
        "servers": [{**srv, "role": "judge"}, {**srv, "role": "verifier"}],
    }  # fmt: skip


def test_a_serving_record_counts_for_gb10_64_only_inside_that_memory_class() -> None:
    assert sc.measured_for(_rec(65536), "gb10-64") == []
    assert sc.measured_for(_rec(80 * 1024), "gb10-64") == []
    assert any("81920" in why for why in sc.measured_for(_rec(80 * 1024 + 1), "gb10-64"))
    assert any("81920" in why for why in sc.measured_for(_rec(97887), "gb10-64"))
    assert any("81920" in why for why in sc.measured_for(_rec(131072), "gb10-64"))
    assert sc.measured_for(_rec(97887), "gb10") == []  # the 128 GB rule has no memory ceiling


def test_a_named_gb10_is_not_reclassified_by_this_machines_memory() -> None:
    """tiers.resolve is given the card. It must not read MemTotal, or a small CI host would move medium off gb10."""
    assert tiers.TIERS["medium"] == "gb10"
    assert tiers.profile_of("aarch64", "NVIDIA GB10", DEPLOY) == "gb10"
    assert tiers.profile_of("aarch64", "NVIDIA GB10", DEPLOY, 64) == "gb10-64"
    assert tiers.profile_of("aarch64", "NVIDIA GB10", DEPLOY, 128) == "gb10"
    with pytest.raises(tiers.Refused, match="has no measured serving record"):
        tiers.resolve("medium", DEPLOY, "aarch64", "NVIDIA GB10")
