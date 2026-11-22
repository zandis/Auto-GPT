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
22.04 has 3.10), no project environment. Exit 0 when a form runs (the verdict names it), 1 when every form
reached the card and none ran, 2 on a usage error, 3 when some form never reached the card (Docker, its NVIDIA
runtime, the network or the disk: the verdict is then ``inconclusive`` and names the one command that fixes it), 130
when interrupted. Nothing here is a supported profile: the result decides whether the measuring run of runbook §29 is
worth the disk (``tools/dgpu48.py`` reads this file's verdict, and the exact variant that passed).

Before any download it checks that Docker answers, that this user may use it, that Docker has the NVIDIA runtime and
that the disk has room: a missing piece is said at once, not after an hour of downloads. It stops at the first form
that passes (after a pinned pass the second image is never pulled). Each check runs in a container of a known name,
removed on a timeout or Ctrl-C; an image it pulled is removed and the removal is checked.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import hashlib
import json
import os
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
r = {"ld_library_path": os.environ.get("LD_LIBRARY_PATH", ""),
     "compat_dir": os.path.isdir("/usr/local/cuda/compat"),
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
    # NVIDIA_DISABLE_REQUIRE: the image declares cuda>=13.0, and the container toolkit refuses to create the container
    # on an older driver before the engine starts; the compatibility forms only make sense past that check
    {"name": "pinned+compat", "image": "pinned", "prefix": "",
     "env": {"NVIDIA_DISABLE_REQUIRE": "1", "VLLM_ENABLE_CUDA_COMPATIBILITY": "1"}},
    {"name": "pinned+libs", "image": "pinned", "env": {"NVIDIA_DISABLE_REQUIRE": "1"},
     "prefix": f"LD_LIBRARY_PATH={COMPAT_DIR}:${{LD_LIBRARY_PATH:-}}"},
    {"name": "cu129", "image": "cu129", "env": {}, "prefix": ""},
]  # fmt: skip
# what each status means, for the table and the page (runbook §29). REACHED: the check got as far as the card (or the
# driver refusing it): an answer about this machine. The others say nothing about the card.
MEANING = {
    "PASS": "the engine imports, sees the card, runs a kernel and loads its compiled kernels",
    "PARTIAL": "the card is seen but a kernel or the engine's compiled kernels fail",
    "DRIVER": "the engine started and its CUDA refused this driver",
    "REQUIRE": "the container toolkit refused the image's CUDA requirement before the engine started",
    "NO-BUILD": "the image has no build for this machine's architecture",
    "BUSY": "the card is busy or full (another program is using it)",
    "NO-GPU": "Docker gave the container no GPU (the NVIDIA runtime is not set up)",
    "TOOLKIT": "the NVIDIA container toolkit could not reach the driver",
    "PULL-FAILED": "the image could not be downloaded",
    "DISK": "not enough free disk to download the image",
    "ERROR": "the check did not finish",
    "SKIPPED": "not needed: an earlier form passed",
    "NOT-RUN": "not tried",
}
# an answer about this form on this machine (it reached the card, or was refused for good before it); the rest say
# nothing about the card, and the verdict is then inconclusive
REACHED = {"PASS", "PARTIAL", "DRIVER", "REQUIRE", "NO-BUILD"}
STOPS = {"NO-GPU", "TOOLKIT", "BUSY"}  # the same for every later form: stop, pull nothing more
EXIT = {"pass": 0, "none": 1, "inconclusive": 3}
RERUN = "python3 tools/engine_probe.py run --out ~/tb-engine-probe.json"
FIX_RUNTIME = "sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
FIX_TOOLKIT = ("send the output of nvidia-container-cli info; do not reinstall or change the driver (the toolkit is "
               "set up but cannot reach it)")  # fmt: skip
FIX_BUSY = "close the program using the card (nvidia-smi lists it at the bottom), then run step 2 again"
Runner = Callable[..., tuple[int, str, str]]  # (cmd, timeout, stream=False) -> (exit code, stdout, stderr)


# ------------------------------------------------------------------------------------------------ pure parts (tested)
_H = "[0-9a-fA-F]{1,4}"  # one IPv6 group
_SCRUB = [
    (re.compile(r"\b(?:GPU|MIG)-[0-9a-fA-F-]{8,}\b"), "<uuid>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\b[0-9a-fA-F]{4,8}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]\b"), "<pci>"),
    (re.compile(r"(?i)\b(bus[ -]?id|pci)(\s*[:=]?\s*)[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]\b"), r"\1\2<pci>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<address>"),
    (re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"), "<mac>"),
    (re.compile(r"\b(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}\b"), "<mac>"),
    (re.compile(rf"(?<![0-9A-Za-z:])(?:{_H}:){{7}}{_H}(?![0-9A-Za-z:])"), "<address>"),
    (
        re.compile(rf"(?<![0-9A-Za-z:])(?:{_H}(?::{_H}){{0,6}})?::(?:{_H}(?::{_H}){{0,6}})?(?![0-9A-Za-z:])"),
        "<address>",
    ),
    (re.compile(r"/(home|Users)/[^/\s'\"]+"), r"/\1/<user>"),
    (re.compile(r"/root\b"), "/<root-home>"),
    (re.compile(r"(?i)\b(serial(?:\s*number)?|s/n)(\s*[:=#]?\s*)[0-9A-Za-z][0-9A-Za-z-]{3,}"), r"\1\2<hidden>"),
    (re.compile(r"(?i)\b(hostname|host name|host)(\s*[:=]\s*)\S+"), r"\1\2<hidden>"),
    (
        re.compile(r"(?i)\b((?:at|on|from) host|hostname|host name)(\s+)(?!<)[A-Za-z0-9][A-Za-z0-9._-]*"),
        r"\1\2<hidden>",
    ),
]


def local_names() -> list[str]:
    """This machine's own name and this user's name: never in a file that is sent."""
    names = [platform.node(), platform.node().split(".")[0], os.environ.get("USER", ""), os.environ.get("LOGNAME", "")]
    with contextlib.suppress(Exception):  # no user database entry: nothing more to hide
        names.append(getpass.getuser())
    return sorted({n for n in names if n and len(n) >= 3}, key=len, reverse=True)


def scrub(text: str, limit: int = 400, hostname: str = "", names: list[str] | None = None) -> str:
    """Error text safe to paste in public: the host's and the user's names, UUIDs, PCI bus ids, addresses, MACs,
    serials and home folders replaced, cut to the last ``limit`` characters (the end of an error says what failed).
    ``names`` defaults to this machine's own (:func:`local_names`)."""
    out = text or ""
    hide = [hostname, *(local_names() if names is None else names)]
    for n in sorted({n for n in hide if n and len(n) >= 3}, key=len, reverse=True):
        out = re.sub(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])", "<name>", out, flags=re.IGNORECASE)
    for pat, rep in _SCRUB:
        out = pat.sub(rep, out)
    out = " ".join(out.split())
    return out[-limit:]


