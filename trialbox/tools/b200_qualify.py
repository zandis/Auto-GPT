"""G1b on the owner's B200 (T-114, D-428): the offline bundle, the host fingerprint and the G1b record.

The owner (or the named operator, Q-12) runs ``tools/b200_qualify.sh`` on the B200 itself. No ``gcloud``, no rental,
no network: everything the run needs comes in one bundle built here, on a development machine::

    python -m tools.b200_qualify build --out /media/usb/tb-b200.tar.gz \\
        --image vllm=<docker save tarball> --weights judge=<folder> --weights verifier=<folder>

The bundle holds the code at a commit (``git archive``), the image tarballs, the weight folders, the two MIG layouts
(``eval/qualification/b200-layouts.json``) and ``MANIFEST.json`` (sha256 and size of every file). Its own sha256 is
written next to it (``<bundle>.sha256``); send that by another channel. On the host the script checks the sha256, then
``verify`` checks every file against the manifest before anything runs.

The host fingerprint (schema ``tb-host-fingerprint/1``) is what makes a qualification on one machine comparable with
another (OPS-071, RSK-52): GPU name and count, memory, driver, CUDA, VBIOS, MIG mode and the MIG layout (the profiles
of the GPU instances), kernel, OS, container toolkit, docker, and the vLLM image digests. ``host_id`` is a sha256 of
the GPU UUIDs, not a hostname. :func:`compare` lists the fields where two fingerprints differ; it compares only the
fields both sides have. ``doctor --platform`` (``host_match``) uses it to warn when the platform differs from the
host the serving record was taken on.

Each layout's serving record (``tools/serving_config.py capture``) is stamped with that layout's fingerprint
(``host_fingerprint``). The G1b record (schema ``tb-b200-qualification/1``,
``schemas/b200_qualification_record.schema.json``) collects both layouts: fingerprint, serving record (sha256 and
whether it measures ``shared-quota``), qualification record (sha256 and status) and the two throughput numbers of
LLM-025 when the run gave them. It states that the host is not CGMH's. Its status is ``passed`` only when both
layouts are measured and qualified; a run with stand-ins (``TB_B200_STANDIN=1``, the tests) is ``standin``, never
``passed``.

Stdlib only (Python 3.11+): it runs from the bundle on the host as ``python3 -m tools.b200_qualify``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools import serving_config as sc

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS = ROOT / "eval" / "qualification" / "b200-layouts.json"
SCHEMA = "tb-b200-qualification/1"
FP_SCHEMA = "tb-host-fingerprint/1"
BUNDLE_SCHEMA = "tb-b200-bundle/1"
MANIFEST = "MANIFEST.json"
# the fields doctor --platform compares (OPS-071): the ones that change what the serving record predicts
COMPARED = (
    "gpu_name",
    "gpu_count",
    "memory_total_mib",
    "driver",
    "cuda",
    "vbios",
    "mig_mode",
    "mig_layout",
    "kernel",
    "os",
    "container_toolkit",
    "vllm_image_digests",
)
FP_FIELDS = ("host_id", "docker", *COMPARED)
THROUGHPUT = ("note_stage_share", "note_stage_s_p50", "note_stage_s_p95", "criterion_s_p50", "criterion_s_p95")
NOT_SITE = (
    "This host is the owner's B200, not CGMH's partition. The record predicts CGMH only where the fingerprints "
    "match; doctor --platform compares them at IQ and warns where they differ (RSK-52)."
)
QUERY = "name,uuid,memory.total,driver_version,vbios_version,mig.mode.current"
# what the host is asked; each answer is kept as a raw file next to the fingerprint (evidence)
COMMANDS: dict[str, list[str]] = {
    "query": ["nvidia-smi", f"--query-gpu={QUERY}", "--format=csv,noheader,nounits"],
    "banner": ["nvidia-smi"],
    "list": ["nvidia-smi", "-L"],
    "kernel": ["uname", "-r"],
    "toolkit": ["nvidia-ctk", "--version"],
    "docker": ["docker", "version", "--format", "{{.Server.Version}}"],
}


# ---------------------------------------------------------------- layouts
def load_layouts(path: Path = LAYOUTS) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = list(doc.get("layouts") or [])
    names = [x.get("name") for x in out]
    if len(out) != 2 or len(set(names)) != 2:
        raise ValueError(f"{path}: G1b qualifies exactly two layouts (D-428), found {names}")
    for lay in out:
        for role in sc.ROLES:
            prof = str((lay.get(role) or {}).get("mig_profile") or "")
            if sc.mig_base(prof) not in sc.MIG_MIN_LEN:
                raise ValueError(f"{path}: {lay.get('name')}.{role}: no rule for MIG profile {prof!r}")
    return out


def layout(name: str, path: Path = LAYOUTS) -> dict[str, Any]:
    for lay in load_layouts(path):
        if lay["name"] == name:
            return lay
    raise ValueError(f"no layout {name!r} in {path}")


def layout_profile(lay: Mapping[str, Any]) -> str:
    """The layout as ``TB_MIG_PROFILE`` names it (``judge=2g.45gb,verifier=1g.23gb``)."""
    return ",".join(f"{r}={lay[r]['mig_profile']}" for r in sc.ROLES)


def assign_devices(list_text: str, lay: Mapping[str, Any]) -> dict[str, str]:
    """``nvidia-smi -L`` after partitioning -> ``{role: MIG instance UUID}``, one instance per role (D-409)."""
    free = dict(sc.parse_mig_list(list_text))
    out: dict[str, str] = {}
    for role in sc.ROLES:
        want = sc.mig_base(lay[role]["mig_profile"])
        uuid = next((u for u, p in free.items() if sc.mig_base(p) == want), None)
        if uuid is None:
            raise ValueError(f"no free MIG instance of profile {want} for the {role} (nvidia-smi -L)")
        out[role] = uuid
        del free[uuid]
    return out


def serve_env(lay: Mapping[str, Any], devices: Mapping[str, str]) -> dict[str, str]:
    """The values ``deploy/docker-compose.shared-quota.yml`` requires, for this layout."""
    env = {"TB_GPU_PROFILE": "shared-quota", "TB_MIG_PROFILE": layout_profile(lay)}
    for role, prefix in (("judge", "JUDGE"), ("verifier", "VERIFIER")):
        srv = lay[role]
        env[f"TB_MIG_{prefix}_DEVICE"] = devices[role]
        env[f"{prefix}_MAX_LEN"] = str(srv["max_len"])
        env[f"{prefix}_MAX_SEQS"] = str(srv["max_seqs"])
        env[f"{prefix}_GPU_MEM_UTIL"] = str(srv["gpu_mem_util"])
    return env


# ---------------------------------------------------------------- fingerprint
def _first_line(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


def parse_os_release(text: str) -> str:
    m = re.search(r'^PRETTY_NAME="?([^"\n]*)"?', text, re.M)
    return m.group(1).strip() if m else ""


def parse_cuda(banner: str) -> str:
    m = re.search(r"CUDA Version:\s*([0-9.]+)", banner)
    return m.group(1) if m else ""


def parse_toolkit(text: str) -> str:
    m = re.search(r"version\s+([0-9][0-9A-Za-z.~+-]*)", text, re.I)
    return m.group(1) if m else _first_line(text)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(
    raw: Mapping[str, str], *, vllm_digests: list[str] | None = None, at: str | None = None
) -> dict[str, Any]:
    """The fingerprint from the raw answers of :data:`COMMANDS` (plus ``os_release``)."""
    rows = [[c.strip() for c in ln.split(",")] for ln in raw.get("query", "").splitlines() if ln.strip()]
    rows = [r for r in rows if len(r) >= 6]
    first = rows[0] if rows else [""] * 6
    names = sorted({r[0] for r in rows})
    modes = sorted({r[5].lower() for r in rows})
    migs = sorted(sc.mig_base(p) for p in sc.parse_mig_list(raw.get("list", "")).values())
    try:
        mem: int | None = int(float(first[2]))
    except ValueError:
        mem = None
    fp: dict[str, Any] = {
        "schema": FP_SCHEMA,
        "captured_at": at or datetime.now(UTC).isoformat(timespec="seconds"),
        "host_id": _sha("\n".join(sorted(r[1] for r in rows)))[:16] if rows else "",
        "gpu_name": " / ".join(names),
        "gpu_count": len(rows),
        "memory_total_mib": mem,
        "driver": first[3],
        "cuda": parse_cuda(raw.get("banner", "")),
        "vbios": first[4],
        "mig_mode": "/".join(modes),
        "mig_layout": migs,
        "kernel": _first_line(raw.get("kernel", "")),
        "os": parse_os_release(raw.get("os_release", "")),
        "container_toolkit": parse_toolkit(raw.get("toolkit", "")),
        "docker": _first_line(raw.get("docker", "")),
        "vllm_image_digests": sorted(vllm_digests or []),
    }
    fp["fingerprint_sha256"] = fingerprint_sha256(fp)
    return fp


def fingerprint_sha256(fp: Mapping[str, Any]) -> str:
    """sha256 over the compared fields (canonical JSON): equal hosts give equal hashes."""
    return _sha(json.dumps({k: fp.get(k) for k in COMPARED}, sort_keys=True, separators=(",", ":")))


def collect_raw(
    run: Callable[[list[str]], str] | None = None, os_release: Path = Path("/etc/os-release")
) -> dict[str, str]:
    """Ask the host (:data:`COMMANDS`); a command that is missing or fails answers ``""``."""

    def _run(cmd: list[str]) -> str:
        try:
            return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    ask = run or _run
    raw = {k: ask(cmd) for k, cmd in COMMANDS.items()}
    raw["os_release"] = os_release.read_text(encoding="utf-8") if os_release.is_file() else ""
    return raw


def image_digests(image: str, run: Callable[[list[str]], str] | None = None) -> list[str]:
    """The registry digests of a loaded image (``docker image inspect``), ``[]`` when unknown."""
    if not image:
        return []
    cmd = ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image]
    try:
        out = run(cmd) if run else subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
        return sorted(str(d) for d in json.loads(out or "[]"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def _norm(v: Any) -> str:
    return re.sub(r"[^0-9a-z.]", "", str(v).lower())


def _digest_ids(v: Any) -> set[str]:
    return {m.group(1) for d in v or [] for m in [re.search(r"sha256:([0-9a-f]{64})", str(d))] if m}


def compare(recorded: Mapping[str, Any], here: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(differences, fields compared). A field missing on either side is not compared."""
    diffs, seen = [], []
    for k in COMPARED:
        a, b = recorded.get(k), here.get(k)
        if a in (None, "", []) or b in (None, "", []):
            continue
        seen.append(k)
        if k == "mig_layout":
            same = sorted(sc.mig_base(str(x)) for x in a) == sorted(sc.mig_base(str(x)) for x in b)
        elif k == "vllm_image_digests":
            same = bool(_digest_ids(a) & _digest_ids(b))
        elif k in ("gpu_name", "os"):
            same = _norm(a) == _norm(b) or _norm(a) in _norm(b) or _norm(b) in _norm(a)
        elif k == "mig_mode":
            same = _norm(a).startswith("enabled") == _norm(b).startswith("enabled")
        else:
            same = _norm(a) == _norm(b)
        if not same:
            diffs.append(f"{k}: recorded {_show(a)}, here {_show(b)}")
    return diffs, seen


