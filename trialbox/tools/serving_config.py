"""Serving-configuration record (SRS FR-MOD-10, D-111): what exactly served the judge and the verifier on a card.

A record is one JSON object, schema version 1::

    {
      "schema": "tb-serving-config/1",
      "captured_at": "2026-11-06T09:12:00+00:00",          # UTC, when the capture ran
      "host": "tb-gpu-sim",                                 # hostname of the GPU box
      "card": {"name": "NVIDIA RTX PRO 6000 Blackwell ...", "memory_total_mib": 97887, "driver": "580.65.06",
               "cuda": "13.0", "count": 1, "capped_to": "RTX 5090 (32 GB)" | null,
               "mig": true | false},                     # MIG mode of the card (D-409)
      "memory_used_mib": 35840,                             # nvidia-smi at capture time (both servers loaded)
      "servers": [                                          # one per vLLM container (judge, verifier)
        {"role": "judge", "container": "judge", "image": "vllm/vllm-openai:v0.32.0",
         "image_digests": ["vllm/vllm-openai@sha256:..."], "structured_outputs_backend": "auto",
         "vllm_version": "0.32.0", "model": "nvidia/Gemma-4-26B-A4B-NVFP4",
         "served_model_name": "local/gemma-4-26b-a4b-nvfp4", "quantization": "nvfp4" | null,
         "max_model_len": 8192, "max_num_seqs": 4, "enforce_eager": true,
         "gpu_memory_utilization": 0.22, "kv_cache_dtype": "auto",
         "extra_args": ["--limit-mm-per-prompt", "..."],
         "model_files": [{"path": "config.json", "bytes": 1234, "sha256": "..."}, ...],
         "model_files_sha256": "...",                      # sha256 over the sorted "path sha256" lines
         "chat_template": "/models/chat-templates/.../chat_template.jinja" | null,   # vLLM --chat-template
         "chat_template_sha256": "..." | null,             # sha256 of that file (T-674, DEP-007)
         "gpu_devices": ["MIG-9f..."] | ["GPU-1a..."],     # the device the container was given (D-409)
         "mig_profile": "2g.45gb" | null}                  # that device's MIG profile (nvidia-smi -L)
      ],
      "notes": "free text"
    }

Required (FR-MOD-10 and the step-5 brief): card, vLLM version, ``max-model-len``, ``max-num-seqs``, the eager flag,
the memory fractions and the model-file sha256 of every server. :func:`validate` lists what is missing. A server
started with ``--chat-template`` must name the template's sha256 (T-674, DEP-007: the judge's template comes from
the developer at a pinned revision, not from the quantised folder); :func:`chat_template_of` returns it, and
:func:`template_problems` says when a record's judge was not started with the template the registry names.

``capture`` runs on the GPU box itself (stdlib only, Python 3.8+): it reads ``docker inspect`` of each vLLM container,
``nvidia-smi``, ``vllm --version`` inside the container and hashes every file of each model's snapshot under the
mounted Hugging Face cache. It is wrapped by ``deploy/gcp/capture-serving-config.sh``; nothing here starts a VM.

    python3 tools/serving_config.py capture --container judge=judge --container verifier=verifier \\
        --models-dir /models --capped-to "RTX 5090 (32 GB)" --out serving_config.json
    python -m tools.serving_config validate eval/parity/serving_config_2026-11-06.json
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
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
    "--chat-template": ("chat_template", str),
    "--chat-template-content-format": ("chat_template_content_format", str),  # D-880
}
SECRET_FLAGS = {"--api-key"}  # never recorded
ROLES = ("judge", "verifier")
# the structured-output backend (D-348): this flag, its JSON form, or vLLM's default "auto" when neither is given
BACKEND_FLAG = "--structured-outputs-config.backend"


def parse_args(args: list[str]) -> dict[str, Any]:
    """vLLM command-line arguments -> the record's server fields (``--flag value`` and ``--flag=value``)."""
    out: dict[str, Any] = {
        "enforce_eager": False,
        "kv_cache_dtype": "auto",
        "quantization": None,
        "chat_template": None,
        "chat_template_content_format": None,
        "extra_args": [],
    }
    out["structured_outputs_backend"] = "auto"
    i = 0
    while i < len(args):
        a = args[i]
        flag, val = (a, None)
        if a.startswith("--") and "=" in a:
            flag, val = a.split("=", 1)
        if flag == "--enforce-eager":
            out["enforce_eager"] = True
        elif flag in (BACKEND_FLAG, "--structured-outputs-config"):
            if val is None and i + 1 < len(args):
                i += 1
                val = args[i]
            out["extra_args"] += [flag, str(val)]
            if flag == BACKEND_FLAG:
                out["structured_outputs_backend"] = val
            else:
                with contextlib.suppress(ValueError, AttributeError):
                    out["structured_outputs_backend"] = json.loads(str(val)).get("backend") or "auto"
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
    if model.startswith("/models/") and (host := _host_path(models_dir, model)).is_dir():
        return host  # the compose form names the folder inside the container (shared-quota, T-114)
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
        if s.get("chat_template") and not s.get("chat_template_sha256"):
            bad.append(f"{who}.chat_template_sha256")
        frac = s.get("gpu_memory_utilization")
        if isinstance(frac, (int, float)) and not 0 < frac <= 1:
            bad.append(f"{who}.gpu_memory_utilization out of (0, 1]")
    return bad


