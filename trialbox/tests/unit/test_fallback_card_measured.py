"""Plan 10 row 10E-32 (review 19 card 19-3, plan 10 decision 106): the measurement rule names the RTX PRO 4500.

The RTX PRO 4500 (Blackwell, 32 GB) is the rtx5090 profile's fallback card; `deploy/gpu_profile.sh` already maps it to
`rtx5090`. Its record, taken on its own card, now passes `serving_config measured rtx5090`; every other condition
of the rule still holds: a capped record, a record made under the ballast and an unrelated card still fail (D-112,
D-1322). Synthetic records only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools import serving_config as sc
from tools import tier_record as tr

ROOT = Path(__file__).resolve().parents[2]
PRO4500 = "NVIDIA RTX PRO 4500 Blackwell"  # the name tests/unit/test_hardware_profiles.py maps to rtx5090


def _rec(name: str, capped: str | None = None, ctx: int = 8192) -> dict[str, Any]:
    files = [{"path": "a", "bytes": 1, "sha256": "0" * 64}]
    srv = {
        "image": "vllm/vllm-openai:v0.32.0", "vllm_version": "0.32.0", "model": "/models/m", "max_model_len": ctx,
        "max_num_seqs": 4, "enforce_eager": True, "gpu_memory_utilization": 0.81, "model_files": files,
        "model_files_sha256": sc.files_digest(files), "extra_args": ["--enable-sleep-mode"],
    }  # fmt: skip
    return {
        "schema": sc.SCHEMA, "card": {"name": name, "memory_total_mib": 32607, "driver": "580", "capped_to": capped},
        "servers": [{**srv, "role": "judge"}, {**srv, "role": "verifier"}],
    }  # fmt: skip


def test_a_pro_4500_record_passes_measured_rtx5090() -> None:
    assert sc.measured_for(_rec(PRO4500), "rtx5090") == []
    assert sc.measured_for(_rec("NVIDIA GeForce RTX 5090"), "rtx5090") == []  # the 5090 itself, unchanged


def test_the_cli_says_measured_for_a_pro_4500_record(tmp_path: Path) -> None:
    path = tmp_path / "serving_config.rtx5090.json"
    path.write_text(json.dumps(_rec(PRO4500)), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "tools/serving_config.py", "measured", "rtx5090", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.strip() == "measured on rtx5090"


def test_the_same_record_capped_still_fails() -> None:
    why = sc.measured_for(_rec(PRO4500, capped="RTX 5090 (32 GB)"), "rtx5090")
    assert any("capped card" in w for w in why)


def test_the_same_record_under_the_ballast_still_fails(tmp_path: Path) -> None:
    rec = _rec(PRO4500, capped="RTX 5090 (32 GB), by ballast")
    assert any("capped card" in w for w in sc.measured_for(rec, "rtx5090"))
    (tmp_path / "serving.json").write_text(json.dumps(rec), encoding="utf-8")
    why = tr._serving_problems("serving.json", "rtx5090", tmp_path)
    assert len(why) == 1 and "ballast stand-in" in why[0] and "never a tier record" in why[0]


def test_an_unrelated_card_name_still_fails() -> None:
    for name in ("NVIDIA GeForce RTX 4090", "NVIDIA RTX PRO 4000 Blackwell", "NVIDIA RTX PRO 6000 Blackwell"):
        assert any("not an 5090" in w for w in sc.measured_for(_rec(name), "rtx5090")), name


def test_the_fallback_name_counts_only_for_rtx5090() -> None:
    assert any("not an RTX PRO 6000" in w for w in sc.measured_for(_rec(PRO4500, ctx=32768), "rtxpro6000"))
    assert any("not an GB10" in w for w in sc.measured_for(_rec(PRO4500, ctx=16384), "gb10"))


def test_the_other_conditions_still_hold_for_a_pro_4500() -> None:
    rec = _rec(PRO4500, ctx=4096)
    for srv in rec["servers"]:
        srv["extra_args"] = []
    why = sc.measured_for(rec, "rtx5090")
    assert "judge ran without --enable-sleep-mode" in why and "judge context 4096 < 8192" in why
