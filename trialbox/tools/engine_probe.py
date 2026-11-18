"""The engine probe (card 24-4, root review 24): can the model engine use this card on this driver? No model.

For a host whose NVIDIA driver is older than the pinned engine image needs (the owner's IGX Orin developer kit with an
RTX A6000 on driver 535; the pinned vLLM image is a CUDA 13 build that wants 580), this answers one question before
any model is fetched: does the engine start and compute on the card, and in which form. It pulls one engine image at
a time, runs a short Python check inside it (no model, no network), removes the image again, and tries:

=================  ==================================================================================================
``pinned``         the image of ``deploy/images.lock`` as it is
``pinned+compat``  the same image with the vendor's CUDA compatibility switch (``VLLM_ENABLE_CUDA_COMPATIBILITY=1``)
``pinned+libs``    the same image with its CUDA compatibility libraries put first by hand (``/usr/local/cuda/compat``)
``cu129``          the same engine release's CUDA 12.9 build (:data:`CU129`): NOT pinned, read from the registry on
                   2026-11-18 by root review 24, to be verified on the machine; it is never written to images.lock
=================  ==================================================================================================

Inside each, the check imports the engine and torch, asks torch for the card, multiplies two small matrices on it
and loads the engine's compiled kernels (``vllm._C``, ``vllm._moe_C``): "the card is seen" is not enough, a kernel
must run. It prints one table and writes one small JSON file (``--out``) to paste back. The file holds no host name,
no serial or UUID, no address and no user name: the card's model, its memory, the driver, the architecture and the
results; error text is cut short and scrubbed (:func:`scrub`).

    python3 tools/engine_probe.py run --out ~/tb-engine-probe.json      # about 1 hour; ~25 GB of disk per image
    python3 tools/engine_probe.py run --dry-run                         # the commands only; nothing is pulled
    python3 tools/engine_probe.py show ~/tb-engine-probe.json           # the table again

Each image is about 10 to 12 GB to download and about 25 GB unpacked: the probe refuses to pull with less than
``--min-free-gb`` (30) free under Docker's folder, and removes each image it pulled before the next one (an image that
was already there is left). Standard library only, Python 3.9 or newer: the host's own ``python3`` runs it (Ubuntu
22.04 has 3.10), no project environment. Exit 0 when a form runs (the verdict names it), 1 when none does, 2 on a
usage error. Nothing here is a supported profile: the result decides whether the measuring run of runbook §29 is
worth the disk (``tools/dgpu48_measure.py`` reads this file's verdict).
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "deploy" / "images.lock"
SCHEMA = "tb-engine-probe/1"
# The same release's CUDA 12.9 build, as root review 24 read it from Docker Hub's registry API on 2026-11-18 (tag
# and multi-arch index digest; it has an arm64 manifest built for 8.0 8.7 8.9 9.0 10.0 12.0). To be verified on the
# machine: the probe pulls it by this digest and records the digests Docker reports. Not in deploy/images.lock: moving
# the engine is a model change (requalify first).
CU129 = "vllm/vllm-openai:v0.32.0-cu129@sha256:bc0445dac61accbf1c3b17fbb524a71eee0b1b32f55ba45952095e3be8991c3f"
COMPAT_DIR = "/usr/local/cuda/compat"
MATMUL_WANT = 262144.0  # ones(64, 64) @ ones(64, 64), summed: 64 * 64 * 64
MIN_FREE_GB = 30
# The check run inside the engine image with its own python3: one line "TBPROBE {json}" whatever fails
PROBE_PY = r"""
import glob, json, os
r = {"compat_dir": os.path.isdir("/usr/local/cuda/compat"),
     "compat_libs": sorted(os.path.basename(p) for p in glob.glob("/usr/local/cuda/compat/libcuda.so*"))}
def step(name, fn):
    try:
        r[name] = fn()
    except BaseException as e:
        r[name + "_error"] = (type(e).__name__ + ": " + str(e))[:400]
step("vllm", lambda: __import__("vllm").__version__)
try:
    import torch
except BaseException as e:
    r["torch_error"] = (type(e).__name__ + ": " + str(e))[:400]
    torch = None
if torch is not None:
    step("torch", lambda: torch.__version__)
    step("torch_cuda", lambda: torch.version.cuda)
    step("available", lambda: bool(torch.cuda.is_available()))
    step("device", lambda: torch.cuda.get_device_name(0))
    step("capability", lambda: "%d.%d" % torch.cuda.get_device_capability(0))
    step("matmul", lambda: float((torch.ones(64, 64, device="cuda") @ torch.ones(64, 64, device="cuda")).sum().item()))
    step("vllm_ops", lambda: bool(__import__("vllm._C")))
    step("vllm_moe_ops", lambda: bool(__import__("vllm._moe_C")))