def chat_template_of(rec: dict[str, Any], role: str = "judge") -> tuple[str | None, str | None]:
    """(template path, sha256) the ``role`` server was started with; (None, None) when it used the model folder's."""
    for s in rec.get("servers") or []:
        if s.get("role") == role:
            return s.get("chat_template") or None, s.get("chat_template_sha256") or None
    return None, None


def template_problems(rec: dict[str, Any], want_sha256: str | None, role: str = "judge") -> list[str]:
    """Why the record's ``role`` server did not serve with the pinned chat template (T-674); empty when it did.
    ``want_sha256`` is the pin's ``weights.chat_template.sha256`` (or the registry's, once fetched)."""
    path, sha = chat_template_of(rec, role)
    if not path:
        return [f"{role} ran without --chat-template (the template inside the model folder was used)"]
    if not sha:
        return [f"{role} names no chat_template_sha256"]
    if want_sha256 and sha != want_sha256:
        return [f"{role} chat template {sha[:12]} is not the pinned {want_sha256[:12]}"]
    # D-880: rendered as strings; vLLM's own choice for this template is list parts, whose system branch adds a space
    fmt = next((s.get("chat_template_content_format") for s in rec.get("servers") or [] if s.get("role") == role), None)
    if fmt != "string":
        return [f"{role} ran with --chat-template-content-format {fmt or 'unset'} (string wanted, D-880)"]
    return []


def _host_path(models_dir: Path, path: str) -> Path:
    """The host file behind a container path under ``/models`` (the compose mount of the models root)."""
    if path.startswith("/models/"):
        return models_dir / path[len("/models/") :]
    return Path(path)


def template_sha256(models_dir: Path, path: str | None) -> str | None:
    if not path:
        return None
    host = _host_path(models_dir, path)
    if not host.is_file():
        return None
    return hashlib.sha256(host.read_bytes()).hexdigest()


# What a record must show to count as a measurement of a GPU profile on its own card (install.sh, D-112, D-124):
#   card       a string in nvidia-smi's card name (the GB10 reports "NVIDIA GB10")
#   also       other strings that name a card of the same profile: the RTX PRO 4500 (Blackwell, 32 GB) is the rtx5090
#              profile's fallback card (plan 10 decision 106, review 19 card 19-3), mapped to it by
#              deploy/gpu_profile.sh:45; its record, taken on its own card, must meet every other condition here
#   sleep     True: both servers ran with --enable-sleep-mode (the one-card swap, the only way the 5090 pair fits);
#              False: both resident, no sleep mode (the profile serves them side by side)
#   min_len    each server's --max-model-len is at least this (the profile's context)
#   mig        True: each server on its own MIG instance; the context rule is then keyed on that instance's MIG
#              profile (MIG_MIN_LEN), not on the card (shared-quota, D-409)
PROFILES: dict[str, dict[str, Any]] = {
    "rtx5090": {"card": "5090", "also": ("RTX PRO 4500",), "sleep": True, "min_len": 8192},
    "rtxpro6000": {"card": "RTX PRO 6000", "sleep": False, "min_len": 32768},
    "gb10": {"card": "GB10", "sleep": False, "min_len": 16384},
    "shared-quota": {"card": "B200", "sleep": False, "min_len": None, "mig": True},
}
# D-409 (LLM-011, LLM-027): the shared-quota rule, keyed on the MIG profile of the instance a server ran on: the
# context each server must reach there, by the instance's memory (as the cards above: 23 GB like the 24-32 GB cards,
# 45 GB like the GB10's share, 90 GB and more like the 96 GB card). A profile not listed has no rule and is refused.
# B200 profiles (nvidia-smi mig -lgip); the "+me" variants (media engines) have the same memory.
MIG_MIN_LEN: dict[str, int] = {
    "1g.23gb": 8192,
    "1g.45gb": 16384,
    "2g.45gb": 16384,
    "3g.90gb": 32768,
    "4g.90gb": 32768,
    "7g.180gb": 32768,
}
MIG_PROFILE = re.compile(r"^\d+g\.\d+gb(\+me)?$")


