"""Serving-configuration record (SRS FR-MOD-10, D-111): what exactly served the judge and the verifier on a card.

A record is one JSON object, schema version 1::

    {
      "schema": "tb-serving-config/1",
      "captured_at": "2026-11-06T09:12:00+00:00",          # UTC, when the capture ran
      "host": "tb-gpu-sim",                                 # hostname of the GPU box
      "card": {"name": "NVIDIA RTX PRO 6000 Blackwell ...", "memory_total_mib": 97887, "driver": "580.65.06",
               "cuda": "13.0", "count": 1, "capped_to": "RTX 5090 (32 GB)" | null},
      "memory_used_mib": 35840,                             # nvidia-smi at capture time (both servers loaded)
      "servers": [                                          # one per vLLM container (judge, verifier)
        {"role": "judge", "container": "judge", "image": "vllm/vllm-openai:v0.32.0",
         "vllm_version": "0.32.0", "model": "nvidia/Gemma-4-26B-A4B-NVFP4",
         "served_model_name": "local/gemma-4-26b-a4b-nvfp4", "quantization": "nvfp4" | null,
         "max_model_len": 8192, "max_num_seqs": 4, "enforce_eager": true,
         "gpu_memory_utilization": 0.22, "kv_cache_dtype": "auto",
         "extra_args": ["--limit-mm-per-prompt", "..."],
         "model_files": [{"path": "config.json", "bytes": 1234, "sha256": "..."}, ...],
         "model_files_sha256": "..."}                      # sha256 over the sorted "path sha256" lines
      ],
      "notes": "free text"
    }

Required (FR-MOD-10 and the step-5 brief): card, vLLM version, ``max-model-len``, ``max-num-seqs``, the eager flag,
the memory fractions and the model-file sha256 of every server. :func:`validate` lists what is missing.

``capture`` runs on the GPU box itself (stdlib only, Python 3.8+): it reads ``docker inspect`` of each vLLM container,
``nvidia-smi``, ``vllm --version`` inside the container and hashes every file of each model's snapshot under the
mounted Hugging Face cache. It is wrapped by ``deploy/gcp/capture-serving-config.sh``; nothing here starts a VM.

    python3 tools/serving_config.py capture --container judge=judge --container verifier=verifier \\
        --models-dir /models --capped-to "RTX 5090 (32 GB)" --out serving_config.json
    python -m tools.serving_config validate eval/parity/serving_config_2026-11-06.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "tb-serving-config/1"
REQUIRED_SERVER = (
    "vllm_version",
    "model",
    "max_model_len",
    "max_num_seqs",
    "enforce_eager",
    "gpu_memory_utilization",
    "model_files_sha256",
)
# vLLM flags read into named fields; everything else is kept in extra_args
FLAGS = {
    "--model": ("model", str),
    "--served-model-name": ("served_model_name", str),
    "--quantization": ("quantization", str),
    "--max-model-len": ("max_model_len", int),
    "--max-num-seqs": ("max_num_seqs", int),
    "--gpu-memory-utilization": ("gpu_memory_utilization", float),
    "--kv-cache-dtype": ("kv_cache_dtype", str),
}
SECRET_FLAGS = {"--api-key"}  # never recorded


def parse_args(args: list[str]) -> dict[str, Any]:
    """vLLM command-line arguments -> the record's server fields (``--flag value`` and ``--flag=value``)."""
    out: dict[str, Any] = {"enforce_eager": False, "kv_cache_dtype": "auto", "quantization": None, "extra_args": []}
    i = 0
    while i < len(args):
        a = args[i]
        flag, val = (a, None)
        if a.startswith("--") and "=" in a:
            flag, val = a.split("=", 1)
        if flag == "--enforce-eager":
            out["enforce_eager"] = True
        elif flag in FLAGS or flag in SECRET_FLAGS:
            if val is None and i + 1 < len(args):
                i += 1
                val = args[i]
            if flag in FLAGS:
                name, kind = FLAGS[flag]
                out[name] = kind(val)
        elif flag == "serve" and i == 0:
            pass  # ``vllm serve <model>`` form
        elif not a.startswith("--") and i == 1 and args[0] == "serve":
            out["model"] = a
        else:
            out["extra_args"].append(a)
        i += 1
    return out


