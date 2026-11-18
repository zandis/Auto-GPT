"""Root review 24: an Arm 64-bit host with a discrete card that is not a GB10 is not the Spark profile.

The owner's workstation is an IGX Orin developer kit (aarch64) with an RTX A6000 (48 GB, Ampere) on driver 535.
Before this, ``deploy/gpu_profile.sh`` called every aarch64 GPU host ``gb10``: the Spark's unified-memory settings
(0.30 and 0.15 of the device) on a 48 GB discrete card, and ``tools/tiers.py`` answered "this card is tier medium".
The host now gets ``arm64-dgpu``: UNMEASURED, no overlay, no record, refused by install.sh and the one-command PoC in
GPU mode, and planned as a stub box by ``tools.box``. A GB10, and an aarch64 host whose card name is unreadable, stay
``gb10``. No GPU is needed: the arch and the card name are given to the scripts.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import tiers

ROOT = Path(__file__).resolve().parents[2]
A6000 = "NVIDIA RTX A6000"

pytestmark = pytest.mark.nodb


def _profile(arch: str, card: str) -> str:
    out = subprocess.run(
        ["sh", str(ROOT / "deploy/gpu_profile.sh"), arch, card], check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.mark.parametrize(
    ("arch", "card", "profile"),
    [
        ("aarch64", A6000, "arm64-dgpu"),
        ("aarch64", "NVIDIA RTX 6000 Ada Generation", "arm64-dgpu"),
        ("arm64", A6000, "arm64-dgpu"),
        # the measured 96 GB record was taken on x86_64: on Arm the card is not the measured box
        ("aarch64", "NVIDIA RTX PRO 6000 Blackwell Workstation Edition", "arm64-dgpu"),
        ("aarch64", "NVIDIA GB10", "gb10"),
        ("arm64", "NVIDIA GB10", "gb10"),
        # unreadable names: as before
        ("aarch64", "", "gb10"),
        ("aarch64", "[N/A]", "gb10"),
        ("aarch64", "Unknown", "gb10"),
        ("aarch64", "[Unknown Error]", "gb10"),
        ("aarch64", "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.", "gb10"),
        ("aarch64", "No devices were found", "gb10"),
        ("x86_64", "[N/A]", "default"),
        ("x86_64", "No devices were found", "default"),
        ("aarch64", "NVIDIA GB200", "b200-no-mig"),  # the B200 rule still comes first
        ("x86_64", A6000, "default"),  # the same card in an x86 machine: unchanged
    ],
)
def test_an_arm_host_with_a_discrete_card_is_not_the_spark(arch: str, card: str, profile: str) -> None:
    assert _profile(arch, card) == profile


def test_no_tier_installs_on_it() -> None:
    for tier in ("small", "medium", "large"):
        with pytest.raises(tiers.Refused, match="not one of the three measured boxes"):
            tiers.resolve(tier, ROOT / "deploy", "aarch64", A6000)


def test_install_and_the_poc_refuse_it_in_gpu_mode() -> None:
    install = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    assert '  arm64-dgpu) die "an Arm 64-bit host with a discrete card that is not a GB10 has no TrialBox profile' in (
        install
    )
    poc = (ROOT / "deploy/poc.sh").read_text(encoding="utf-8")
    # the PoC's GPU mode serves only these two; anything else stops before a file is written
    assert 'rtxpro6000|gb10) ok "GPU profile $GPU" ;;' in poc
    assert "the one-command PoC serves the pair on rtxpro6000 or gb10" in poc
    assert not (ROOT / "deploy/docker-compose.arm64-dgpu.yml").exists()


def test_the_box_plan_makes_it_a_stub_box() -> None:
    from tools.box import plan as bp

    assert bp.gpu_profile("aarch64", A6000) == "arm64-dgpu"
    assert "arm64-dgpu" not in (*bp.PAIR_PROFILES, "rtx4090")  # plan(): mode stub, "no GPU of a TrialBox profile"