def scrub_probe(
    found: dict[str, Any] | None, hostname: str = "", names: list[str] | None = None
) -> dict[str, Any] | None:
    """The check's own result with every text in it scrubbed (its error fields carry the engine's messages)."""
    if found is None:
        return None
    return {k: scrub(v, hostname=hostname, names=names) if isinstance(v, str) else v for k, v in found.items()}


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


_REQUIRE_WORDS = re.compile(r"(?i)(unsatisfied condition: cuda|requirement error)")
_DRIVER_WORDS = re.compile(
    r"(?i)(driver version is insufficient|forward compatibility|cuda driver version|too old|older than|"
    r"\b804\b|\b803\b|requires newer driver|system has unsupported display driver)"
)
_NO_GPU_WORDS = re.compile(
    r"(?i)(could not select device driver|unknown or invalid runtime name|failed to discover gpu)"
)
_TOOLKIT_WORDS = re.compile(
    r"(?i)(nvidia-container-cli: (?:initialization|mount|detection) error|load library failed|libnvidia-ml\.so|"
    r"nvml error|no devices were found)"
)
_BUSY_WORDS = re.compile(
    r"(?i)(busy or unavailable|cudaErrorDevicesUnavailable|devices? (?:is|are) busy|out of memory|"
    r"cudaErrorMemoryAllocation)"
)
_NO_BUILD_WORDS = re.compile(r"(?i)(no matching manifest|does not provide the specified platform)")
_RATE_WORDS = re.compile(r"(?i)(toomanyrequests|rate limit|429 too many)")