def mig_base(profile: str) -> str:
    """``1g.23gb+me`` -> ``1g.23gb`` (the rule's key)."""
    return profile.strip().removesuffix("+me")


def mig_layout(text: str) -> dict[str, str]:
    """``TB_MIG_PROFILE`` as ``{role: profile}``: one profile both instances have (``3g.90gb``), or one per role
    (``judge=2g.45gb,verifier=1g.23gb``). Empty for ``""`` or ``unmeasured``; ValueError for anything else."""
    t = text.strip()
    if not t or t == "unmeasured":
        return {}
    if "=" not in t:
        if not MIG_PROFILE.match(t):
            raise ValueError(f"MIG profile {t!r} is not <n>g.<mem>gb")
        return dict.fromkeys(ROLES, t)
    out: dict[str, str] = {}
    for part in (p.strip() for p in t.split(",") if p.strip()):
        role, _, prof = part.partition("=")
        if role.strip() not in ROLES or not MIG_PROFILE.match(prof.strip()):
            raise ValueError(f"MIG layout part {part!r} is not judge=<profile> or verifier=<profile>")
        out[role.strip()] = prof.strip()
    if set(out) != set(ROLES):
        raise ValueError(f"MIG layout {t!r} must name the judge and the verifier")
    return out


def record_layout(rec: dict[str, Any]) -> dict[str, str]:
    """``{role: MIG profile}`` a record's servers ran on (each server's ``mig_profile``, else the card's)."""
    card = rec.get("card") or {}
    out = {}
    for s in rec.get("servers") or []:
        prof = s.get("mig_profile") or card.get("mig_profile")
        if s.get("role") and prof:
            out[str(s["role"])] = str(prof)
    return out


def parse_mig_list(text: str) -> dict[str, str]:
    """``nvidia-smi -L`` -> ``{MIG instance UUID: profile}`` (lines ``MIG 2g.45gb Device 0: (UUID: MIG-...)``)."""
    out = {}
    for m in re.finditer(r"MIG\s+(\S+)\s+Device\s+\d+:\s*\(UUID:\s*(MIG-[0-9A-Za-z-]+)\)", text):
        out[m.group(2)] = m.group(1)
    return out


PROFILE_CARDS = {k: v["card"] for k, v in PROFILES.items()}


def measured_for(rec: dict[str, Any], profile: str) -> list[str]:
    """Why ``rec`` is not a measurement of ``profile`` on its own card; empty when it is (install.sh, D-112).

    A record counts only when it is complete, was taken on the card the profile names (not a larger card capped to
    its limits), served both the judge and the verifier, ran them the way the profile does (sleep swap or resident)
    and at the profile's context length.
    """
    rule = PROFILES.get(profile)
    if rule is None:
        return [f"no measurement rule for profile {profile}"]
    why = validate(rec)
    card = rec.get("card") or {}
    want = rule["card"]
    if not any(c in str(card.get("name", "")) for c in (want, *rule.get("also", ()))):
        why.append(f"card is {card.get('name') or '?'}, not an {want}")
    if card.get("capped_to"):
        why.append(f"measured on a capped card ({card['capped_to']}), not on the {want} itself")
    servers = rec.get("servers") or []
    roles = {s.get("role") for s in servers}
    why += [f"no {r} server in the record" for r in ROLES if r not in roles]
    for srv in servers:
        who = srv.get("role") or "?"
        sleeps = "--enable-sleep-mode" in (srv.get("extra_args") or [])
        if rule["sleep"] and not sleeps:
            why.append(f"{who} ran without --enable-sleep-mode")
        if not rule["sleep"] and sleeps:
            why.append(f"{who} ran with --enable-sleep-mode (this profile keeps both resident)")
        n, want_len = srv.get("max_model_len"), rule["min_len"]
        if rule.get("mig"):
            want_len = None
            why += _mig_problems(srv, card)
            prof = srv.get("mig_profile") or card.get("mig_profile")
            if prof:
                want_len = MIG_MIN_LEN.get(mig_base(str(prof)))
        if isinstance(n, int) and want_len is not None and n < want_len:
            why.append(f"{who} context {n} < {want_len}")
    if rule.get("mig"):
        devs = [tuple(s.get("gpu_devices") or []) for s in servers]
        if len(devs) == 2 and devs[0] and devs[0] == devs[1]:
            why.append(f"judge and verifier ran on one device {devs[0][0]}: time-sliced, not two MIG instances (D-409)")
    return why