print("TBPROBE " + json.dumps(r, sort_keys=True))
"""
TESTS: list[dict[str, Any]] = [
    {"name": "pinned", "image": "pinned", "env": {}, "prefix": ""},
    {"name": "pinned+compat", "image": "pinned", "env": {"VLLM_ENABLE_CUDA_COMPATIBILITY": "1"}, "prefix": ""},
    {"name": "pinned+libs", "image": "pinned", "env": {},
     "prefix": f"LD_LIBRARY_PATH={COMPAT_DIR}:${{LD_LIBRARY_PATH:-}}"},
    {"name": "cu129", "image": "cu129", "env": {}, "prefix": ""},
]  # fmt: skip
# what each status means, for the table and the page (runbook §29)
MEANING = {
    "PASS": "the engine imports, sees the card, runs a kernel and loads its compiled kernels",
    "PARTIAL": "the card is seen but a kernel or the engine's compiled kernels fail (see the error)",
    "DRIVER": "the CUDA runtime in the image refuses this driver",
    "NO-GPU": "Docker gave the container no GPU (the NVIDIA container runtime)",
    "PULL-FAILED": "the image could not be downloaded (network, or the digest is gone)",
    "DISK": "not enough free disk under Docker's folder to pull the image",
    "ERROR": "the check did not finish (see the error)",
    "NOT-RUN": "not tried (--only, or an earlier step stopped it)",
}
Runner = Callable[[list[str], int], tuple[int, str, str]]


# ------------------------------------------------------------------------------------------------ pure parts (tested)
_H = "[0-9a-fA-F]{1,4}"  # one IPv6 group
_SCRUB = [
    (re.compile(r"\b(?:GPU|MIG)-[0-9a-fA-F-]{8,}\b"), "<uuid>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<address>"),
    (re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"), "<mac>"),
    (re.compile(rf"(?<![0-9A-Za-z:])(?:{_H}:){{7}}{_H}(?![0-9A-Za-z:])"), "<address>"),
    (
        re.compile(rf"(?<![0-9A-Za-z:])(?:{_H}(?::{_H}){{0,6}})?::(?:{_H}(?::{_H}){{0,6}})?(?![0-9A-Za-z:])"),
        "<address>",
    ),
    (re.compile(r"/(home|Users)/[^/\s'\"]+"), r"/\1/<user>"),
    (re.compile(r"/root\b"), "/<root-home>"),
    (re.compile(r"(?i)\b(serial(?: number)?|hostname|host)\s*[:=]\s*\S+"), r"\1: <hidden>"),
]


def scrub(text: str, limit: int = 400, hostname: str = "") -> str:
    """Error text safe to paste in public: the host's name, UUIDs, addresses, MACs and home folders replaced, cut
    to the last ``limit`` characters (the end of an error says what failed)."""
    out = text or ""
    if hostname:
        out = re.sub(re.escape(hostname), "<host>", out, flags=re.IGNORECASE)
    for pat, rep in _SCRUB:
        out = pat.sub(rep, out)
    out = " ".join(out.split())
    return out[-limit:]


def scrub_probe(found: dict[str, Any] | None, hostname: str = "") -> dict[str, Any] | None:
    """The check's own result with every text in it scrubbed (its error fields carry the engine's messages)."""
    if found is None:
        return None
    return {k: scrub(v, hostname=hostname) if isinstance(v, str) else v for k, v in found.items()}


def parse_probe(stdout: str) -> dict[str, Any] | None:
    """The ``TBPROBE {json}`` line of the check, or None when the check printed none."""
    for line in reversed((stdout or "").splitlines()):
        if line.startswith("TBPROBE "):
            try:
                found = json.loads(line[len("TBPROBE ") :])
            except ValueError:
                return None
            return found if isinstance(found, dict) else None
    return None


_DRIVER_WORDS = re.compile(
    r"(?i)(driver version is insufficient|forward compatibility|cuda driver version|too old|older than|"
    r"\b804\b|\b803\b|unsatisfied condition: cuda|requires newer driver|system has unsupported display driver)"
)
_NO_GPU_WORDS = re.compile(
    r"(?i)(could not select device driver|unknown or invalid runtime name|no devices were found|"
    r"nvidia-container-cli: initialization error|failed to discover gpu)"
)


def classify(rc: int, stdout: str, stderr: str) -> tuple[str, dict[str, Any] | None, str]:
    """(status, the check's own result, the error that decided it) for one ``docker run`` of the check."""
    probe = parse_probe(stdout)
    if probe is None:
        err = stderr or stdout or f"exit {rc}"
        if _NO_GPU_WORDS.search(err):
            return "NO-GPU", None, err
        if _DRIVER_WORDS.search(err):
            return "DRIVER", None, err
        if re.search(r"(?i)no space left on device", err):
            return "DISK", None, err
        return "ERROR", None, err
    errors = " | ".join(f"{k}: {v}" for k, v in sorted(probe.items()) if k.endswith("_error"))
    seen = probe.get("available") is True
    ran = probe.get("matmul") == MATMUL_WANT
    ops = probe.get("vllm_ops") is True and probe.get("vllm_moe_ops") is True
    if seen and ran and ops and "vllm" in probe:
        return "PASS", probe, ""
    if seen:
        return "PARTIAL", probe, errors or "a kernel gave a wrong result"
    if _DRIVER_WORDS.search(errors) or _DRIVER_WORDS.search(stderr or ""):
        return "DRIVER", probe, errors or stderr
    if probe.get("available") is False:
        return "DRIVER", probe, errors or "torch.cuda.is_available() is False inside the image"
    return "ERROR", probe, errors or stderr


def verdict(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Which form of the engine to measure with, from the tests' statuses (first PASS in this order: the pinned image
    as it is, then with its compatibility switch, then with its libraries by hand, then the CUDA 12.9 build)."""
    by = {r["name"]: r["status"] for r in results}
    if by.get("pinned") == "PASS":
        return {"use": "pinned", "image": "pinned", "env": {}, "pinned_engine": True,
                "next": "The pinned engine runs as it is. Next: the measuring run (runbook §29 step 6)."}  # fmt: skip
    if by.get("pinned+compat") == "PASS":
        return {"use": "pinned+compat", "image": "pinned", "env": {"VLLM_ENABLE_CUDA_COMPATIBILITY": "1"},
                "pinned_engine": True,
                "next": "The pinned engine runs with its compatibility switch. Next: the measuring run (runbook §29 "
                        "step 6); the switch is recorded with the result."}  # fmt: skip
    if by.get("pinned+libs") == "PASS":
        return {"use": "pinned+libs", "image": "pinned", "env": {"LD_LIBRARY_PATH": COMPAT_DIR},
                "pinned_engine": True,
                "next": "The pinned engine runs only with its compatibility libraries put first by hand. Next: the "
                        "measuring run (runbook §29 step 6); this setting is recorded with the result."}  # fmt: skip
    if by.get("cu129") == "PASS":
        return {"use": "cu129", "image": "cu129", "env": {}, "pinned_engine": False,
                "next": "Only the CUDA 12.9 build of the same engine release runs. It is not the pinned engine: a "
                        "measuring run with it is evidence for a later model change, not a profile. Next: the "
                        "measuring run (runbook §29 step 6) reads this verdict, if you have the disk."}  # fmt: skip
    partial = [n for n, s in by.items() if s == "PARTIAL"]
    note = f" {', '.join(partial)}: the card is seen but a kernel fails." if partial else ""
    return {"use": None, "image": None, "env": {}, "pinned_engine": False,
            "next": "No form of the engine computes on this card with this driver." + note + " Stop here: send the "
                    "file. The real models cannot run on this machine with this engine release."}  # fmt: skip


def table(rec: dict[str, Any]) -> str:
    """The probe's result as a plain-text table, then the verdict."""
    host = rec.get("host") or {}
    lines = [
        f"engine probe ({rec.get('schema')}), {rec.get('at', '')}",
        f"host: {host.get('arch')} | {host.get('card')} | {host.get('memory_total_mib')} MiB | driver "
        f"{host.get('driver')} | compute {host.get('compute_cap')} | Docker {host.get('docker')} | nvidia runtime "
        f"{'yes' if host.get('nvidia_runtime') else 'no'}",
        "",
        f"{'test':<15} {'status':<12} {'engine':<9} {'torch/CUDA':<20} {'card seen':<10} {'kernel':<7} detail",
    ]
    for r in rec.get("tests") or []:
        p = r.get("probe") or {}
        tc = f"{p.get('torch', '-')}/{p.get('torch_cuda', '-')}" if p else "-"
        seen = "yes" if p.get("available") is True else ("no" if p.get("available") is False else "-")
        kern = "ok" if p.get("matmul") == MATMUL_WANT else ("-" if not p else "fail")
        detail = r.get("error") or MEANING.get(r["status"], "")
        lines.append(f"{r['name']:<15} {r['status']:<12} {p.get('vllm', '-')!s:<9} {tc:<20} {seen:<10} {kern:<7} "
                     f"{detail[:110]}")  # fmt: skip
    v = rec.get("verdict") or {}
    lines += ["", f"verdict: {v.get('use') or 'none'}", v.get("next", "")]
    return "\n".join(lines)


def pinned_ref(lock_path: Path = LOCK) -> str:
    entry = json.loads(lock_path.read_text(encoding="utf-8"))["third_party"]["vllm"]
    return f"{entry['image']}@{entry['digest']}"


def run_command(test: dict[str, Any], ref: str, gpu_args: list[str]) -> list[str]:
    """``docker run`` of the check for one test: no network, the card, the check in an environment variable."""
    env = [x for k, v in sorted(test["env"].items()) for x in ("-e", f"{k}={v}")]
    inner = f'{test["prefix"]} python3 -c "$ENGINE_PROBE_PY"'.strip()
    return ["docker", "run", "--rm", "--network", "none", *gpu_args, *env, "-e", "ENGINE_PROBE_PY",
            "--entrypoint", "bash", ref, "-c", inner]  # fmt: skip


# ------------------------------------------------------------------------------------------------ the machine
def _real_runner(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    env = None
    if "ENGINE_PROBE_PY" in cmd:
        import os

        env = {**os.environ, "ENGINE_PROBE_PY": PROBE_PY}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, env=env)
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout} s"
    return p.returncode, p.stdout, p.stderr


