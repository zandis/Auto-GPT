"""FR-MOD-10 serving-configuration record (D-111): argument parsing, hashing and the completeness check."""

from __future__ import annotations

import json
from pathlib import Path

from tools import serving_config as sc

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
