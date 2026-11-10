"""Digest-pinned images on any Docker image store (D-176): the box runs exactly the images of the signed bundle.

The compose files pin third-party images by digest (``${POSTGRES_IMAGE:-postgres:16-alpine@sha256:...}``). A
bundle carries each one saved under its tag (``tools/make_bundle.sh``) and a signed ``image-pins.json``: for every
digest reference, the image id (the config digest) that ``docker save`` wrote. After ``docker load``:

* Docker's containerd image store keeps the digest, and the reference resolves as it is: nothing to do.
* The classic store (overlay2) does not: ``docker load`` restores tags only, so ``postgres:16-alpine@sha256:...``
  is "No such image" and compose would try to pull it. Here the loaded image is found by its id, which is content
  addressed (an image with that id is that content), and its compose variable is set in ``deploy/.env`` to the id.

    python3 -m tools.image_pins merge <bundle's image-pins.json> --deploy deploy   # update.py: keep the pins
    python3 -m tools.image_pins resolve --deploy deploy --files a.yml:b.yml        # before every compose up

``resolve`` exits 1, naming the image, when a pinned image is neither on the box by digest nor by the bundle's id:
the box would need a registry. A variable the site set to anything but an image id (its own mirror) is left alone.
Standard library only (a site host has no TrialBox Python packages).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

PINS = "image-pins.json"
VAR_REF = re.compile(r"\$\{([A-Z][A-Z0-9_]*):-([^}\s]+@sha256:[0-9a-f]{64})\}")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")

Inspect = Callable[[str], bool]


def docker_has(ref: str) -> bool:
    """True when the local Docker has an image by this reference or id (no pull)."""
    r = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", ref], capture_output=True, text=True, check=False
    )
    return r.returncode == 0


def compose_pins(files: list[Path]) -> dict[str, str]:
    """``{variable: digest reference}`` of every ``${VAR:-image@sha256:...}`` in the compose files."""
    out: dict[str, str] = {}
    for f in files:
        if not f.is_file():
            continue
        for var, ref in VAR_REF.findall(f.read_text(encoding="utf-8")):
            out[var] = ref
    return out


def read_pins(path: Path) -> dict[str, str]:
    """``{digest reference: image id}`` from an ``image-pins.json`` (empty when there is none)."""
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for p in doc.get("pins") or []:
        ref, image = str(p.get("ref", "")), str(p.get("image", ""))
        if "@sha256:" in ref and IMAGE_ID.match(image):
            out[ref] = image
    return out


def merge(src: Path, deploy: Path) -> int:
    """Add a bundle's pins to ``deploy/image-pins.json`` (the newest bundle wins for a reference); the count added."""
    have = read_pins(deploy / PINS)
    new = read_pins(src)
    have.update(new)
    doc = {"pins": [{"ref": r, "image": i} for r, i in sorted(have.items())]}
    tmp = deploy / f".{PINS}.tmp"
    tmp.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    tmp.chmod(0o644)
    tmp.replace(deploy / PINS)
    return len(new)


def read_env(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def resolve(
    deploy: Path, files: list[Path], has: Inspect | None = None
) -> tuple[dict[str, str | None], list[str], list[str]]:
    """``({variable: image id, or None to clear}, notes, missing references)`` for this box's compose files."""
    has = has or docker_has
    pins = read_pins(deploy / PINS)
    env = {}
    for line in read_env(deploy / ".env"):
        k, sep, v = line.partition("=")
        if sep:
            env[k.strip()] = v.strip()
    changes: dict[str, str | None] = {}
    notes: list[str] = []
    missing: list[str] = []
    for var, ref in sorted(compose_pins(files).items()):
        current = env.get(var, "")
        if current and not IMAGE_ID.match(current):
            notes.append(f"{var}: the site's own {current} (left alone)")
            continue
        if has(ref):
            notes.append(f"{var}: {ref} on this box by its digest")
            if current:
                changes[var] = None
            continue
        image = pins.get(ref)
        if image and has(image):
            notes.append(f"{var}: {ref} is the bundle's image {image[:19]} (this image store keeps no digests)")
            if current != image:
                changes[var] = image
            continue
        missing.append(f"{var}: {ref}" + ("" if image else " (no pin in deploy/image-pins.json)"))
    return changes, notes, missing


def write_env(path: Path, changes: dict[str, str | None]) -> None:
    if not changes:
        return
    lines = [ln for ln in read_env(path) if ln.partition("=")[0].strip() not in changes]
    lines += [f"{k}={v}" for k, v in sorted(changes.items()) if v]
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    tmp = path.with_name(f".{path.name}.pins.tmp")
    tmp.touch(mode=0o600)
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.chmod(mode)
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="image_pins", description=__doc__.split("\n\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("pins", type=Path)
    m.add_argument("--deploy", type=Path, required=True)
    r = sub.add_parser("resolve")
    r.add_argument("--deploy", type=Path, required=True)
    r.add_argument("--files", required=True, help="the compose files, ':'-separated (deploy/.env COMPOSE_FILE)")
    a = ap.parse_args(argv)
    if a.cmd == "merge":
        print(f"image pins: {merge(a.pins, a.deploy)} from the bundle")
        return 0
    files = [Path(f) for f in a.files.split(":") if f]
    changes, notes, missing = resolve(a.deploy, files)
    for n in notes:
        print(f"image pins: {n}")
    if missing:
        for x in missing:
            print(f"image pins: MISSING {x}: neither on this box by digest nor loaded from the bundle", file=sys.stderr)
        return 1
    write_env(a.deploy / ".env", changes)
    for k, v in sorted(changes.items()):
        print(f"image pins: deploy/.env {k}={v}" if v else f"image pins: deploy/.env {k} cleared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