def host_facts(run: Runner) -> dict[str, Any]:
    """What the result needs to be read, and nothing that names the machine."""
    facts: dict[str, Any] = {"arch": platform.machine()}
    rc, out, _ = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_cap",
                      "--format=csv,noheader,nounits"], 60)  # fmt: skip
    if rc == 0 and out.strip():
        cells = [c.strip() for c in out.strip().splitlines()[0].split(",")]
        cells += [""] * (4 - len(cells))
        facts.update(card=cells[0], memory_total_mib=int(cells[1]) if cells[1].isdigit() else cells[1],
                     driver=cells[2], compute_cap=cells[3])  # fmt: skip
    else:
        facts.update(card=None, memory_total_mib=None, driver=None, compute_cap=None)
    rc, out, _ = run(["docker", "version", "--format", "{{.Server.Version}}"], 60)
    facts["docker"] = out.strip() if rc == 0 else None
    rc, out, _ = run(["docker", "info", "--format", "{{json .Runtimes}}"], 60)
    facts["nvidia_runtime"] = rc == 0 and "nvidia" in out
    return facts


def free_gb(run: Runner) -> float | None:
    rc, root, _ = run(["docker", "info", "--format", "{{.DockerRootDir}}"], 60)
    where = root.strip() if rc == 0 and root.strip() else "/var/lib/docker"
    rc, out, _ = run(["df", "-Pk", where], 60)
    try:
        return round(int(out.strip().splitlines()[-1].split()[3]) / 1048576, 1) if rc == 0 else None
    except (IndexError, ValueError):
        return None