def _show(v: Any) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(str(x)[:24] for x in v) + "]"
    return str(v)


def fingerprint_from_node(node: Mapping[str, Any], images: list[str]) -> dict[str, Any]:
    """What a Kubernetes node says of its GPU (GPU feature discovery and node feature discovery labels, the MIG
    resources it offers), plus the vLLM images running there: the fields :func:`compare` can use."""
    lab = (node.get("metadata") or {}).get("labels") or {}
    alloc = ((node.get("status") or {}).get("allocatable")) or {}

    def joined(*keys: str) -> str:
        parts = [str(lab[k]) for k in keys if lab.get(k) not in (None, "")]
        return ".".join(parts) if len(parts) == len(keys) else ""

    migs: list[str] = []
    for res, qty in alloc.items():
        m = re.fullmatch(r"nvidia\.com/mig-(\d+g\.\d+gb(?:\+me)?)", str(res))
        if m:
            migs += [sc.mig_base(m.group(1))] * int(float(str(qty) or 0))
    strategy = str(lab.get("nvidia.com/mig.strategy") or "")
    count = str(lab.get("nvidia.com/gpu.count") or "")
    mem = str(lab.get("nvidia.com/gpu.memory") or "")
    fp: dict[str, Any] = {
        "gpu_name": str(lab.get("nvidia.com/gpu.product") or "").replace("-", " "),
        "gpu_count": int(count) if count.isdigit() else None,
        "memory_total_mib": int(mem) if mem.isdigit() and not migs else None,
        "driver": str(lab.get("nvidia.com/cuda.driver-version.full") or "")
        or joined("nvidia.com/cuda.driver.major", "nvidia.com/cuda.driver.minor", "nvidia.com/cuda.driver.rev"),
        "cuda": str(lab.get("nvidia.com/cuda.runtime-version.full") or "")
        or joined("nvidia.com/cuda.runtime.major", "nvidia.com/cuda.runtime.minor"),
        "mig_mode": "enabled" if strategy in ("single", "mixed") or migs else "",
        "mig_layout": sorted(migs),
        "kernel": str(lab.get("feature.node.kubernetes.io/kernel-version.full") or ""),
        "vllm_image_digests": sorted(i for i in images if "@sha256:" in i),
    }
    return fp


