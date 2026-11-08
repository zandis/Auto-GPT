"""FR-MOD-10 serving-configuration record (D-111): argument parsing, hashing and the completeness check."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools import serving_config as sc

ROOT = Path(__file__).resolve().parents[2]

ARGS = [
    "--model", "nvidia/Gemma-4-26B-A4B-NVFP4", "--served-model-name", "local/gemma-4-26b-a4b-nvfp4",
    "--max-model-len", "8192", "--max-num-seqs", "4", "--enforce-eager", "--gpu-memory-utilization", "0.22",
    "--api-key", "secret-key-value", "--limit-mm-per-prompt", '{"image":0}',
]  # fmt: skip


def test_parse_args_reads_the_fields_and_never_the_key() -> None:
    r = sc.parse_args(ARGS)
    assert r["model"] == "nvidia/Gemma-4-26B-A4B-NVFP4" and r["served_model_name"] == "local/gemma-4-26b-a4b-nvfp4"
    assert (r["max_model_len"], r["max_num_seqs"], r["enforce_eager"], r["gpu_memory_utilization"]) == (
        8192,
        4,
        True,
        0.22,
    )
    assert r["kv_cache_dtype"] == "auto" and r["quantization"] is None
    assert "secret-key-value" not in json.dumps(r) and "--api-key" not in r["extra_args"]
    assert r["extra_args"] == ["--limit-mm-per-prompt", '{"image":0}']


def test_equals_form_and_defaults() -> None:
    r = sc.parse_args(["--model=/models/q", "--max-model-len=4096", "--kv-cache-dtype=fp8", "--api-key=k"])
    assert r["model"] == "/models/q" and r["max_model_len"] == 4096 and r["kv_cache_dtype"] == "fp8"
    assert r["enforce_eager"] is False and r["extra_args"] == []


def test_hash_tree_and_snapshot_lookup(tmp_path: Path) -> None:
    snap = tmp_path / "hub" / "models--org--m" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    (snap / "w.safetensors").write_bytes(b"x" * 10)
    assert sc.snapshot_dir(tmp_path, "org/m") == snap
    files = sc.hash_tree(snap)
    assert [f["path"] for f in files] == ["config.json", "w.safetensors"] and files[1]["bytes"] == 10
    assert sc.files_digest(files) == sc.files_digest(list(reversed(files)))


def test_validate_lists_what_is_missing() -> None:
    rec = json.loads((Path(__file__).resolve().parents[2] / "eval/parity/serving_config_2026-11-06.json").read_text())
    missing = sc.validate(rec)
    assert missing == ["judge.model_files_sha256", "judge.model_files", "verifier.model_files_sha256",
                       "verifier.model_files"]  # fmt: skip  # the 6 Nov run recorded no hashes
    for s in rec["servers"]:
        s["model_files"] = [{"path": "a", "bytes": 1, "sha256": "0" * 64}]
        s["model_files_sha256"] = sc.files_digest(s["model_files"])
    assert sc.validate(rec) == []
    rec["servers"][0]["gpu_memory_utilization"] = 1.5
    assert sc.validate(rec) == ["judge.gpu_memory_utilization out of (0, 1]"]


def _rec_5090(name: str = "NVIDIA GeForce RTX 5090", capped: str | None = None, sleep: bool = True) -> dict[str, Any]:
    files = [{"path": "a", "bytes": 1, "sha256": "0" * 64}]
    srv = {
        "image": "vllm/vllm-openai:v0.32.0", "vllm_version": "0.32.0", "model": "/models/m", "max_model_len": 8192,
        "max_num_seqs": 4, "enforce_eager": True, "gpu_memory_utilization": 0.81, "model_files": files,
        "model_files_sha256": sc.files_digest(files), "extra_args": ["--enable-sleep-mode"] if sleep else [],
    }  # fmt: skip
    return {
        "schema": sc.SCHEMA, "card": {"name": name, "memory_total_mib": 32607, "driver": "580", "capped_to": capped},
        "servers": [{**srv, "role": "judge"}, {**srv, "role": "verifier"}],
    }  # fmt: skip


def test_measured_accepts_a_real_5090_record_with_sleep_mode(tmp_path: Path) -> None:
    assert sc.measured_for(_rec_5090(), "rtx5090") == []
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(_rec_5090()))
    assert sc.main(["measured", "rtx5090", str(p)]) == 0


def test_measured_refuses_capped_cards_other_cards_and_no_sleep(tmp_path: Path) -> None:
    capped = sc.measured_for(_rec_5090("NVIDIA RTX PRO 6000 Blackwell", capped="RTX 5090 (32 GB)"), "rtx5090")
    assert any("not an 5090" in w for w in capped) and any("capped card" in w for w in capped)
    assert sc.measured_for(_rec_5090(sleep=False), "rtx5090") == [
        "judge ran without --enable-sleep-mode", "verifier ran without --enable-sleep-mode"]  # fmt: skip
    # the 8 Nov bench record (RTX PRO 6000 capped to 5090 limits) is not a 5090 measurement
    bench = json.loads(
        (Path(__file__).resolve().parents[2] / "eval/parity/serving_config_2026-11-08_tb-gpu-sim.json").read_text()
    )
    assert sc.measured_for(bench, "rtx5090")
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(bench))
    assert sc.main(["measured", "rtx5090", str(p)]) == 1


def test_install_guards_the_rtx5090_profile() -> None:
    sh = (ROOT / "deploy/install.sh").read_text()
    assert 'tools.serving_config measured "$GPU"' in sh and "TB_ACCEPT_UNMEASURED_GPU" in sh
    assert "gpu:rtxpro6000|gpu:gb10|gpu:rtx5090)" in sh  # every pair profile needs a record of its own card
    compose = (ROOT / "deploy/docker-compose.rtx5090.yml").read_text()
    assert compose.count("--enable-sleep-mode") == 2 and "vllm/vllm-openai:v0.32.0" in compose
    assert "GPU_MEM_UTIL:-0.81" in compose and "outlines" not in compose
