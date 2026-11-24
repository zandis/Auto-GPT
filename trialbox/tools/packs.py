"""H-95: the two packs of a release, as the install sees them (standard library only: a clean host runs it).

A release is a software pack (the box's own images, host tree, rule sets, reference data, installer) and a model pack
(the engine image and the weights), each signed on its own (``tools/sign_bundle.py --pack``, manifest 1.4.0). The
software pack names its model pack by that pack's signed identity: its bundle id and the sha256 of its signed
``manifest.json``. Nothing here verifies a signature or a hash: ``tools/apply_update.sh`` does, before anything is
loaded. This module only finds and measures.

    python3 tools/packs.py find BUNDLE              # the model pack beside BUNDLE that it names (one line, or none)
    python3 tools/packs.py sizes BUNDLE [--model-pack FILE]   # installed size, the peak during the load, the stick
    python3 tools/packs.py space BUNDLE [--model-pack FILE] --docker-root DIR --models DIR --stage DIR --deploy DIR \
        [--updates DIR]    # exit 1, with the numbers, when a file system cannot hold what the load writes on it
                           # (exit 3: a manifest cannot be read; that is the verifier's to refuse)

``space`` sums, per file system, what the load writes there at its peak: the images into Docker's data root, the
weights into the models folder, the small payloads staged in passing, the host tree and the other files beside
deploy/. A pack the box already holds (its record in ``--updates``: ``model-pack.json`` or ``installed.json`` names
its manifest) writes nothing and is not counted, so a run again of the install is not refused for space it used.

``find`` looks only in the bundle's own folder, at the files named ``trialbox-models-*.pack``, and prints the one
whose signed manifest has the sha256 the software pack names; the file's name decides nothing.

``sizes``: the installed size is every payload as it lands on the box (images, weights, the host tree unpacked, rule
sets, reference data, other files); the peak is the installed size plus the small payloads staged in passing (the
host tree, rule sets, reference data and other files: the images and the weights are never staged, H-95); the bound
the install is held to is the installed size plus 10 % (tests/unit/test_load_from_the_stick_h95.py measures it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Any

MODEL_PACK_GLOB = "trialbox-models-*.pack"
STREAMED = ("image", "model")
PEAK_MARGIN = 1.10


def manifest_of(bundle: Path) -> tuple[dict[str, Any], str]:
    """A bundle's manifest.json and the sha256 of its bytes (unverified: for finding and measuring only)."""
    with tarfile.open(bundle, "r:") as tf:
        m = tf.extractfile("manifest.json")
        body = m.read() if m is not None else b""
    return json.loads(body), hashlib.sha256(body).hexdigest()


def required_model_pack(bundle: Path) -> dict[str, str] | None:
    pack = manifest_of(bundle)[0].get("pack") or {}
    return pack.get("requires_model") if pack.get("kind") == "software" else None


def find(bundle: Path) -> Path | None:
    need = required_model_pack(bundle)
    if need is None:
        return None
    for cand in sorted(bundle.parent.glob(MODEL_PACK_GLOB)):
        try:
            if manifest_of(cand)[1] == need["manifest_sha256"]:
                return cand
        except (OSError, KeyError, ValueError, tarfile.TarError):
            continue
    return None


def sizes(bundles: list[Path]) -> dict[str, int]:
    kinds: dict[str, int] = {}
    stick = largest = 0
    for b in bundles:
        stick += b.stat().st_size
        for f in manifest_of(b)[0].get("files") or []:
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + int(f["size"])
            if f["kind"] == "image":
                largest = max(largest, int(f["size"]))
    staged = sum(n for k, n in kinds.items() if k not in STREAMED)
    installed = sum(kinds.values()) + kinds.get("host", 0)  # the host tree also lands unpacked
    return {
        "installed": installed,
        "images": kinds.get("image", 0),
        "weights": kinds.get("model", 0),
        "rest": installed - kinds.get("image", 0) - kinds.get("model", 0),
        "staged": staged,
        # H-124 (the integrator's ruling 7132484063): the update runs the new release's code from its host tree
        # unpacked in the stage, one more copy while it runs; the bound allows the staged tar and that copy, read from
        # the signed manifest (2 x the host tree's declared size)
        "peak": installed + staged + kinds.get("host", 0),
        "bound": int(installed * PEAK_MARGIN) + 2 * kinds.get("host", 0),
        "stick": stick,
        # review F5: the engine's own working space in its data root while it loads, one archive at a time; not in
        # the peak above (this card's own writes), counted by ``space``
        "engine": largest,
    }