def classify(rc: int, stdout: str, stderr: str) -> tuple[str, dict[str, Any] | None, str]:
    """(status, the check's own result, the error that decided it) for one ``docker run`` of the check."""
    probe = parse_probe(stdout)
    if probe is None:
        err = stderr or stdout or f"exit {rc}"
        if _REQUIRE_WORDS.search(err):
            return "REQUIRE", None, err
        if _NO_GPU_WORDS.search(err):
            return "NO-GPU", None, err
        if _TOOLKIT_WORDS.search(err):
            return "TOOLKIT", None, err
        if _BUSY_WORDS.search(err):
            return "BUSY", None, err
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
    if _BUSY_WORDS.search(errors):  # a busy or full card says nothing about this engine on this card
        return "BUSY", probe, errors
    if seen:
        return "PARTIAL", probe, errors or "a kernel gave a wrong result"
    if _DRIVER_WORDS.search(errors) or _DRIVER_WORDS.search(stderr or ""):
        return "DRIVER", probe, errors or stderr
    if probe.get("available") is False:
        return "DRIVER", probe, errors or "torch.cuda.is_available() is False inside the image"
    return "ERROR", probe, errors or stderr


def fix_for(status: str, error: str) -> tuple[str, str]:
    """(what is wrong, the one command or action that fixes it) for a status that did not reach the card."""
    e = error or ""
    if status == "NO-GPU":
        return "Docker gave the container no card (the NVIDIA container runtime)", FIX_RUNTIME
    if status == "TOOLKIT":
        return "the NVIDIA container toolkit could not reach the driver", FIX_TOOLKIT
    if status == "BUSY":
        return "the card is busy or full", FIX_BUSY
    if status == "DISK":
        return ("too little free disk under Docker's folder",
                f"free at least {MIN_FREE_GB} GB under Docker's folder (runbook §29 step 1), then df -h /")  # fmt: skip
    if status == "PULL-FAILED":
        if re.search(r"(?i)permission denied", e):
            return "this user may not use Docker", "sudo usermod -aG docker $USER, then sign out and back in"
        if _RATE_WORDS.search(e):
            return ("the registry's download limit was reached",
                    "wait an hour, or sign in with a free Docker Hub account (docker login), then run step 2 "
                    "again")  # fmt: skip
        return (
            "the download failed (network)",
            "curl -sI https://registry-1.docker.io/v2/ (it should print an HTTP/ line)",
        )
    if status == "ERROR" and re.search(r"(?i)timed out", e):
        return "a check took longer than 15 minutes", "send the file; then run step 2 again once"
    if status == "NOT-RUN":
        if re.search(r"(?i)interrupted", e):
            return "the probe was interrupted", "run step 2 again"
        return "a form was not tried (--only)", "run step 2 again without --only"
    return "a check stopped before it reached the card", "send the file; then run step 2 again once"