# ---------------------------------------------------------------- bundle
def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def build(
    out: Path,
    *,
    ref: str = "HEAD",
    code: Path | None = None,
    images: list[tuple[str, Path]] | None = None,
    weights: list[tuple[str, Path]] | None = None,
    layouts: Path = LAYOUTS,
) -> dict[str, Any]:
    """Write the offline bundle ``out`` (a .tar.gz) and ``out.sha256``; return its manifest."""
    load_layouts(layouts)
    files: dict[str, dict[str, Any]] = {}
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tb-b200-") as tmp, tarfile.open(out, "w:gz") as tar:
        if code is None:
            src = Path(tmp) / "code.tar"
            with src.open("wb") as fh:
                subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", ref], check=True, stdout=fh)
            commit: str | None = _git("rev-parse", ref)
            with tarfile.open(src) as code_tar:
                for m in code_tar.getmembers():
                    if not m.isfile():
                        continue
                    data = code_tar.extractfile(m)
                    assert data is not None
                    body = data.read()
                    m.name = f"code/{m.name}"
                    files[m.name] = {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
                    data.seek(0)
                    tar.addfile(m, data)
        else:
            commit = None
            for p in sorted(x for x in code.rglob("*") if x.is_file()):
                name = f"code/{p.relative_to(code).as_posix()}"
                files[name] = {"bytes": p.stat().st_size, "sha256": _hash_file(p)}
                tar.add(p, arcname=name)
        image_rows = []
        for ref_name, tarball in images or []:
            name = f"images/{tarball.name}"
            files[name] = {"bytes": tarball.stat().st_size, "sha256": _hash_file(tarball)}
            tar.add(tarball, arcname=name)
            image_rows.append({"name": ref_name, "file": name})
        weight_rows = []
        for build_name, folder in weights or []:
            for p in sorted(x for x in folder.rglob("*") if x.is_file()):
                name = f"weights/{build_name}/{p.relative_to(folder).as_posix()}"
                files[name] = {"bytes": p.stat().st_size, "sha256": _hash_file(p)}
                tar.add(p, arcname=name)
            listed = [
                {"path": k.split("/", 2)[2], **v} for k, v in files.items() if k.startswith(f"weights/{build_name}/")
            ]
            weight_rows.append(
                {"name": build_name, "dir": f"weights/{build_name}", "files_sha256": sc.files_digest(listed)}
            )
        name = "layouts.json"
        files[name] = {"bytes": layouts.stat().st_size, "sha256": _hash_file(layouts)}
        tar.add(layouts, arcname=name)
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "commit": commit,
            "code_source": "git archive" if code is None else "folder (not a commit: a stand-in, never a G1b pass)",
            "images": image_rows,
            "weights": weight_rows,
            "needs": "python3 3.11+, docker with compose, nvidia-smi, root for MIG; no network, no gcloud",
            "files": files,
        }
        body = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8")
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(body)
        info.mtime = int(datetime.now(UTC).timestamp())
        tar.addfile(info, io.BytesIO(body))
    Path(f"{out}.sha256").write_text(f"{_hash_file(out)}  {out.name}\n", encoding="utf-8")
    return manifest


