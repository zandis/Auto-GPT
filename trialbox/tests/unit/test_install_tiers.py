"""TB-PLAN-04 step 8 (D-138): ``install.sh --tier small|medium|large`` installs only a measured box.

No GPU is needed: the card name and the machine are given to the check (``tools/tiers.py``, and in the shell tests
``TB_TIER_TEST_CARD`` / ``TB_TIER_TEST_ARCH``), and the records are the vendor's ``deploy/measured/`` files or copies
of them in a temporary ``deploy`` folder.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools import tiers

ROOT = Path(__file__).resolve().parents[2]
PRO6000 = "NVIDIA RTX PRO 6000 Blackwell Server Edition"
R5090 = "NVIDIA GeForce RTX 5090"
VENDOR = json.loads((ROOT / "deploy/measured/serving_config.rtxpro6000.json").read_text(encoding="utf-8"))


def _deploy(tmp: Path, records: dict[str, dict[str, Any]], where: str = "measured") -> Path:
    d = tmp / "deploy"
    (d / "measured").mkdir(parents=True)
    (d / "site").mkdir()
    shutil.copy(ROOT / "deploy/gpu_profile.sh", d / "gpu_profile.sh")
    for gpu, rec in records.items():
        (d / where / f"serving_config.{gpu}.json").write_text(json.dumps(rec), encoding="utf-8")
    return d


def _as_5090(rec: dict[str, Any]) -> dict[str, Any]:
    """The vendor's PRO 6000 record turned into what a real 5090 measurement looks like (sleep swap, 8k)."""
    r = copy.deepcopy(rec)
    r["card"]["name"] = R5090
    r["card"]["capped_to"] = None
    for s in r["servers"]:
        s["max_model_len"] = 8192
        s["extra_args"] = [*s.get("extra_args", []), "--enable-sleep-mode"]
    return r


def test_the_tiers_are_the_three_measured_boxes() -> None:
    assert tiers.TIERS == {"small": "rtx5090", "medium": "gb10", "large": "rtxpro6000"}


def test_large_installs_on_a_pro6000_from_the_vendor_record() -> None:
    gpu, rec = tiers.resolve("large", ROOT / "deploy", "x86_64", PRO6000)
    assert gpu == "rtxpro6000" and rec == ROOT / "deploy/measured/serving_config.rtxpro6000.json"


@pytest.mark.parametrize(("tier", "arch", "card"), [("small", "x86_64", R5090), ("medium", "aarch64", "NVIDIA GB10")])
def test_an_unmeasured_tier_is_refused_with_what_is_missing_and_how_to_get_it(tier: str, arch: str, card: str) -> None:
    with pytest.raises(tiers.Refused) as exc:
        tiers.resolve(tier, ROOT / "deploy", arch, card)
    msg = str(exc.value)
    gpu = tiers.TIERS[tier]
    assert "has no measured serving record" in msg and f"serving_config.{gpu}.json" in msg
    assert "tools/serving_config.py capture" in msg and f"--tier {tier}" in msg


def test_the_card_must_be_the_tiers_card() -> None:
    with pytest.raises(tiers.Refused, match="this card is tier small"):
        tiers.resolve("large", ROOT / "deploy", "x86_64", R5090)
    with pytest.raises(tiers.Refused, match="not one of the three measured boxes"):
        tiers.resolve("large", ROOT / "deploy", "x86_64", "NVIDIA L4")
    with pytest.raises(tiers.Refused, match="no NVIDIA card"):
        tiers.resolve("large", ROOT / "deploy", "x86_64", "")
    with pytest.raises(tiers.Refused, match="unknown tier"):
        tiers.resolve("huge", ROOT / "deploy", "x86_64", PRO6000)


def test_a_capped_or_wrong_record_is_refused(tmp_path: Path) -> None:
    capped = copy.deepcopy(VENDOR)
    capped["card"]["capped_to"] = "RTX 5090 (32 GB)"
    d = _deploy(tmp_path, {"rtxpro6000": capped}, where="site")  # the site's record is read first
    with pytest.raises(tiers.Refused, match="capped card"):
        tiers.resolve("large", d, "x86_64", PRO6000)
    shutil.rmtree(d)
    d = _deploy(tmp_path, {"rtx5090": copy.deepcopy(VENDOR) | {"card": {**VENDOR["card"], "name": R5090}}})
    with pytest.raises(tiers.Refused, match="without --enable-sleep-mode"):
        tiers.resolve("small", d, "x86_64", R5090)


def test_a_site_record_of_its_own_card_makes_the_tier_installable(tmp_path: Path) -> None:
    d = _deploy(tmp_path, {"rtx5090": _as_5090(VENDOR)}, where="site")
    gpu, rec = tiers.resolve("small", d, "x86_64", R5090)
    assert gpu == "rtx5090" and rec == d / "site/serving_config.rtx5090.json"


def _install(*args: str, card: str, arch: str = "x86_64", **env: str) -> subprocess.CompletedProcess[str]:
    e = {**os.environ, "TB_TIER_TEST_CARD": card, "TB_TIER_TEST_ARCH": arch, **env}
    return subprocess.run(["bash", str(ROOT / "deploy/install.sh"), *args], capture_output=True, text=True, env=e,
                          check=False, timeout=60)  # fmt: skip


def test_install_sh_refuses_an_unmeasured_tier_before_anything_else(tmp_path: Path) -> None:
    bundle = tmp_path / "trialbox-x.tar"
    bundle.write_bytes(b"")
    out = _install(str(bundle), "--tier", "small", card=R5090)
    assert out.returncode == 3
    assert "refused: tier small" in out.stderr and "has no measured serving record" in out.stderr
    assert "==> host" not in out.stdout  # stopped before the host, the bundle or any setting
    # no override: the trial-boot switch does not make an unmeasured tier installable
    out = _install(str(bundle), "--tier", "medium", card="NVIDIA GB10", arch="aarch64", TB_ACCEPT_UNMEASURED_GPU="1")
    assert out.returncode == 3 and "refused: tier medium" in out.stderr


def test_install_sh_tier_check_accepts_the_measured_tier_and_rejects_mixed_options() -> None:
    ok = _install("--tier", "large", "--tier-check", card=PRO6000)
    assert ok.returncode == 0, ok.stderr
    assert "tier large: rtxpro6000 profile" in ok.stdout and "serving_config.rtxpro6000.json" in ok.stdout
    wrong = _install("--tier", "large", "--tier-check", card=R5090)
    assert wrong.returncode == 3 and "this card is tier small" in wrong.stderr
    both = _install("--tier", "large", "--gpu", "rtxpro6000", "--tier-check", card=PRO6000)
    assert both.returncode != 0 and "--tier and --gpu" in both.stderr
    stub = _install("--tier", "large", "--mode", "stub", "--tier-check", card=PRO6000)
    assert stub.returncode != 0 and "needs the GPU" in stub.stderr