def _held(updates: Path | None) -> set[str]:
    out: set[str] = set()
    for name in ("model-pack.json", "installed.json"):
        f = updates / name if updates else None
        if f is not None and f.is_file() and not f.is_symlink():
            try:
                out.add(str(json.loads(f.read_text(encoding="utf-8")).get("manifest_sha256") or ""))
            except (OSError, ValueError, AttributeError):
                continue
    return out


def _existing(p: Path) -> Path:
    p = p.absolute()
    while not p.exists():
        p = p.parent
    return p


def space(bundles: list[Path], where: dict[str, Path], updates: Path | None = None,
          free_of: Any = None) -> tuple[bool, list[str]]:  # fmt: skip
    """(fits, one line per file system): what the load writes there against its free space."""
    held = _held(updates)
    per: dict[int, dict[str, Any]] = {}
    for b in bundles:
        manifest, sha = manifest_of(b)
        if sha in held:
            continue
        files = manifest.get("files") or []
        largest = max((int(f["size"]) for f in files if f["kind"] == "image"), default=0)
        if largest:  # review F5: the engine unpacks one archive at a time in its data root before it keeps it
            ex = _existing(where["docker_root"])
            d = per.setdefault(os.stat(ex).st_dev, {"path": ex, "need": 0, "what": {}})
            d["need"] += largest
            d["what"]["the engine's working space (largest image)"] = largest
        for f in files:
            kind, n = f["kind"], int(f["size"])
            targets = [("images", where["docker_root"])] if kind == "image" else \
                [("weights", where["models"])] if kind == "model" else \
                [("staged in passing", where["stage"]), ("unpacked and kept", where["deploy"])]  # fmt: skip
            if kind == "host":  # H-124 (7132484063): the update's own code, the tree unpacked in the stage in passing
                targets.append(("the update's own code, unpacked in passing", where["stage"]))
            for what, path in targets:
                ex = _existing(path)
                d = per.setdefault(os.stat(ex).st_dev, {"path": ex, "need": 0, "what": {}})
                d["need"] += n
                d["what"][what] = d["what"].get(what, 0) + n
    free_of = free_of or (lambda p: shutil.disk_usage(p).free)
    ok, lines = True, []
    for d in per.values():
        free = int(free_of(d["path"]))
        parts = ", ".join(f"{w} {gb(n)}" for w, n in d["what"].items())
        short = free < d["need"]
        ok = ok and not short
        lines.append(f"{d['path']}: needs {gb(d['need'])} at the peak ({parts}), free {gb(free)}"
                     + (": NOT ENOUGH" if short else ""))  # fmt: skip
    return ok, lines


def gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find")
    f.add_argument("bundle", type=Path)
    s = sub.add_parser("sizes")
    s.add_argument("bundle", type=Path)
    s.add_argument("--model-pack", type=Path)
    s.add_argument("--json", action="store_true")
    sp = sub.add_parser("space")
    sp.add_argument("bundle", type=Path)
    sp.add_argument("--model-pack", type=Path)
    for name in ("--docker-root", "--models", "--stage", "--deploy"):
        sp.add_argument(name, type=Path, required=True)
    sp.add_argument("--updates", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "find":
            got = find(a.bundle)
            if got is not None:
                print(got)
            return 0
        if a.cmd == "space":
            where = {"docker_root": a.docker_root, "models": a.models, "stage": a.stage, "deploy": a.deploy}
            fits, lines = space([a.bundle] + ([a.model_pack] if a.model_pack else []), where, a.updates)
            for line in lines:
                print(line)
            return 0 if fits else 1
        n = sizes([a.bundle] + ([a.model_pack] if a.model_pack else []))
    except (OSError, KeyError, ValueError, tarfile.TarError) as exc:  # the verifier says why, with stop (1)
        print(f"packs: cannot read the manifests ({exc})", file=sys.stderr)
        return 3
    if a.json:
        print(json.dumps(n, sort_keys=True))
        return 0
    print(f"installed size {gb(n['installed'])} (images {gb(n['images'])}, weights {gb(n['weights'])}, "
          f"the rest {gb(n['rest'])}); peak during the load {gb(n['peak'])}, at most {gb(n['bound'])} "
          f"(installed + 10 % + twice the host tree, H-124), and the engine's own working space up to {gb(n['engine'])} while an image loads; "
          f"the stick holds {gb(n['stick'])}")  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