def files_digest(files: list[dict[str, Any]]) -> str:
    lines = sorted(f"{f['path']} {f['sha256']}" for f in files)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def hash_tree(root: Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(x for x in root.rglob("*") if x.is_file() or (x.is_symlink() and x.resolve().is_file())):
        h = hashlib.sha256()
        with p.resolve().open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        out.append({"path": str(p.relative_to(root)), "bytes": p.resolve().stat().st_size, "sha256": h.hexdigest()})
    return out


def snapshot_dir(models_dir: Path, model: str) -> Path | None:
    """The model's files: a local directory, or the newest snapshot of ``model`` in a Hugging Face cache."""
    direct = Path(model)
    if direct.is_dir():
        return direct
    for base in (models_dir, models_dir / "hub"):
        snaps = base / ("models--" + model.replace("/", "--")) / "snapshots"
        if snaps.is_dir():
            dirs = sorted((d for d in snaps.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
            if dirs:
                return dirs[-1]
    return None


def validate(rec: dict[str, Any]) -> list[str]:
    """Missing or malformed fields; empty when the record is complete."""
    bad = []
    if rec.get("schema") != SCHEMA:
        bad.append(f"schema is not {SCHEMA}")
    card = rec.get("card") or {}
    for k in ("name", "memory_total_mib", "driver"):
        if card.get(k) in (None, ""):
            bad.append(f"card.{k}")
    servers = rec.get("servers") or []
    if not servers:
        bad.append("servers")
    for s in servers:
        who = s.get("role") or s.get("container") or "?"
        for k in REQUIRED_SERVER:
            if s.get(k) in (None, ""):
                bad.append(f"{who}.{k}")
        if not (s.get("model_files") or []):
            bad.append(f"{who}.model_files")
        frac = s.get("gpu_memory_utilization")
        if isinstance(frac, (int, float)) and not 0 < frac <= 1:
            bad.append(f"{who}.gpu_memory_utilization out of (0, 1]")
    return bad


# ---------------------------------------------------------------- capture (on the GPU box)
def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def card_info() -> tuple[dict[str, Any], int | None]:
    q = _run(
        ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader,nounits"]
    )
    rows = [[c.strip() for c in line.split(",")] for line in q.splitlines() if line.strip()]
    cuda = ""
    for line in _run(["nvidia-smi"]).splitlines():
        if "CUDA Version" in line:
            cuda = line.split("CUDA Version:")[1].split()[0]
    card = {"name": rows[0][0], "memory_total_mib": int(rows[0][1]), "driver": rows[0][3], "cuda": cuda,
            "count": len(rows)}  # fmt: skip
    return card, sum(int(r[2]) for r in rows)


def server_info(role: str, container: str, models_dir: Path) -> dict[str, Any]:
    ins = json.loads(_run(["docker", "inspect", container]))[0]
    args = list(ins.get("Args") or [])
    rec: dict[str, Any] = {"role": role, "container": container, "image": ins["Config"]["Image"]}
    rec.update(parse_args(args))
    try:
        rec["vllm_version"] = _run(
            ["docker", "exec", container, "python3", "-c", "import vllm;print(vllm.__version__)"]
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        rec["vllm_version"] = None
    snap = snapshot_dir(models_dir, str(rec.get("model") or ""))
    rec["model_files"] = hash_tree(snap) if snap else []
    rec["model_files_sha256"] = files_digest(rec["model_files"]) if rec["model_files"] else None
    rec["model_dir"] = str(snap) if snap else None
    return rec


def capture(containers: list[tuple[str, str]], models_dir: Path, capped_to: str | None, notes: str) -> dict[str, Any]:
    card, used = card_info()
    card["capped_to"] = capped_to
    return {
        "schema": SCHEMA,
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "card": card,
        "memory_used_mib": used,
        "servers": [server_info(role, c, models_dir) for role, c in containers],
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture", help="on the GPU box: write the record of the running vLLM containers")
    c.add_argument("--container", action="append", required=True, help="role=container, e.g. judge=judge")
    c.add_argument("--models-dir", type=Path, default=Path("/models"))
    c.add_argument("--capped-to", default=None)
    c.add_argument("--notes", default="")
    c.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("validate", help="list what a record is missing")
    v.add_argument("record", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "capture":
        pairs = [tuple(x.split("=", 1)) if "=" in x else (x, x) for x in a.container]
        rec = capture([(str(r), str(n)) for r, n in pairs], a.models_dir, a.capped_to, a.notes)
        a.out.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        missing = validate(rec)
        print(f"wrote {a.out}" + (f"; incomplete: {', '.join(missing)}" if missing else "; complete"))
        return 1 if missing else 0
    rec = json.loads(a.record.read_text(encoding="utf-8"))
    missing = validate(rec)
    print("complete" if not missing else "missing: " + ", ".join(missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
