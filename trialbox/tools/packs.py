"""H-95: the two packs of a release, as the install sees them (standard library only: a clean host runs it).

A release is a software pack (the box's own images, host tree, rule sets, reference data, installer) and a model pack
(the engine image and the weights), each signed on its own (``tools/sign_bundle.py --pack``, manifest 1.4.0). The
software pack names its model pack by that pack's signed identity: its bundle id and the sha256 of its signed
``manifest.json``. Nothing here verifies a signature or a hash: ``tools/apply_update.sh`` does, before anything is
loaded. This module only finds and measures.

    python3 tools/packs.py find BUNDLE              # the model pack beside BUNDLE that it names (one line, or none)
    python3 tools/packs.py sizes BUNDLE [--model-pack FILE]   # installed size, the peak during the load, the stick

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
    stick = 0
    for b in bundles:
        stick += b.stat().st_size
        for f in manifest_of(b)[0].get("files") or []:
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + int(f["size"])
    staged = sum(n for k, n in kinds.items() if k not in STREAMED)
    installed = sum(kinds.values()) + kinds.get("host", 0)  # the host tree also lands unpacked
    return {
        "installed": installed,
        "images": kinds.get("image", 0),
        "weights": kinds.get("model", 0),
        "rest": installed - kinds.get("image", 0) - kinds.get("model", 0),
        "staged": staged,
        "peak": installed + staged,
        "bound": int(installed * PEAK_MARGIN),
        "stick": stick,
    }


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
    a = ap.parse_args(argv)
    try:
        if a.cmd == "find":
            got = find(a.bundle)
            if got is not None:
                print(got)
            return 0
        n = sizes([a.bundle] + ([a.model_pack] if a.model_pack else []))
    except (OSError, KeyError, ValueError, tarfile.TarError) as exc:
        print(f"packs: {exc}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(n, sort_keys=True))
        return 0
    print(f"installed size {gb(n['installed'])} (images {gb(n['images'])}, weights {gb(n['weights'])}, "
          f"the rest {gb(n['rest'])}); peak during the load {gb(n['peak'])}, at most {gb(n['bound'])} "
          f"(installed + 10 %); the stick holds {gb(n['stick'])}")  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