def verify(bundle_dir: Path) -> list[str]:
    """Every file of the manifest is there with its size and sha256; nothing else is in the bundle."""
    mpath = bundle_dir / MANIFEST
    if not mpath.is_file():
        return [f"no {MANIFEST} in {bundle_dir}"]
    man = json.loads(mpath.read_text(encoding="utf-8"))
    bad = [] if man.get("schema") == BUNDLE_SCHEMA else [f"manifest schema is not {BUNDLE_SCHEMA}"]
    listed = man.get("files") or {}
    for name, meta in sorted(listed.items()):
        p = bundle_dir / name
        if not p.is_file():
            bad.append(f"{name}: missing")
        elif p.stat().st_size != meta.get("bytes") or _hash_file(p) != meta.get("sha256"):
            bad.append(f"{name}: sha256 or size differs from the manifest")
    for p in sorted(x for x in bundle_dir.rglob("*") if x.is_file()):
        rel = p.relative_to(bundle_dir).as_posix()
        if rel != MANIFEST and rel not in listed and "/__pycache__/" not in rel:
            bad.append(f"{rel}: not in the manifest")
    return bad


# ---------------------------------------------------------------- record
def stamp(serving_record: Path, fp: Mapping[str, Any]) -> None:
    """Put the layout's host fingerprint in its serving record (what doctor --platform compares)."""
    rec = json.loads(serving_record.read_text(encoding="utf-8"))
    rec["host_fingerprint"] = dict(fp)
    serving_record.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _read(p: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _file_ref(p: Path, base: Path) -> dict[str, Any]:
    return {"path": p.relative_to(base).as_posix(), "sha256": _hash_file(p) if p.is_file() else None}


def make_record(run_dir: Path, *, operator: str, standin: bool, layouts: Path = LAYOUTS) -> dict[str, Any]:
    """The G1b record from a run folder (``tools/b200_qualify.sh``'s layout, see the RUNBOOK section)."""
    man = _read(run_dir / "bundle" / MANIFEST) or {}
    host_fp = _read(run_dir / "host" / "fingerprint.json") or {}
    rows, failed = [], []
    for lay in load_layouts(layouts):
        d = run_dir / lay["name"]
        fp = _read(d / "fingerprint.json") or {}
        serving = _read(d / "serving_config.json")
        qual = _read(d / "qualification.json")
        tput = _read(d / "throughput.json") or {}
        why = []
        if not fp:
            why.append("no fingerprint")
        elif sorted(fp.get("mig_layout") or []) != sorted(sc.mig_base(lay[r]["mig_profile"]) for r in sc.ROLES):
            why.append(f"the host's MIG layout {fp.get('mig_layout')} is not the layout's {layout_profile(lay)}")
        measured = sc.measured_for(serving, "shared-quota") if serving else ["no serving record"]
        if serving and sc.record_layout(serving) != {r: lay[r]["mig_profile"] for r in sc.ROLES}:
            got = {r: sc.mig_base(p) for r, p in sc.record_layout(serving).items()}
            if got != {r: sc.mig_base(lay[r]["mig_profile"]) for r in sc.ROLES}:
                measured.append(f"the serving record ran on {got}, not on {layout_profile(lay)}")
        if serving and (serving.get("host_fingerprint") or {}).get("fingerprint_sha256") != fp.get(
            "fingerprint_sha256"
        ):
            measured.append("the serving record does not carry this layout's host fingerprint")
        why += measured
        q_status = (qual or {}).get("status") or "absent"
        if q_status != "passed":
            why.append(f"qualification {q_status}")
        status = "passed" if not why else "failed"
        failed += [f"{lay['name']}: {w}" for w in why]
        rows.append(
            {
                "name": lay["name"],
                "mig_profile": layout_profile(lay),
                "fingerprint": fp,
                "serving_record": {
                    **_file_ref(d / "serving_config.json", run_dir),
                    "measured": not measured,
                    "why": measured,
                },
                "qualification": {**_file_ref(d / "qualification.json", run_dir), "status": q_status},
                "throughput": {k: tput.get(k) for k in THROUGHPUT},
                "status": status,
            }
        )
    if not man.get("commit"):
        failed.append("the bundle's code is not a commit (git archive)")
    status = "standin" if standin else ("passed" if not failed else "failed")
    bundle_sha = (
        (run_dir / "bundle.sha256").read_text(encoding="utf-8").split()[0]
        if (run_dir / "bundle.sha256").is_file()
        else None
    )
    return {
        "schema": SCHEMA,
        "card": "T-114",
        "gate": "G1b",
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "operator": operator,
        "standin": standin,
        "host": {"kind": "owner-b200", "site_host": False, "statement": NOT_SITE},
        "bundle": {"sha256": bundle_sha, "commit": man.get("commit"), "built_at": man.get("built_at")},
        "fingerprint": host_fp,
        "layouts": rows,
        "status": status,
        "failed": failed,
    }


def problems(rec: Mapping[str, Any], layouts: Path = LAYOUTS) -> list[str]:
    """What makes a G1b record invalid (the schema's rules, stdlib only, plus the status rule)."""
    bad = [] if rec.get("schema") == SCHEMA else [f"schema is not {SCHEMA}"]
    host = rec.get("host") or {}
    if host.get("site_host") is not False or not host.get("statement"):
        bad.append("the record must state that the host is not the site's (host.site_host false, statement)")
    want = sorted(x["name"] for x in load_layouts(layouts))
    rows = rec.get("layouts") or []
    if sorted(str(r.get("name")) for r in rows) != want:
        bad.append(f"layouts must be exactly {want}")
    for r in rows:
        fp = r.get("fingerprint") or {}
        missing = [k for k in FP_FIELDS if k not in fp]
        if fp.get("schema") != FP_SCHEMA or missing:
            bad.append(f"{r.get('name')}: fingerprint incomplete ({', '.join(missing) or 'schema'})")
        elif fp.get("fingerprint_sha256") != fingerprint_sha256(fp):
            bad.append(f"{r.get('name')}: fingerprint_sha256 does not match its fields")
    st = rec.get("status")
    if st == "passed" and (rec.get("standin") or rec.get("failed") or any(r.get("status") != "passed" for r in rows)):
        bad.append("status passed with a stand-in, a failure or a failed layout")
    if st not in ("passed", "failed", "standin"):
        bad.append(f"status {st!r}")
    if rec.get("standin") and st != "standin":
        bad.append("a stand-in run must have status standin")
    return bad


def render(rec: Mapping[str, Any]) -> str:
    """The gate record ``G1b.md`` from the JSON record."""
    fp = rec.get("fingerprint") or {}
    bundle = rec.get("bundle") or {}
    lines = [
        "# G1b gate record: the model pair on the owner's B200 (T-114, D-428)",
        "",
        f"- **Status:** {rec.get('status')}" + (" (stand-in devices: never a pass)" if rec.get("standin") else ""),
        f"- **Captured:** {rec.get('captured_at')} by {rec.get('operator')}",
        f"- **Bundle:** commit {bundle.get('commit')}, sha256 {bundle.get('sha256')}",
        f"- **Host:** {(rec.get('host') or {}).get('statement')}",
        "",
        "## Host fingerprint (before partitioning)",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    lines += [f"| {k} | {_show(fp.get(k))} |" for k in FP_FIELDS]
    lines += [
        "",
        "## Layouts",
        "",
        "| Layout | MIG | Serving record | Qualification | Note-stage s p50 / p95 | Status |",
    ]
    lines += ["| --- | --- | --- | --- | --- | --- |"]
    for r in rec.get("layouts") or []:
        t = r.get("throughput") or {}
        sr, q = r.get("serving_record") or {}, r.get("qualification") or {}
        lines.append(
            f"| {r.get('name')} | {r.get('mig_profile')} | {'measured' if sr.get('measured') else 'not measured'} "
            f"| {q.get('status')} | {t.get('note_stage_s_p50')} / {t.get('note_stage_s_p95')} | {r.get('status')} |"
        )
    if rec.get("failed"):
        lines += ["", "## Why not passed", ""] + [f"- {w}" for w in rec["failed"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- CLI
def _pairs(values: list[str]) -> list[tuple[str, Path]]:
    out = []
    for v in values:
        name, _, path = v.partition("=")
        if not path:
            raise SystemExit(f"expected name=<path>, got {v!r}")
        out.append((name, Path(path)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="b200_qualify", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="on a development machine: write the offline bundle")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--ref", default="HEAD")
    b.add_argument("--code", type=Path, default=None, help="a folder instead of git archive (stand-in runs only)")
    b.add_argument("--image", action="append", default=[], help="name=<docker save tarball>")
    b.add_argument("--weights", action="append", default=[], help="build=<weight folder>")
    v = sub.add_parser("verify", help="on the host: check the unpacked bundle against its manifest")
    v.add_argument("bundle_dir", type=Path)
    i = sub.add_parser("images", help="the bundle's image tarballs, one per line")
    i.add_argument("bundle_dir", type=Path)
    sub.add_parser("layouts", help="the layout names, one per line")
    c = sub.add_parser("cgi", help="the profiles to create for a layout (nvidia-smi mig -cgi)")
    c.add_argument("layout")
    e = sub.add_parser("env", help="the compose values for a layout, from nvidia-smi -L after partitioning")
    e.add_argument("layout")
    e.add_argument("--list", type=Path, required=True, help="nvidia-smi -L output")
    f = sub.add_parser("fingerprint", help="on the host: write the host fingerprint and its raw answers")
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--vllm-image", default=os.environ.get("VLLM_IMAGE", ""))
    s = sub.add_parser("stamp", help="put a fingerprint into a serving record")
    s.add_argument("serving_record", type=Path)
    s.add_argument("fingerprint", type=Path)
    r = sub.add_parser("record", help="write the G1b record and G1b.md from a run folder")
    r.add_argument("run_dir", type=Path)
    r.add_argument("--operator", required=True)
    k = sub.add_parser("check", help="validate a G1b record")
    k.add_argument("record", type=Path)
    for p in (c, e, sub.choices["layouts"], r, k):
        p.add_argument("--layouts", type=Path, default=LAYOUTS)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        man = build(a.out, ref=a.ref, code=a.code, images=_pairs(a.image), weights=_pairs(a.weights))
        print(f"wrote {a.out} ({len(man['files'])} files, commit {man['commit']}) and {a.out}.sha256")
        return 0
    if a.cmd == "verify":
        bad = verify(a.bundle_dir)
        print("bundle verified" if not bad else "bundle refused:\n  " + "\n  ".join(bad))
        return 1 if bad else 0
    if a.cmd == "images":
        man = json.loads((a.bundle_dir / MANIFEST).read_text(encoding="utf-8"))
        print("\n".join(str(i["file"]) for i in man.get("images") or []))
        return 0
    if a.cmd == "layouts":
        print("\n".join(x["name"] for x in load_layouts(a.layouts)))
        return 0
    if a.cmd == "cgi":
        lay = layout(a.layout, a.layouts)
        print(",".join(lay[r]["mig_profile"] for r in sc.ROLES))
        return 0
    if a.cmd == "env":
        lay = layout(a.layout, a.layouts)
        env = serve_env(lay, assign_devices(a.list.read_text(encoding="utf-8"), lay))
        print("\n".join(f"{k}={v}" for k, v in sorted(env.items())))
        return 0
    if a.cmd == "fingerprint":
        raw = collect_raw()
        (a.out.parent / "raw").mkdir(parents=True, exist_ok=True)
        for name, text in raw.items():
            (a.out.parent / "raw" / f"{name}.txt").write_text(text, encoding="utf-8")
        fp = fingerprint(raw, vllm_digests=image_digests(a.vllm_image))
        a.out.write_text(json.dumps(fp, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{a.out}: {fp['gpu_name']} x{fp['gpu_count']}, driver {fp['driver']}, CUDA {fp['cuda']}, "
              f"MIG {fp['mig_mode']} {fp['mig_layout']}")  # fmt: skip
        return 0 if fp["gpu_count"] else 1
    if a.cmd == "stamp":
        stamp(a.serving_record, json.loads(a.fingerprint.read_text(encoding="utf-8")))
        return 0
    if a.cmd == "record":
        standin = os.environ.get("TB_B200_STANDIN") == "1"
        rec = make_record(a.run_dir, operator=a.operator, standin=standin, layouts=a.layouts)
        bad = problems(rec, a.layouts)
        out = a.run_dir / "g1b-record.json"
        out.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        (a.run_dir / "G1b.md").write_text(render(rec), encoding="utf-8")
        print(f"wrote {out} and G1b.md: {rec['status']}" + "".join(f"\n  {w}" for w in rec["failed"] + bad))
        return 0 if rec["status"] == "passed" and not bad else 1
    rec = json.loads(a.record.read_text(encoding="utf-8"))
    bad = problems(rec, a.layouts)
    print(f"{rec.get('status')}" if not bad else "invalid: " + "; ".join(bad))
    return 1 if bad or rec.get("status") != "passed" else 0


if __name__ == "__main__":
    sys.exit(main())
