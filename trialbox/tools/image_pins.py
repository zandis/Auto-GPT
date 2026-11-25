"""Digest-pinned images on either image store of the container engine (D-176, H-149): the box runs exactly the
images of the signed bundle.

The compose files pin third-party images by digest (``${HAPI_IMAGE:-hapiproject/hapi:...@sha256:...}``). A bundle
carries each one saved under its tag (``tools/make_bundle.sh``) and a signed ``image-pins.json``: for every digest
reference, read out of the saved archive itself, the image id that ``save`` wrote (the config digest), the tag it was
saved under, the layer diff ids (``rootfs.diff_ids``) and the config fields that decide what a container runs.

After ``load``, three cases, tried in this order:

* The store keeps the digest reference and it resolves as it is: nothing to set.
* The classic store (the container engine's default through major version 28): ``load`` restores tags only, and an
  image's id is its config digest. The bundle's id is found as it is, and its compose variable is set in
  ``deploy/.env`` to that id. The id is content addressed: an image with that id is that content.
* The newer image store (the default from major version 29): the loaded image keeps neither the registry's digest nor
  the config digest as its id; its ``Id`` is the digest of the manifest (or index) the archive carried. Here the image
  under the bundle's tag is proved by what both stores agree on: its ``RootFS.Layers`` equal the signed diff ids, in
  order, and its architecture, OS and run config equal the signed ones. Only then is its compose variable set to the
  store's own ``Id`` (an id the store keeps; nothing is pulled). An image whose layers or config differ is refused, as
  is a pin from a bundle before H-149 (it carries no layers to prove the image by).

    python3 -m tools.image_pins merge <bundle's image-pins.json> --deploy deploy   # update.py: keep the pins
    python3 -m tools.image_pins resolve --deploy deploy --files a.yml:b.yml        # before every compose up
    python3 -m tools.image_pins bundle-pins OUT REF=TAG=ARCHIVE...                 # make_bundle.sh: the pins

``resolve`` exits 1, naming the image, when a pinned image is not proved on the box in one of those ways: the box
would need a registry. A variable the site set to anything but an image id (its own mirror) is left alone.
Standard library only (a site host has no TrialBox Python packages).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

PINS = "image-pins.json"
VAR_REF = re.compile(r"\$\{([A-Z][A-Z0-9_]*):-([^}\s]+@sha256:[0-9a-f]{64})\}")
IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
#: the image config's run fields compared on the newer image store (``config`` of the image config, ``Config`` of
#: ``image inspect`` on either store); with the layers they decide what a container of the image runs
RUN_FIELDS = ("Entrypoint", "Cmd", "Env", "User", "WorkingDir", "Volumes", "ExposedPorts", "StopSignal", "Labels",
              "Healthcheck", "Shell", "OnBuild")  # fmt: skip
#: the image config's platform fields (top level of both the image config and ``image inspect``)
PLATFORM_FIELDS = {"Architecture": "architecture", "Os": "os", "Variant": "variant"}

Inspect = Callable[[str], bool]
InspectJson = Callable[[str], "dict[str, Any] | None"]


def docker_has(ref: str) -> bool:
    """True when the local container engine has an image by this reference or id (no pull)."""
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", ref], capture_output=True, text=True, check=False
        )
    except OSError:
        return False
    return r.returncode == 0


def docker_inspect(ref: str) -> dict[str, Any] | None:
    """``image inspect`` of a local image as a dict (no pull); None when there is none by that reference."""
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{json .}}", ref], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    if r.returncode != 0:
        return None
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        return None
    if isinstance(doc, list):  # without --format the engine answers a list of one
        doc = doc[0] if len(doc) == 1 else None
    return doc if isinstance(doc, dict) else None


def compose_pins(files: list[Path]) -> dict[str, str]:
    """``{variable: digest reference}`` of every ``${VAR:-image@sha256:...}`` in the compose files."""
    out: dict[str, str] = {}
    for f in files:
        if not f.is_file():
            continue
        for var, ref in VAR_REF.findall(f.read_text(encoding="utf-8")):
            out[var] = ref
    return out


def bundle_tag(ref: str) -> str:
    """The tag ``make_bundle.sh`` saves a digest-pinned image under: the reference without its digest, ``:pinned``
    when it has no tag."""
    name = ref.split("@", 1)[0]
    return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:pinned"


def read_pin_records(path: Path) -> dict[str, dict[str, Any]]:
    """``{digest reference: pin record}`` from an ``image-pins.json`` (empty when there is none). A record has
    ``image`` (the config digest) and, from H-149 on, ``tag``, ``layers`` and ``config``; a malformed one is dropped."""
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for p in doc.get("pins") or []:
        if not isinstance(p, dict):
            continue
        ref, image = str(p.get("ref", "")), str(p.get("image", ""))
        if "@sha256:" not in ref or not IMAGE_ID.match(image):
            continue
        rec: dict[str, Any] = {"ref": ref, "image": image}
        layers = p.get("layers")
        if isinstance(layers, list) and layers and all(isinstance(x, str) and IMAGE_ID.match(x) for x in layers):
            rec["layers"] = list(layers)
            rec["config"] = dict(p.get("config") or {}) if isinstance(p.get("config"), dict) else {}
            tag = p.get("tag")
            rec["tag"] = tag if isinstance(tag, str) and tag else bundle_tag(ref)
        out[ref] = rec
    return out


def read_pins(path: Path) -> dict[str, str]:
    """``{digest reference: image id}`` from an ``image-pins.json`` (empty when there is none)."""
    return {ref: rec["image"] for ref, rec in read_pin_records(path).items()}


def _write_atomic(path: Path, text: str, mode: int) -> None:
    """Write-then-rename with fsync: a reader sees the old file or the new one, never half of one."""
    tmp = path.with_name(f".{path.name}.pins.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.replace(path)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def merge(src: Path, deploy: Path) -> int:
    """Add a bundle's pins to ``deploy/image-pins.json`` (the newest bundle wins for a reference); the count added."""
    have = read_pin_records(deploy / PINS)
    new = read_pin_records(src)
    have.update(new)
    doc = {"pins": [have[r] for r in sorted(have)]}
    _write_atomic(deploy / PINS, json.dumps(doc, indent=1) + "\n", 0o644)
    return len(new)


