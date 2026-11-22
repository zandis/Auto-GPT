"""The third-party images of ``deploy/images.lock`` (D-348): the compose files against the lock, and the GPU host
against what the vLLM image needs.

``deploy/images.lock`` is the one digest list. Its ``third_party`` section names every image the box pulls as
published, with the multi-arch index digest read from the registry, the compose variables that name it, its
platforms and, for the vLLM image, the CUDA architectures of each platform's build and the lowest NVIDIA driver it
runs on. Two uses:

* ``check-compose``: every ``image:`` line of the given compose files is either a TrialBox image (``trialbox-*``, built
  and pinned by the release, T-104/T-110) or ``${VAR:-repository:tag@sha256:...}`` with exactly the reference and
  digest the lock gives for ``VAR``. No image by tag alone; no digest the lock does not hold.
* ``host``: on a GPU box, the host's architecture, NVIDIA driver and compute capability against the vLLM entry. FAIL
  when the image has no build for the architecture, when the driver is below ``gpu.driver_min`` (a CUDA 13 image on an
  R575 driver does not start), or when no CUDA architecture of the build runs on the device. A site that set its own
  vLLM image (a mirror) gets a WARN: the lock does not describe that image.

    python3 -m tools.images_lock check-compose --files deploy/docker-compose.yml:deploy/docker-compose.gb10.yml
    python3 -m tools.images_lock host --arch "$(uname -m)" --driver 580.142 --compute-cap 12.1 [--image REF]

Standard library only: ``deploy/check_host.sh`` and ``deploy/install.sh`` run it on a site host.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "deploy" / "images.lock"
OWN_PREFIX = "trialbox-"  # images TrialBox builds (pinned by the release, not here)
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_LINE = re.compile(r"^\s*image:\s*(\S.*?)\s*(?:#.*)?$")
VAR_DEFAULT = re.compile(r"^\$\{([A-Z][A-Z0-9_]*):-([^}\s]+)\}$")
ARCH = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
VLLM = "vllm"


def load(path: Path = LOCK) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("third_party"), dict):
        raise ValueError(f"{path}: no third_party section")
    return data


def lock_problems(lock: dict[str, Any]) -> list[str]:
    """The lock's own shape: a tag and an index digest per entry, each compose variable owned by one entry."""
    out: list[str] = []
    owner: dict[str, str] = {}
    for name, e in sorted(lock["third_party"].items()):
        image, digest = e.get("image"), e.get("digest")
        if not isinstance(image, str) or ":" not in image.rsplit("/", 1)[-1] or "@" in image:
            out.append(f"{name}: image {image!r} is not repository:tag")
        if not isinstance(digest, str) or not DIGEST.match(digest):
            out.append(f"{name}: digest {digest!r} is not sha256:<64 hex>")
        plats = e.get("platforms")
        if not isinstance(plats, dict) or not plats:
            out.append(f"{name}: no platforms")
        variables = e.get("variables")
        if not isinstance(variables, list) or not variables:
            out.append(f"{name}: no compose variables")
            continue
        for v in variables:
            if v in owner:
                out.append(f"variable {v}: named by {owner[v]} and {name}")
            owner[v] = name
    gpu = (lock["third_party"].get(VLLM) or {}).get("gpu") or {}
    for k in ("cuda", "driver_min", "structured_outputs_backend"):
        if not gpu.get(k):
            out.append(f"{VLLM}: gpu.{k} missing")
    for plat, p in ((lock["third_party"].get(VLLM) or {}).get("platforms") or {}).items():
        if not p.get("cuda_arch"):
            out.append(f"{VLLM}: {plat} has no cuda_arch list")
    return out