def verdict(results: list[dict[str, Any]], blocked: tuple[str, str] | None = None) -> dict[str, Any]:
    """The one answer and the one next action. ``pass``: the first form that passed (pinned, then the compatibility
    switch, then the compatibility libraries, then the CUDA 12.9 build). ``none``: every form reached the card and
    none ran. ``inconclusive``: some form never reached the card (``blocked`` is a preflight's (what, fix)): the
    answer is unknown, and the fix comes first."""
    by = {r["name"]: r for r in results}
    for name, text in (
        ("pinned", "The pinned engine runs as it is."),
        ("pinned+compat", "The pinned engine runs with its compatibility switch; the switch is recorded."),
        ("pinned+libs", "The pinned engine runs with its compatibility libraries first; the exact library path is "
                        "recorded and the measuring run uses it."),
        ("cu129", "Only the CUDA 12.9 build of the same engine release runs. It is not the pinned engine: a measuring "
                  "run with it is evidence for a later model change, not a profile."),
    ):  # fmt: skip
        r = by.get(name)
        if r and r["status"] == "PASS":
            test = next(t for t in TESTS if t["name"] == name)
            env = dict(test["env"])
            if test["prefix"]:
                env["LD_LIBRARY_PATH"] = ((r.get("probe") or {}).get("ld_library_path") or COMPAT_DIR).rstrip(":")
            return {
                "answer": "pass",
                "use": name,
                "image": test["image"],
                "env": env,
                "pinned_engine": test["image"] == "pinned",
                "next": f"{text} Next: runbook §29 step 4, then step 5 (the weights) and step 6 (the measuring run, "
                "which reads this file).",
            }
    if blocked is not None:
        what, fix = blocked
        return {"answer": "inconclusive", "use": None, "image": None, "env": {}, "pinned_engine": False,
                "problem": what, "fix": fix,
                "next": f"Inconclusive: {what}; the card was not reached. Fix: {fix}. Then run step 2 again: "
                        f"{RERUN}"}  # fmt: skip
    # the cause before what it stopped (a NOT-RUN after a NO-GPU)
    unreached = sorted(
        (r for r in results if r["status"] not in REACHED and r["status"] != "SKIPPED"),
        key=lambda r: r["status"] == "NOT-RUN",
    )
    if unreached:
        what, fix = fix_for(unreached[0]["status"], unreached[0].get("error") or "")
        return {"answer": "inconclusive", "use": None, "image": None, "env": {}, "pinned_engine": False,
                "problem": f"{unreached[0]['name']}: {what}", "fix": fix,
                "next": f"Inconclusive: {unreached[0]['name']}: {what}; this says nothing about the card. Fix: {fix}. "
                        f"Then run step 2 again: {RERUN}"}  # fmt: skip
    partial = [r["name"] for r in results if r["status"] == "PARTIAL"]
    note = f" ({', '.join(partial)}: the card is seen but a kernel fails)" if partial else ""
    return {"answer": "none", "use": None, "image": None, "env": {}, "pinned_engine": False,
            "next": "Every form reached the card and none computes on it with this driver" + note + ". Stop here and "
                    "send the file: the real models cannot run on this machine with this engine release. Step 4 (the "
                    "real embedder) does not depend on this."}  # fmt: skip


def preflight(run: Runner, need_disk_gb: float, min_free: float) -> tuple[str, str] | None:
    """(what, fix) of the first thing that would make every download useless, checked before any download."""
    rc, out, err = run(["docker", "version", "--format", "{{.Server.Version}}"], 60)
    if rc == 127:
        return "Docker is not installed", "install Docker Engine (runbook §28 step 2)"
    if rc != 0:
        if re.search(r"(?i)permission denied", err):
            return "this user may not use Docker", "sudo usermod -aG docker $USER, then sign out and back in"
        return "Docker does not answer", "sudo systemctl start docker"
    rc, out, _ = run(["nvidia-smi", "-L"], 60)
    if rc != 0 or not out.strip():
        return (
            "the NVIDIA driver does not answer (nvidia-smi)",
            "send the output of nvidia-smi; do not change the driver",
        )
    rc, out, _ = run(["docker", "info", "--format", "{{json .Runtimes}}"], 60)
    if rc != 0 or "nvidia" not in out:
        return "Docker has no NVIDIA runtime", FIX_RUNTIME
    rc, _, _ = run(["nvidia-container-cli", "info"], 60)
    if rc not in (0, 127):  # 127: not on this host's path; the first check then says what is wrong
        return "the NVIDIA container toolkit could not reach the driver (nvidia-container-cli info)", FIX_TOOLKIT
    if need_disk_gb > 0:
        free = free_gb(run)
        if free is not None and free < min_free:
            return (f"{free} GB free under Docker's folder, {min_free:g} GB needed for one engine image",
                    "free the disk as runbook §29 step 1 says, then df -h /")  # fmt: skip
    return None


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
        detail = MEANING.get(r["status"], "") + (f": {r['error']}" if r.get("error") else "")
        lines.append(f"{r['name']:<15} {r['status']:<12} {p.get('vllm', '-')!s:<9} {tc:<20} {seen:<10} {kern:<7} "
                     f"{detail[:110]}")  # fmt: skip
    for name, info in (rec.get("images") or {}).items():
        if info.get("remove_failed"):
            lines.append(f"note: the {name} image could not be removed: docker image rm {info['ref']}")
    v = rec.get("verdict") or {}
    word = v.get("use") or v.get("answer") or "none"
    lines += ["", f"verdict: {word}", f"next: {v.get('next', '')}"]
    return "\n".join(lines)