def probe(
    run: Runner,
    only: list[str] | None = None,
    keep: bool = False,
    min_free: float = MIN_FREE_GB,
    gpu_args: list[str] | None = None,
    pinned: str = "",
    hostname: str = "",
    say: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run the tests one image at a time and return the result record (no file written here)."""
    refs = {"pinned": pinned or pinned_ref(), "cu129": CU129}
    gpus = gpu_args if gpu_args is not None else ["--gpus", "all"]
    rec: dict[str, Any] = {
        "schema": SCHEMA,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 (the host's Python 3.9+)
        "host": host_facts(run),
        "images": {},
        "tests": [],
    }
    rec["host"]["free_gb_before"] = free_gb(run)
    wanted = [t for t in TESTS if not only or t["name"] in only]
    for image in ("pinned", "cu129"):
        tests = [t for t in wanted if t["image"] == image]
        if not tests:
            continue
        ref = refs[image]
        info: dict[str, Any] = {"ref": ref, "verified_in_lock": image == "pinned"}
        rec["images"][image] = info
        had, _, _ = run(["docker", "image", "inspect", ref], 60)
        info["was_present"] = had == 0
        if had != 0:
            free = free_gb(run)
            if free is not None and free < min_free:
                say(f"  {image}: {free} GB free under Docker's folder, {min_free} GB needed: not pulled")
                rec["tests"] += [{"name": t["name"], "status": "DISK", "probe": None,
                                  "error": f"{free} GB free, {min_free} GB needed"} for t in tests]  # fmt: skip
                continue
            say(f"  pulling {image} ({ref.split('@')[0]}): 10 to 12 GB, often 20 to 40 minutes")
            rc, _, err = run(["docker", "pull", ref], 7200)
            if rc != 0:
                rec["tests"] += [{"name": t["name"], "status": "PULL-FAILED", "probe": None,
                                  "error": scrub(err, hostname=hostname)} for t in tests]  # fmt: skip
                continue
        rc, out, _ = run(["docker", "image", "inspect", "--format", "{{json .RepoDigests}}|{{.Size}}", ref], 60)
        if rc == 0 and "|" in out:
            digests, size = out.strip().rsplit("|", 1)
            try:
                info["repo_digests"] = json.loads(digests)
            except ValueError:
                info["repo_digests"] = []
            info["size_gb"] = round(int(size) / 1e9, 1) if size.strip().isdigit() else None
            info["digest_matches"] = any(d.endswith(ref.split("@", 1)[1]) for d in info["repo_digests"])
        for t in tests:
            say(f"  checking {t['name']}")
            rc, out, err = run(run_command(t, ref, gpus), 900)
            status, found, why = classify(rc, out, err)
            rec["tests"].append({"name": t["name"], "status": status, "probe": scrub_probe(found, hostname),
                                 "env": t["env"], "libs_first": bool(t["prefix"]),
                                 "error": scrub(why, hostname=hostname) if why else ""})  # fmt: skip
        if not keep and not info["was_present"]:
            run(["docker", "image", "rm", ref], 600)
            info["removed"] = True
    done = {r["name"] for r in rec["tests"]}
    rec["tests"] += [{"name": t["name"], "status": "NOT-RUN", "probe": None, "error": ""} for t in TESTS
                     if t["name"] not in done]  # fmt: skip
    rec["tests"].sort(key=lambda r: [t["name"] for t in TESTS].index(r["name"]))
    rec["verdict"] = verdict(rec["tests"])
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="pull, check, remove: one engine image at a time (about 1 hour)")
    r.add_argument("--out", type=Path, default=Path.home() / "tb-engine-probe.json")
    r.add_argument("--only", default="", help=f"comma-separated tests ({', '.join(t['name'] for t in TESTS)})")
    r.add_argument("--keep-images", action="store_true", help="leave the pulled images (needs about 50 GB)")
    r.add_argument("--min-free-gb", type=float, default=MIN_FREE_GB)
    r.add_argument("--gpu-args", default="--gpus all", help="how docker run is given the card (default --gpus all)")
    r.add_argument("--dry-run", action="store_true", help="print the commands; run nothing")
    s = sub.add_parser("show", help="print the table of a result file")
    s.add_argument("file", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "show":
        rec = json.loads(a.file.read_text(encoding="utf-8"))
        print(table(rec))
        return 0 if (rec.get("verdict") or {}).get("use") else 1
    only = [x.strip() for x in a.only.split(",") if x.strip()]
    unknown = sorted(set(only) - {t["name"] for t in TESTS})
    if unknown:
        print(f"engine_probe: unknown test {', '.join(unknown)}", file=sys.stderr)
        return 2
    gpu_args = shlex.split(a.gpu_args)
    if a.dry_run:
        refs = {"pinned": pinned_ref(), "cu129": CU129}
        for t in TESTS:
            if not only or t["name"] in only:
                print(f"docker pull {refs[t['image']]}  # once per image, removed after its tests")
                print(" ".join(shlex.quote(x) for x in run_command(t, refs[t["image"]], gpu_args)))
        print("(the check itself, passed as ENGINE_PROBE_PY:)" + PROBE_PY)
        return 0
    print("engine probe: no model is loaded; each image is pulled, checked and removed in turn")
    rec = probe(_real_runner, only or None, a.keep_images, a.min_free_gb, gpu_args,
                hostname=platform.node())  # fmt: skip
    a.out.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print()
    print(table(rec))
    print(f"\nwritten: {a.out} (send this file: it names no host, serial, address or user)")
    return 0 if rec["verdict"]["use"] else 1


if __name__ == "__main__":
    sys.exit(main())
