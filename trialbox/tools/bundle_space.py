"""The disk space ``tools/make_bundle.sh`` needs, checked before it saves the first image (D-830).

The build saves every image into its staging folder (``mktemp -d`` under ``$TMPDIR``, default /tmp) and then writes
the signed bundle to ``--out``: about the images' size (plus models) in each place, twice on one disk. Lane G's
build ran out of space under /tmp while packing the vLLM image.

    python -m tools.bundle_space --stage DIR --out FILE [--models DIR] IMAGE...

Exit 0 with one line naming the estimate; exit 2 with what to free or where to point ``TMPDIR``/``--out``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

MARGIN = 1.1  # archive headers, the host tree, the release record
SLACK = 512 << 20


def _gb(n: float) -> str:
    return f"{n / (1 << 30):.1f} GB"


def _inspect(ref: str) -> Any:
    proc = subprocess.run(["docker", "image", "inspect", ref], capture_output=True, text=True, check=False)
    try:
        return json.loads(proc.stdout) if proc.returncode == 0 else None
    except json.JSONDecodeError:
        return None


def payload_bytes(images: Iterable[str], models: Path | None, *, inspect: Callable[[str], Any] = _inspect) -> int:
    """Docker's size of each image plus every model file: an image docker cannot size counts 0."""
    total = 0
    for ref in images:
        doc = inspect(ref)
        with contextlib.suppress(TypeError, IndexError, KeyError, ValueError, AttributeError):
            total += int(doc[0].get("Size") or 0)
    if models is not None and models.is_dir():
        total += sum(f.stat().st_size for f in models.rglob("*") if f.is_file())
    return total


def problems(
    stage: Path,
    out_dir: Path,
    payload: int,
    *,
    free: Callable[[Path], int] = lambda p: shutil.disk_usage(p).free,
    same: bool | None = None,
) -> list[str]:
    need = int(payload * MARGIN) + SLACK
    if same is None:
        same = os.stat(stage).st_dev == os.stat(out_dir).st_dev
    if same:
        have = free(stage)
        if have < 2 * need:
            return [
                f"needs about {_gb(2 * need)} free on the disk of {stage} (staging) and {out_dir} (--out); "
                f"{_gb(have)} free: free space, or set TMPDIR (staging) or --out to a larger disk"
            ]
        return []
    out = []
    if free(stage) < need:
        out.append(
            f"needs about {_gb(need)} free for staging in {stage}; {_gb(free(stage))} free: set TMPDIR to a larger disk"
        )
    if free(out_dir) < need:
        out.append(
            f"needs about {_gb(need)} free for the bundle in {out_dir}; {_gb(free(out_dir))} free: choose another --out"
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.bundle_space", description=__doc__)
    ap.add_argument("--stage", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path, help="the bundle file (its folder is checked)")
    ap.add_argument("--models", type=Path)
    ap.add_argument("image", nargs="*")
    args = ap.parse_args(argv)
    out_dir = args.out.resolve().parent
    payload = payload_bytes(args.image, args.models)
    found = problems(args.stage, out_dir, payload)
    for p in found:
        print(f"make_bundle: {p}", file=sys.stderr)
    if not found:
        print(
            f"    disk: about {_gb(int(payload * MARGIN) + SLACK)} for staging ({args.stage}), as much for the bundle"
        )
    return 2 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