def pinned_ref(lock_path: Path = LOCK) -> str:
    entry = json.loads(lock_path.read_text(encoding="utf-8"))["third_party"]["vllm"]
    return f"{entry['image']}@{entry['digest']}"


def container_name(test: dict[str, Any]) -> str:
    return "tb-engine-probe-" + str(test["name"]).replace("+", "-")


def run_command(test: dict[str, Any], ref: str, gpu_args: list[str]) -> list[str]:
    """``docker run`` of the check for one test: a known name (removed on a timeout or Ctrl-C), no network, the card,
    the check in an environment variable."""
    env = [x for k, v in sorted(test["env"].items()) for x in ("-e", f"{k}={v}")]
    inner = f'{test["prefix"]} python3 -c "$ENGINE_PROBE_PY"'.strip()
    return ["docker", "run", "--rm", "--name", container_name(test), "--network", "none", *gpu_args, *env,
            "-e", "ENGINE_PROBE_PY", "--entrypoint", "bash", ref, "-c", inner]  # fmt: skip


# ------------------------------------------------------------------------------------------------ the machine
def _real_runner(cmd: list[str], timeout: int, stream: bool = False) -> tuple[int, str, str]:
    """One command; ``stream`` shows its standard output as it comes (a download's progress) and keeps its errors."""
    env = None
    if "ENGINE_PROBE_PY" in cmd:
        env = {**os.environ, "ENGINE_PROBE_PY": PROBE_PY}
    try:
        if stream:
            p = subprocess.run(cmd, stdout=None, stderr=subprocess.PIPE, text=True, timeout=timeout, check=False)
            return p.returncode, "", p.stderr
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, env=env)
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout} s"
    return p.returncode, p.stdout, p.stderr


def card_id(uuid: str) -> str:
    """H-89: a one-way digest of a card's UUID: says "the same card" without naming it."""
    return hashlib.sha256(f"{SCHEMA} card {uuid.strip()}".encode()).hexdigest()[:32]


def host_id() -> str | None:
    """H-89: a one-way digest of this host's /etc/machine-id (TB_HOST_ROOT moves it: the tests only); None without
    one."""
    try:
        mid = Path(os.environ.get("TB_HOST_ROOT", "") + "/etc/machine-id").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return hashlib.sha256(f"{SCHEMA} host {mid}".encode()).hexdigest()[:32] if mid else None