def by_variable(lock: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    return {v: (name, e) for name, e in lock["third_party"].items() for v in e.get("variables") or []}


def pinned(entry: dict[str, Any]) -> str:
    return f"{entry['image']}@{entry['digest']}"


def image_lines(path: Path) -> list[tuple[int, str]]:
    """``(line number, value)`` of every ``image:`` key in a compose file (anchors and overrides included)."""
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = IMAGE_LINE.match(line)
        if m:
            out.append((n, m.group(1).strip("\"'")))
    return out


def check_compose(lock: dict[str, Any], files: list[Path]) -> tuple[list[str], set[str]]:
    """Problems with the image lines of ``files``, and the lock entries they use."""
    problems: list[str] = []
    used: set[str] = set()
    owners = by_variable(lock)
    for f in files:
        for n, value in image_lines(f):
            where = f"{f.name}:{n}"
            m = VAR_DEFAULT.match(value)
            ref = m.group(2) if m else value
            if ref.startswith(OWN_PREFIX):
                continue
            if not m:
                problems.append(f"{where}: {value} is not ${{VAR:-image@digest}} (a third-party image is named by its "
                                "compose variable and pinned by digest)")  # fmt: skip
                continue
            var = m.group(1)
            if "@sha256:" not in ref:
                problems.append(f"{where}: {var} pulls {ref} by tag: pin it by digest from deploy/images.lock")
                continue
            if var not in owners:
                problems.append(f"{where}: {var} ({ref}) is not in deploy/images.lock third_party")
                continue
            name, entry = owners[var]
            used.add(name)
            if ref != pinned(entry):
                problems.append(f"{where}: {var} is {ref}, deploy/images.lock {name} is {pinned(entry)}")
    return problems, used


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def arch_covers(archs: list[str], cap: str) -> bool:
    """Does a build for these CUDA architectures run on a device of compute capability ``cap``? Code built for X.y
    runs on X.z with z >= y (same major); an "a" or "f" build (10.0a) runs only on its own capability."""
    want = _version(cap)
    if len(want) < 2:
        return False
    for a in archs:
        exact = a[-1:].isalpha()
        have = _version(a)
        if len(have) < 2:
            continue
        if exact and have[:2] == want[:2]:
            return True
        if not exact and have[0] == want[0] and have[1] <= want[1]:
            return True
    return False


def host_check(
    lock: dict[str, Any],
    arch: str,
    driver: str,
    compute_cap: str,
    image: str = "",
    rehearsal: Callable[[str], tuple[list[str], dict[str, Any]]] | None = None,
) -> list[tuple[str, str]]:
    """``(PASS|WARN|FAIL, message)`` lines for this GPU host and the locked vLLM image. ``rehearsal``: card H-89's
    driver allowance (install.sh under the rehearsal mark only); None: a driver below the minimum FAILs."""
    entry = lock["third_party"][VLLM]
    ref = pinned(entry)
    if image and image != ref and not DIGEST.match(image):
        # an image id (sha256:...) is the bundle's own copy of the pinned image (tools/image_pins.py)
        return [("WARN", f"vLLM image {image} is the site's own, not deploy/images.lock's {ref}: its arch and "
                         "driver needs are not checked here")]  # fmt: skip
    out: list[tuple[str, str]] = []
    gpu = entry["gpu"]
    plat = f"linux/{ARCH.get(arch, arch)}"
    build = (entry.get("platforms") or {}).get(plat)
    if build is None:
        out.append(("FAIL", f"vLLM image {entry['image']} has no {plat} build (it has "
                            f"{', '.join(sorted(entry['platforms']))}): this host cannot run it"))  # fmt: skip
    else:
        out.append(("PASS", f"vLLM image {entry['image']} has a {plat} build ({build.get('manifest', 'index')})"))
    need = gpu["driver_min"]
    if not driver:
        out.append(("FAIL", f"no NVIDIA driver found (nvidia-smi): the vLLM image needs {need} or newer"))
    elif _version(driver) < _version(need):
        line = need.split(".")[0]
        msg = f"NVIDIA driver {driver} is below {need}, the lowest that runs the vLLM image (CUDA {gpu['cuda']})"
        # REHEARSAL-REAL-SERVERS (H-89): below the minimum a WARN only on a rehearsal box with a passed probe file of
        # this card, this driver and the pinned image (tools/rehearsal_real.py driver_allowance); else FAIL as before
        why, _ = rehearsal(driver) if rehearsal is not None else (["no rehearsal"], {})
        if rehearsal is not None and not why:
            out.append(("WARN", f"{msg}: rehearsal: driver below the minimum (found {driver}, minimum {need}), with "
                                "the forward-compatibility path the engine probe passed on this card; not valid for "
                                "a site"))  # fmt: skip
        else:
            out.append(("FAIL", f"{msg}: update the driver to the R{line} line or newer"))
            if rehearsal is not None:
                out += [("FAIL", f"rehearsal with real servers refused: {w}") for w in why]
        # ---- end of REHEARSAL-REAL-SERVERS (H-89)
    else:
        out.append(("PASS", f"NVIDIA driver {driver} runs CUDA {gpu['cuda']} (needs {need} or newer)"))
    if build is not None:
        archs = build.get("cuda_arch") or []
        if not compute_cap:
            msg = f"the image's CUDA architectures {' '.join(archs)} are not checked against the device"
            out.append(("WARN", f"compute capability not reported (nvidia-smi --query-gpu=compute_cap): {msg}"))
        elif arch_covers(archs, compute_cap):
            out.append(("PASS", f"GPU compute capability {compute_cap} is covered by the image's build "
                                f"({' '.join(archs)})"))  # fmt: skip
        else:
            out.append(("FAIL", f"GPU compute capability {compute_cap} is not in the image's {plat} build "
                                f"({' '.join(archs)}): vLLM has no kernels for this device"))  # fmt: skip
    out.append(("PASS", f"structured output: vLLM backend {gpu['structured_outputs_backend']} (deploy/images.lock)"))
    return out


# REHEARSAL-REAL-SERVERS (H-89): the driver allowance of tools/rehearsal_real.py for this card (run as a file too)
def _rehearsal_allowance(probe: Path, index: str, deploy: Path) -> Callable[[str], tuple[list[str], dict[str, Any]]]:
    """The allowance, bound to the probe file, the card's index and the box's deploy folder (the driver is that card's,
    read again by the allowance)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools import rehearsal_real

    def allowance(driver: str) -> tuple[list[str], dict[str, Any]]:
        problems, rec = rehearsal_real.driver_allowance(probe, index, deploy)
        if rec.get("driver_found") not in (None, driver):
            problems.append(f"the card's driver is {rec.get('driver_found')}, the host check read {driver}")
        return problems, rec

    return allowance


# ---- end of REHEARSAL-REAL-SERVERS (H-89)


def _files(arg: str) -> list[Path]:
    return [Path(p) for p in arg.split(":") if p]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lock", type=Path, default=LOCK)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check-compose", help="the compose files' image lines against the lock")
    c.add_argument("--files", required=True, help="colon-separated compose files")
    c.add_argument("--all", action="store_true", help="also fail on a lock entry no file uses")
    h = sub.add_parser("host", help="this GPU host against the locked vLLM image")
    h.add_argument("--arch", required=True)
    h.add_argument("--driver", default="")
    h.add_argument("--compute-cap", default="")
    h.add_argument("--image", default="", help="the vLLM image the site set (VLLM_IMAGE), if any")
    # REHEARSAL-REAL-SERVERS (H-89): install.sh's rehearsal only; all four or none
    h.add_argument("--rehearsal-real-servers", action="store_true", help=argparse.SUPPRESS)
    h.add_argument("--engine-probe", type=Path, default=None, help=argparse.SUPPRESS)
    h.add_argument("--gpu-index", default="", help=argparse.SUPPRESS)
    h.add_argument("--deploy", type=Path, default=None, help=argparse.SUPPRESS)
    # ---- end of REHEARSAL-REAL-SERVERS (H-89)
    sub.add_parser("vllm", help="print the locked vLLM reference (image@digest)")
    args = ap.parse_args(argv)
    try:
        lock = load(args.lock)
    except (OSError, ValueError) as exc:
        print(f"FAIL  deploy/images.lock: {exc}")
        return 1
    bad = lock_problems(lock)
    if bad:
        for b in bad:
            print(f"FAIL  deploy/images.lock: {b}")
        return 1
    if args.cmd == "vllm":
        print(pinned(lock["third_party"][VLLM]))
        return 0
    if args.cmd == "check-compose":
        files = _files(args.files)
        problems, used = check_compose(lock, files)
        if args.all:
            unused = sorted(set(lock["third_party"]) - used)
            problems += [f"deploy/images.lock {n} is used by no compose file" for n in unused]
        for p in problems:
            print(f"FAIL  {p}")
        if not problems:
            print(
                f"PASS  third-party images of {len(files)} compose file(s) as deploy/images.lock ({len(used)} entries)"
            )
        return 1 if problems else 0
    allowance: Callable[[str], tuple[list[str], dict[str, Any]]] | None = None
    # REHEARSAL-REAL-SERVERS (H-89)
    if args.rehearsal_real_servers or args.engine_probe or args.gpu_index or args.deploy:
        if not (args.rehearsal_real_servers and args.engine_probe and args.gpu_index and args.deploy):
            ap.error("--rehearsal-real-servers needs --engine-probe, --gpu-index and --deploy (install.sh's rehearsal)")
        allowance = _rehearsal_allowance(args.engine_probe, args.gpu_index.strip(), args.deploy)
    # ---- end of REHEARSAL-REAL-SERVERS (H-89)
    lines = host_check(lock, args.arch, args.driver.strip(), args.compute_cap.strip(), args.image.strip(), allowance)
    for level, msg in lines:
        print(f"{level:<5} {msg}")
    return 1 if any(level == "FAIL" for level, _ in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
