"""TB-PLAN-04 step 1 (D-124): a hardware profile for every box we sell, each serving the measured pair.

rtxpro6000 (both resident, 32k), gb10 (both resident, 16k), rtx5090 (sleep swap, 8k): the card detection install.sh
uses, the compose files, the registry builds and the rule that says a serving record measures a profile.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import serving_config as sc

ROOT = Path(__file__).resolve().parents[2]
JUDGE, VERIFIER = "Gemma-4-26B-A4B-NVFP4", "Qwen3.5-9B-AWQ-4bit"
PROFILES = {"rtxpro6000": 32768, "gb10": 16384, "rtx5090": 8192}  # profile -> context of both models


@pytest.mark.parametrize(
    ("arch", "card", "profile"),
    [
        ("x86_64", "NVIDIA RTX PRO 6000 Blackwell Server Edition", "rtxpro6000"),
        ("x86_64", "NVIDIA RTX PRO 6000 Blackwell Workstation Edition", "rtxpro6000"),
        ("x86_64", "NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition", "rtxpro6000"),
        ("aarch64", "NVIDIA GB10", "gb10"),
        ("x86_64", "NVIDIA GeForce RTX 5090", "rtx5090"),
        ("x86_64", "NVIDIA RTX PRO 4500 Blackwell", "rtx5090"),
        ("x86_64", "NVIDIA GeForce RTX 4090", "rtx4090"),
        ("x86_64", "NVIDIA L4", "default"),
    ],
)
def test_install_detects_the_profile_from_the_card(arch: str, card: str, profile: str) -> None:
    out = subprocess.run(
        ["sh", str(ROOT / "deploy/gpu_profile.sh"), arch, card], check=False, capture_output=True, text=True
    )
    assert out.returncode == 0 and out.stdout.strip() == profile


def test_install_wires_every_pair_profile() -> None:
    sh = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    assert 'GPU="$(sh "$ROOT/deploy/gpu_profile.sh")"' in sh  # auto-detection, no copy of the table
    assert "auto|default|rtxpro6000|gb10|rtx5090|rtx4090)" in sh
    assert "gpu:rtxpro6000) COMPOSE+=(-f deploy/docker-compose.rtxpro6000.yml)" in sh
    assert "gpu:gb10) COMPOSE+=(-f deploy/docker-compose.gb10.yml)" in sh
    assert '"deploy/site/serving_config.$GPU.json" "deploy/measured/serving_config.$GPU.json"' in sh
    assert "gpu:rtxpro6000) PROFILE=P-PRO6000" in sh
    assert "P-PRO6000" in yaml.safe_load((ROOT / "models/routing.yaml").read_text(encoding="utf-8"))["profiles"]
    out = subprocess.run(["bash", "-n", str(ROOT / "deploy/install.sh")], check=False, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def _services(name: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT / "deploy" / name).read_text(encoding="utf-8"))["services"]  # type: ignore[no-any-return]


def _flags(svc: dict[str, Any]) -> list[str]:
    return [str(c) for c in svc["command"]]


@pytest.mark.parametrize(
    ("name", "ctx"), [("docker-compose.rtxpro6000.yml", 32768), ("docker-compose.gb10.yml", 16384)]
)
def test_resident_profiles_serve_the_measured_pair(name: str, ctx: int) -> None:
    text = (ROOT / "deploy" / name).read_text(encoding="utf-8")
    svc = _services(name)
    judge, verifier = _flags(svc["llm-service"]), _flags(svc["llm-verifier"])
    for flags in (judge, verifier):
        assert (
            f"--max-model-len=${{JUDGE_MAX_LEN:-{ctx}}}" in flags
            or f"--max-model-len=${{VERIFIER_MAX_LEN:-{ctx}}}" in flags
        )
        assert "--enable-sleep-mode" not in flags and "--enforce-eager" in flags
    assert any("gemma-4-26b-a4b-it-4bit" in f for f in judge) and any("qwen3.5-9b-4bit" in f for f in verifier)
    assert any("enable_thinking" in f for f in verifier)
    assert svc["llm-verifier"]["depends_on"]["llm-service"]["condition"] == "service_healthy"
    assert svc["gateway"]["environment"]["TB_MODEL_SWAP"] == "off"
    assert svc["orchestrator"]["environment"]["TB_MODEL_SWAP"] == "off"
    assert "gpt-oss" not in "\n".join(judge + verifier) and "guided-decoding-backend" not in text


def test_pro6000_fits_the_card_with_headroom() -> None:
    svc = _services("docker-compose.rtxpro6000.yml")
    fracs = []
    for name, var in (("llm-service", "JUDGE_GPU_MEM_UTIL"), ("llm-verifier", "VERIFIER_GPU_MEM_UTIL")):
        flag = next(f for f in _flags(svc[name]) if f.startswith("--gpu-memory-utilization="))
        fracs.append(float(flag.split(f"${{{var}:-")[1].rstrip("}")))
    # weights 17.1 + 7.5 GiB of 95.6 GiB: each share must hold its weights and leave room for 32k of KV
    assert fracs[0] * 95.6 > 17.1 + 10 and fracs[1] * 95.6 > 7.5 + 5 and sum(fracs) <= 0.7
    lock = json.loads((ROOT / "deploy/images.lock").read_text(encoding="utf-8"))["third_party"]["vllm"]  # D-348
    assert svc["llm-service"]["image"].endswith(f"{lock['image']}@{lock['digest']}}}")


def test_registry_has_the_pair_for_every_profile() -> None:
    builds = {b["build_id"]: b for b in yaml.safe_load((ROOT / "models/registry.yaml").read_text())["builds"]}
    for profile, ctx in PROFILES.items():
        tag = {"gb10": "spark"}.get(profile, profile)  # the Spark's builds keep their product name
        judge, verifier = builds[f"gemma-4-26b-a4b-it-{tag}"], builds[f"qwen3.5-9b-{tag}"]
        assert (judge["alias"], verifier["alias"]) == ("j-workhorse", "v-verifier")
        assert judge["repository"].endswith(JUDGE) and verifier["repository"].endswith(VERIFIER)
        assert judge["context_length"] == verifier["context_length"] == ctx
        assert (ROOT / "models/cards" / f"gemma-4-26b-a4b-it-{tag}.md").exists()
    spark = [b for k, b in builds.items() if k.endswith("-spark")]
    assert spark and not any("gpt-oss" in b["repository"] for b in spark)  # TB-PLAN-04 §3: not the Spark judge


def _rec(name: str, ctx: int, sleep: bool = False, capped: str | None = None) -> dict[str, Any]:
    files = [{"path": "a", "bytes": 1, "sha256": "0" * 64}]
    srv = {
        "image": "vllm/vllm-openai:v0.32.0", "vllm_version": "0.32.0", "model": "/models/m", "max_model_len": ctx,
        "max_num_seqs": 16, "enforce_eager": True, "gpu_memory_utilization": 0.4, "model_files": files,
        "model_files_sha256": sc.files_digest(files), "extra_args": ["--enable-sleep-mode"] if sleep else [],
    }  # fmt: skip
    return {
        "schema": sc.SCHEMA, "card": {"name": name, "memory_total_mib": 97887, "driver": "580", "capped_to": capped},
        "servers": [{**srv, "role": "judge"}, {**srv, "role": "verifier"}],
    }  # fmt: skip


PRO = "NVIDIA RTX PRO 6000 Blackwell Server Edition"


def test_measured_rtxpro6000_accepts_an_uncapped_resident_record(tmp_path: Path) -> None:
    assert sc.measured_for(_rec(PRO, 32768), "rtxpro6000") == []
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(_rec(PRO, 32768)))
    assert sc.main(["measured", "rtxpro6000", str(p)]) == 0
    assert sc.measured_for(_rec("NVIDIA GB10", 16384), "gb10", lambda: None) == []  # memory unknown: not read


def test_measured_rtxpro6000_refuses_what_is_not_the_profile() -> None:
    assert any("capped card" in w for w in sc.measured_for(_rec(PRO, 32768, capped="RTX 5090"), "rtxpro6000"))
    assert sc.measured_for(_rec(PRO, 8192), "rtxpro6000") == ["judge context 8192 < 32768",
                                                             "verifier context 8192 < 32768"]  # fmt: skip
    assert any("keeps both resident" in w for w in sc.measured_for(_rec(PRO, 32768, sleep=True), "rtxpro6000"))
    assert any(
        "not an RTX PRO 6000" in w for w in sc.measured_for(_rec("NVIDIA GeForce RTX 5090", 32768), "rtxpro6000")
    )
    one = copy.deepcopy(_rec(PRO, 32768))
    one["servers"] = one["servers"][:1]
    assert sc.measured_for(one, "rtxpro6000") == ["no verifier server in the record"]
    assert sc.measured_for(_rec(PRO, 32768), "h100") == ["no measurement rule for profile h100"]
    # the 8 Nov bench record (the same card capped to the 5090's 32 GB, 8k) measures neither profile
    bench = json.loads((ROOT / "eval/parity/serving_config_2026-11-08_tb-gpu-sim.json").read_text())
    why = sc.measured_for(bench, "rtxpro6000")
    assert any("capped card" in w for w in why) and any("context 8192" in w for w in why)


def test_vendor_records_shipped_with_the_kit_are_measurements() -> None:
    for rec in sorted((ROOT / "deploy/measured").glob("serving_config.*.json")):
        profile = rec.name.split(".")[1]
        assert sc.measured_for(json.loads(rec.read_text()), profile, lambda: None) == [], rec.name  # no live host