def host_facts(run: Runner, index: str | None = None) -> dict[str, Any]:
    """What the result needs to be read, and nothing that names the machine. With ``index`` (``run --gpu-index``,
    H-89): that one card's facts, and the one-way ids of the card and of this host."""
    facts: dict[str, Any] = {"arch": platform.machine()}
    one = ["-i", index] if index is not None else []
    rc, out, _ = run(["nvidia-smi", *one, "--query-gpu=name,memory.total,driver_version,compute_cap",
                      "--format=csv,noheader,nounits"], 60)  # fmt: skip
    if rc == 0 and out.strip():
        cells = [c.strip() for c in out.strip().splitlines()[0].split(",")]
        cells += [""] * (4 - len(cells))
        facts.update(card=cells[0], memory_total_mib=int(cells[1]) if cells[1].isdigit() else cells[1],
                     driver=cells[2], compute_cap=cells[3])  # fmt: skip
    else:
        facts.update(card=None, memory_total_mib=None, driver=None, compute_cap=None)
    rc, out, _ = run(
        ["nvidia-smi", *one, "--query-gpu=display_active,memory.used", "--format=csv,noheader,nounits"], 60
    )
    cells = [c.strip() for c in out.strip().splitlines()[0].split(",")] if rc == 0 and out.strip() else []
    facts["display_active"] = cells[0] if cells else None  # "Enabled": the card also drives a screen
    facts["memory_used_mib"] = int(cells[1]) if len(cells) > 1 and cells[1].isdigit() else None
    rc, out, _ = run(["docker", "version", "--format", "{{.Server.Version}}"], 60)
    facts["docker"] = out.strip() if rc == 0 else None
    rc, out, _ = run(["docker", "info", "--format", "{{json .Runtimes}}"], 60)
    facts["nvidia_runtime"] = rc == 0 and "nvidia" in out
    if index is not None:
        rc, out, _ = run(["nvidia-smi", "-i", index, "--query-gpu=uuid", "--format=csv,noheader"], 60)
        uuid = out.strip().splitlines()[0].strip() if rc == 0 and out.strip() else ""
        facts.update(gpu_index=int(index), card_id=card_id(uuid) if uuid else None, host_id=host_id())
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
    names: list[str] | None = None,
    gpu_index: str | None = None,
) -> dict[str, Any]:
    """Run the tests one image at a time, stopping at the first form that passes, and return the result record (no
    file written here). Ctrl-C stops it cleanly: the running check's container and an image it pulled are removed,
    and the record says it was interrupted."""
    refs = {"pinned": pinned or pinned_ref(), "cu129": CU129}
    gpus = gpu_args if gpu_args is not None else ["--gpus", "all"]
    rec: dict[str, Any] = {
        "schema": SCHEMA,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 (the host's Python 3.9+)
        "host": {},
        "images": {},
        "tests": [],
    }
    wanted = [t for t in TESTS if not only or t["name"] in only]

    def done(status: str, t: dict[str, Any], error: str = "") -> None:
        rec["tests"].append({"name": t["name"], "status": status, "probe": None, "env": t["env"],
                             "libs_first": bool(t["prefix"]), "error": error})  # fmt: skip

    def remove(image: str, info: dict[str, Any]) -> None:
        if keep or info.get("was_present") or not info.get("pulled"):
            return
        rc, _, err = run(["docker", "image", "rm", info["ref"]], 600)
        gone = rc != 0 and re.search(r"(?i)no such image", err or "")  # nothing there to remove: not a failure
        info["removed"] = rc == 0 or bool(gone)
        if rc != 0 and not gone:
            info["remove_failed"] = scrub(err, 200, hostname, names)
            say(f"  could not remove the {image} image: docker image rm {info['ref']}")

    current: dict[str, Any] = {}
    passed = False
    stopped = ""  # a status every later form would meet the same way (no card given, the card busy)
    blocked: tuple[str, str] | None = None
    try:
        rec["host"] = host_facts(run, gpu_index)
        rec["host"]["free_gb_before"] = free_gb(run)
        blocked = preflight(run, 1.0, min_free)
        if blocked is not None:
            say(f"  stopped before any download: {blocked[0]}")
            for t in wanted:
                done("NOT-RUN", t, blocked[0])
        for image in ("pinned", "cu129"):
            if blocked is not None or stopped:
                break
            tests = [t for t in wanted if t["image"] == image]
            if not tests:
                continue
            if passed:
                for t in tests:
                    done("SKIPPED", t)
                continue
            ref = refs[image]
            info: dict[str, Any] = {"ref": ref, "verified_in_lock": image == "pinned"}
            rec["images"][image] = info
            current = {"image": image, "info": info}
            had, _, _ = run(["docker", "image", "inspect", ref], 60)
            info["was_present"] = had == 0
            if had != 0:
                free = free_gb(run)
                if free is not None and free < min_free:
                    say(f"  {image}: {free} GB free under Docker's folder, {min_free:g} GB needed: not pulled")
                    for t in tests:
                        done("DISK", t, f"{free} GB free, {min_free:g} GB needed")
                    continue
                say(f"  downloading the {image} engine image (10 to 12 GB; often 20 to 40 minutes; progress below)")
                rc, _, err = run(["docker", "pull", ref], 7200, stream=True)
                info["pulled"] = rc == 0
                if rc != 0:
                    status = "PULL-FAILED"
                    if _NO_BUILD_WORDS.search(err or ""):
                        status = "NO-BUILD"  # final for this form: no Arm build of it exists
                    elif re.search(r"(?i)no space left on device", err or ""):
                        status = "DISK"
                    for t in tests:
                        done(status, t, scrub(err, hostname=hostname, names=names))
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
                if passed:
                    done("SKIPPED", t)
                    continue
                if stopped:
                    done("NOT-RUN", t, f"not tried after {stopped}")
                    continue
                say(f"  checking {t['name']}")
                current["container"] = container_name(t)
                run(["docker", "rm", "-f", container_name(t)], 60)  # a leftover of an earlier, interrupted run
                rc, out, err = run(run_command(t, ref, gpus), 900)
                if rc == 124:
                    run(["docker", "rm", "-f", container_name(t)], 120)  # the timeout ended the client only
                current.pop("container", None)
                status, found, why = classify(rc, out, err)
                rec["tests"].append({"name": t["name"], "status": status, "probe": scrub_probe(found, hostname, names),
                                     "env": t["env"], "libs_first": bool(t["prefix"]),
                                     "error": scrub(why, hostname=hostname, names=names) if why else ""})  # fmt: skip
                passed = passed or status == "PASS"
                if status in STOPS:
                    stopped = status
                    say(f"  {status}: {MEANING[status]}; nothing more is tried")
            remove(image, info)
            current = {}
    except KeyboardInterrupt:
        rec["interrupted"] = True
        say("  interrupted: removing the running check and the image it downloaded")
        if current.get("container"):
            run(["docker", "rm", "-f", current["container"]], 120)
        if current.get("info"):
            current["info"].setdefault("pulled", True)
            remove(current["image"], current["info"])
    seen = {r["name"] for r in rec["tests"]}
    for t in TESTS:
        if t["name"] not in seen:
            why = "interrupted" if rec.get("interrupted") else (f"not tried after {stopped}" if stopped else "")
            done("SKIPPED" if passed else "NOT-RUN", t, "" if passed else why)
    rec["tests"].sort(key=lambda r: [t["name"] for t in TESTS].index(r["name"]))
    rec["verdict"] = verdict(rec["tests"], blocked)
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
    r.add_argument("--gpu-index", default=None, help="H-89: probe the one card at this index (--gpus device=N), and "
                   "record its one-way id and this host's (a rehearsal with real servers needs them)")  # fmt: skip
    r.add_argument("--dry-run", action="store_true", help="print the commands; run nothing")
    s = sub.add_parser("show", help="print the table of a result file")
    s.add_argument("file", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "show":
        rec = json.loads(a.file.read_text(encoding="utf-8"))
        print(table(rec))
        return EXIT.get((rec.get("verdict") or {}).get("answer") or "none", 1)
    only = [x.strip() for x in a.only.split(",") if x.strip()]
    unknown = sorted(set(only) - {t["name"] for t in TESTS})
    if unknown:
        print(f"engine_probe: unknown test {', '.join(unknown)}", file=sys.stderr)
        return 2
    gpu_args = shlex.split(a.gpu_args)
    if a.gpu_index is not None:
        if not a.gpu_index.isdigit() or a.gpu_args != "--gpus all":
            print(
                "engine_probe: --gpu-index N names one card (0, 1, ...) and takes the place of --gpu-args",
                file=sys.stderr,
            )
            return 2
        gpu_args = ["--gpus", f"device={a.gpu_index}"]
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
                hostname=platform.node(), gpu_index=a.gpu_index)  # fmt: skip
    a.out.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print()
    print(table(rec))
    print(f"\nwritten: {a.out} (send this file: it names no host, serial, address or user)")
    if rec.get("interrupted"):
        return 130
    return EXIT[rec["verdict"]["answer"]]


if __name__ == "__main__":
    sys.exit(main())