def _norm(v: Any) -> Any:
    """An absent, null or empty field is one value: the two stores write an unset field either way."""
    return None if v in (None, "", [], {}) else v


def _obj(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def config_fields(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """The compared fields of an image config (the JSON a saved archive carries), keyed as ``image inspect`` keys
    them."""
    run = _obj(cfg.get("config"))
    out = {k: _norm(cfg.get(src)) for k, src in PLATFORM_FIELDS.items()}
    out.update({k: _norm(run.get(k)) for k in RUN_FIELDS})
    return {k: v for k, v in out.items() if v is not None}


def inspect_fields(doc: Mapping[str, Any]) -> dict[str, Any]:
    """The same fields of an ``image inspect`` answer, from either store."""
    run = _obj(doc.get("Config"))
    out = {k: _norm(doc.get(k)) for k in PLATFORM_FIELDS}
    out.update({k: _norm(run.get(k)) for k in RUN_FIELDS})
    return {k: v for k, v in out.items() if v is not None}


def differs(rec: Mapping[str, Any], doc: Mapping[str, Any]) -> str:
    """Empty when the inspected image is the pinned one by its layers and config; else what differs. Never weaker
    than the config digest it stands in for: the filesystem (every layer's diff id, in order) and every config field
    a container runs by must be equal."""
    got = _obj(doc.get("RootFS")).get("Layers")
    layers: list[Any] = got if isinstance(got, list) else []
    signed = rec.get("layers")
    if layers != signed:
        return f"its layers differ from the bundle's ({len(layers)} here, {len(signed or [])} signed)"
    want = {k: _norm(v) for k, v in _obj(rec.get("config")).items()}
    want = {k: v for k, v in want.items() if v is not None}
    have = inspect_fields(doc)
    bad = sorted(k for k in set(want) | set(have) if want.get(k) != have.get(k))
    return f"its config differs from the bundle's ({', '.join(bad)})" if bad else ""


def read_env(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def resolve(
    deploy: Path,
    files: list[Path],
    has: Inspect | None = None,
    used: set[str] | None = None,
    inspect: InspectJson | None = None,
) -> tuple[dict[str, str | None], list[str], list[str]]:
    """``({variable: image id, or None to clear}, notes, missing references)`` for this box's compose files.
    ``used`` (OPS-004b, D-574): the images the rendered stack runs (``docker compose config --images`` with the
    box's overrides). A pinned variable whose image no service runs is noted and not asked for; without the list
    every pinned variable is asked for. ``inspect`` (H-149): ``image inspect`` of a reference, for the newer image
    store, where the bundle's image is proved by its layers and config under the bundle's tag."""
    has = has or docker_has
    inspect = inspect or docker_inspect
    pins = read_pin_records(deploy / PINS)
    env = {}
    for line in read_env(deploy / ".env"):
        k, sep, v = line.partition("=")
        if sep:
            env[k.strip()] = v.strip().strip("'\"")
    changes: dict[str, str | None] = {}
    notes: list[str] = []
    missing: list[str] = []
    for var, ref in sorted(compose_pins(files).items()):
        current = env.get(var, "")
        if current and not IMAGE_ID.match(current):
            notes.append(f"{var}: the site's own {current} (left alone)")
            continue
        if used is not None and ref not in used and not (current and current in used):
            notes.append(f"{var}: {ref}: no service of this box's stack runs it (not needed on this box)")
            continue
        if has(ref):
            notes.append(f"{var}: {ref} on this box by its digest")
            if current:
                changes[var] = None
            continue
        rec = pins.get(ref)
        if rec is None:
            missing.append(f"{var}: {ref} (no pin in deploy/image-pins.json)")
            continue
        image = rec["image"]
        if has(image):  # the classic store: the id is the config digest, content addressed
            notes.append(f"{var}: {ref} is the bundle's image {image[:19]} (this image store keeps no digests)")
            if current != image:
                changes[var] = image
            continue
        why = _proved_by_layers(rec, inspect)
        if why.startswith("sha256:"):
            notes.append(f"{var}: {ref} is the bundle's image under {rec['tag']}, proved by its layers and config "
                         f"(this image store's id {why[:19]})")  # fmt: skip
            if current != why:
                changes[var] = why
            continue
        notes.append(f"{var}: {ref} not proved on this box: {why}")
        missing.append(f"{var}: {ref}")
    return changes, notes, missing


def _proved_by_layers(rec: Mapping[str, Any], inspect: InspectJson) -> str:
    """The store's own ``Id`` of the bundle's image under its tag when its layers and config are the signed ones;
    else why not (never an id)."""
    if not rec.get("layers"):
        return "the bundle's pin names no layers to prove the image by (a bundle made before H-149)"
    tag = str(rec.get("tag") or bundle_tag(str(rec["ref"])))
    doc = inspect(tag)
    if doc is None:
        return f"no image {tag} on this box"
    bad = differs(rec, doc)
    if bad:
        return f"the image {tag} on this box is not the bundle's: {bad}; refused"
    have = str(doc.get("Id") or "")
    if not IMAGE_ID.match(have):
        return f"the image {tag} on this box has no image id ({have or 'none'})"
    return have


def write_env(path: Path, changes: dict[str, str | None]) -> None:
    if not changes:
        return
    lines = [ln for ln in read_env(path) if ln.partition("=")[0].strip() not in changes]
    lines += [f"{k}={v}" for k, v in sorted(changes.items()) if v]
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    _write_atomic(path, "\n".join(lines) + "\n", mode)


# --------------------------------------------------------------------------------- the bundle's side (make_bundle.sh)
def archive_pin(archive: Path, ref: str, tag: str) -> tuple[dict[str, Any], str]:
    """The pin record of a digest reference saved as ``tag`` in ``archive`` (a ``save`` archive), read out of the
    archive itself, and a warning (empty when none). The image id is the config's name, as before H-149. The layers
    and config are added only when the config blob is the content its digest names and carries the layer diff ids;
    otherwise the pin is today's, which proves the image on the classic store only, and the warning says so."""
    with tarfile.open(archive) as tf:
        m = tf.extractfile("manifest.json")
        entries = json.loads(m.read()) if m else []
        entry = next((e for e in entries if tag in (e.get("RepoTags") or [])), None)
        if entry is None:
            raise ValueError(f"{archive.name}: no image tagged {tag} in its manifest.json")
        path = str(entry.get("Config") or "")
        name = PurePosixPath(path).name.removesuffix(".json")
        if not re.fullmatch(r"[0-9a-f]{64}", name):
            raise ValueError(f"{archive.name}: no image id in the saved archive ({path or 'no Config'})")
        blob = tf.extractfile(path)
        raw = blob.read() if blob else b""
    pin: dict[str, Any] = {"ref": ref, "image": f"sha256:{name}"}
    if hashlib.sha256(raw).hexdigest() != name:
        return pin, f"{ref}: its config {path} is not the content its digest names: no layers pinned"
    cfg = json.loads(raw)
    layers = list(_obj(cfg.get("rootfs")).get("diff_ids") or [])
    if not layers or not all(isinstance(x, str) and IMAGE_ID.match(x) for x in layers):
        return pin, f"{ref}: its config names no layer diff ids: no layers pinned"
    pin.update({"tag": tag, "layers": layers, "config": config_fields(cfg)})
    return pin, ""


def bundle_pins(out: Path, items: Iterable[str]) -> tuple[int, list[str]]:
    """Write the bundle's ``image-pins.json`` from ``REF=TAG=ARCHIVE`` items; the count written and the warnings."""
    pins, warnings = [], []
    for item in items:
        ref, tag, archive = item.split("=", 2)
        pin, warn = archive_pin(Path(archive), ref, tag)
        pins.append(pin)
        if warn:
            warnings.append(warn)
    out.write_text(json.dumps({"pins": pins}, indent=1) + "\n", encoding="utf-8")
    return len(pins), warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="image_pins", description=__doc__.split("\n\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("pins", type=Path)
    m.add_argument("--deploy", type=Path, required=True)
    r = sub.add_parser("resolve")
    r.add_argument("--deploy", type=Path, required=True)
    r.add_argument("--files", required=True, help="the compose files, ':'-separated (deploy/.env COMPOSE_FILE)")
    r.add_argument("--used", default="", help="the images the rendered stack runs, one per line or word (D-574)")
    b = sub.add_parser("bundle-pins")
    b.add_argument("out", type=Path)
    b.add_argument("items", nargs="+", help="REF=TAG=ARCHIVE: a digest reference, its saved tag, its archive")
    a = ap.parse_args(argv)
    if a.cmd == "merge":
        print(f"image pins: {merge(a.pins, a.deploy)} from the bundle")
        return 0
    if a.cmd == "bundle-pins":
        try:
            count, warnings = bundle_pins(a.out, a.items)
        except (OSError, ValueError, KeyError, tarfile.TarError) as e:
            print(f"make_bundle: image pins: {e}", file=sys.stderr)
            return 1
        for w in warnings:
            print(
                f"make_bundle: WARNING image pins: {w}; this bundle's {w.split(':', 1)[0]} installs on the classic "
                "image store only (H-149)",
                file=sys.stderr,
            )
        print(f"    image pins: {count} digest references (image-pins.json)")
        return 0
    files = [Path(f) for f in a.files.split(":") if f]
    changes, notes, missing = resolve(a.deploy, files, used=set(a.used.split()) or None)
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