def _mig_problems(srv: dict[str, Any], card: dict[str, Any]) -> list[str]:
    """Why one server of a shared-quota record did not run on its own MIG instance of a profile with a rule."""
    who = srv.get("role") or "?"
    devs = [str(d) for d in srv.get("gpu_devices") or []]
    if card.get("mig") is False:
        return [f"{who}: the card ran with MIG off (a whole card or a time-slice, not a MIG instance)"]
    if len(devs) != 1 or not devs[0].startswith("MIG-"):
        return [f"{who} ran on {devs or 'no named device'}, not on one MIG instance (MIG-<uuid>)"]
    prof = srv.get("mig_profile") or card.get("mig_profile")
    if not prof:
        return [f"{who}: no mig_profile in the record"]
    if mig_base(str(prof)) not in MIG_MIN_LEN:
        return [f"{who}: no rule for MIG profile {prof} (MIG_MIN_LEN)"]
    return []


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
    try:  # D-409: MIG mode, and the instances by UUID (each server's device names its profile)
        mode = _run(["nvidia-smi", "--query-gpu=mig.mode.current", "--format=csv,noheader"]).splitlines()
        card["mig"] = bool(mode) and mode[0].strip().lower() == "enabled"
    except (subprocess.CalledProcessError, FileNotFoundError):
        card["mig"] = False
    return card, sum(int(r[2]) for r in rows)


def mig_instances() -> dict[str, str]:
    try:
        return parse_mig_list(_run(["nvidia-smi", "-L"]))
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}


def server_info(role: str, container: str, models_dir: Path) -> dict[str, Any]:
    ins = json.loads(_run(["docker", "inspect", container]))[0]
    args = list(ins.get("Args") or [])
    rec: dict[str, Any] = {"role": role, "container": container, "image": ins["Config"]["Image"]}
    rec.update(parse_args(args))
    try:  # the registry digests of the image that ran (D-348: the lock's vLLM entry names the same)
        rec["image_digests"] = json.loads(
            _run(["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", ins["Image"]])
        )
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        rec["image_digests"] = []
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
    rec["chat_template_sha256"] = template_sha256(models_dir, rec.get("chat_template"))
    rec["gpu_devices"] = [
        str(d) for req in (ins.get("HostConfig") or {}).get("DeviceRequests") or [] for d in req.get("DeviceIDs") or []
    ]
    migs = mig_instances() if any(d.startswith("MIG-") for d in rec["gpu_devices"]) else {}
    profs = {migs[d] for d in rec["gpu_devices"] if d in migs}
    rec["mig_profile"] = profs.pop() if len(profs) == 1 else None
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
    m = sub.add_parser("measured", help="is the record a measurement of this GPU profile on its own card (install.sh)")
    m.add_argument("profile", choices=sorted(PROFILE_CARDS))
    m.add_argument("record", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "capture":
        pairs = [tuple(x.split("=", 1)) if "=" in x else (x, x) for x in a.container]
        rec = capture([(str(r), str(n)) for r, n in pairs], a.models_dir, a.capped_to, a.notes)
        a.out.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        missing = validate(rec)
        print(f"wrote {a.out}" + (f"; incomplete: {', '.join(missing)}" if missing else "; complete"))
        return 1 if missing else 0
    rec = json.loads(a.record.read_text(encoding="utf-8"))
    if a.cmd == "measured":
        why = measured_for(rec, a.profile)
        print(f"measured on {a.profile}" if not why else "not a measurement of this profile: " + "; ".join(why))
        return 1 if why else 0
    missing = validate(rec)
    print("complete" if not missing else "missing: " + ", ".join(missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
