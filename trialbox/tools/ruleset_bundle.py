"""Vendor side, interim for the dry run: sign an update bundle that carries rule-set parts alone (plan 10 row 10D-28,
review 19-9; D-1369).

A rule-set part is a rule set compiled and approved on the head box (``python -m criteria_compiler.export_part``).
Until the coordinating centre signs a study package (10D-2 to 10D-4), the vendor carries it to a screen-only site box
in an ordinary update bundle, **signed with the vendor key** (``tools/sign_bundle.py``; no other key type), which
``tools/apply_update.sh`` verifies and applies as any update: verify (signature, release_seq, compat.json, each
payload's sha256), backup, rollback point, the rule-set import (``criteria_compiler.import_ruleset``: approved,
equivalence gate, the part's content sha256), check, ``update.applied`` audited. The bundle carries no image and no
host tree, so it changes no code; the box keeps the release it runs (``installed.json`` keeps its commit).

    python -m tools.ruleset_bundle --key keys/vendor_ed25519.key --id 2026.11-1-rs1 --release-seq 4 \\
        --out dist/trialbox-2026.11-1-rs1.tar GZQO-1.0.0.part.zip [more parts]

``--release-seq`` takes the next number after the box's installed one (a bundle is refused unless it is higher, D-210):
a rule-set bundle uses one number of the vendor's sequence like a release. Beside a release, a part rides in
``tools/make_bundle.sh --rulesets DIR`` (every ``*.zip`` of DIR is a payload of kind ruleset); this tool reads each
part before it is signed, as the receiving box will. Such a bundle is for the dry run: it expires after
``--valid-days`` (30 by default, at most 90), where a release bundle's default is a year.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
#: a rule-set bundle is for the dry run: it expires after about a month (a release bundle's default is 365 days)
VALID_DAYS = 30
MAX_VALID_DAYS = 90


def build(key: Path, bundle_id: str, parts: list[Path], out: Path, *, release_seq: int, min_installed: int = 0,
          valid_days: int = VALID_DAYS) -> dict[str, Any]:  # fmt: skip
    """Check each part (``tb_common.ruleset_part.open_part``) and sign the bundle; refuses a file that is no part.

    The bytes signed are the bytes checked (the review's N1): each part is read once, checked, and handed to
    ``sign_bundle.build`` as a copy in a private folder of this run; after the build, each packed member is read back
    from the bundle and its sha256, and the one the signed manifest records, must equal the checked bytes' sha256,
    else the bundle is removed and refused (``sign_bundle.py`` is unchanged)."""
    from tb_common.ruleset_part import PartRefused, open_part

    from tools import sign_bundle

    if not parts:
        raise SystemExit("ruleset_bundle: no rule-set part given")
    if not 1 <= valid_days <= MAX_VALID_DAYS:
        raise SystemExit(
            f"ruleset_bundle: --valid-days {valid_days}: a dry-run bundle is valid 1 to {MAX_VALID_DAYS} days"
        )
    names: list[str] = []
    origins: list[dict[str, Any]] = []
    checked: dict[str, bytes] = {}
    if len({p.name for p in parts}) != len(parts):
        raise SystemExit("ruleset_bundle: two parts have the same file name")
    for p in parts:
        data = p.read_bytes()  # read once: these bytes are checked, copied, signed and compared after the build
        try:
            rid, _files, manifest, origin = open_part(data)
        except PartRefused as exc:
            raise SystemExit(f"ruleset_bundle: {p}: {exc}") from exc
        names.append(f"{rid} v{manifest.get('version')} (part sha256 {str(origin['part_sha256'])[:12]})")
        origins.append(origin)
        checked[p.name] = data
    compat, floor = pinned_compat(bundle_id, origins)
    with tempfile.TemporaryDirectory(prefix="ruleset-bundle-") as tmp:  # mode 0700: this run's own copies
        items = []
        for name, data in checked.items():
            copy = Path(tmp) / name
            copy.write_bytes(data)
            items.append(("ruleset", copy, name))
        m = sign_bundle.build(
            key, bundle_id, items, out,
            description="Rule set(s) compiled and approved on another box, interim for the dry run (D-1369): "
            + "; ".join(names),
            release_seq=release_seq, min_installed_version=max(min_installed, floor), valid_days=valid_days,
            compat=compat,
        )  # fmt: skip
    _signed_is_checked(out, m, checked)
    return m


def _signed_is_checked(out: Path, manifest: dict[str, Any], checked: dict[str, bytes]) -> None:
    """Each part as packed in the bundle, and as its signed manifest records it, is the part that was checked; else
    the bundle is removed and the build refused."""
    recorded = {f["path"]: f["sha256"] for f in manifest["files"]}
    with tarfile.open(out) as tf:
        packed = {}
        for name in checked:
            fh = tf.extractfile(f"files/{name}")
            packed[name] = hashlib.sha256(fh.read() if fh else b"").hexdigest()
    for name, data in checked.items():
        want = hashlib.sha256(data).hexdigest()
        if recorded.get(name) != want or packed[name] != want:
            out.unlink(missing_ok=True)
            raise SystemExit(
                f"ruleset_bundle: {name} changed between its check and the signature (checked sha256 {want[:12]}, "
                f"signed {str(recorded.get(name))[:12]}, packed {packed[name][:12]}); no bundle was written"
            )


def pinned_compat(bundle_id: str, origins: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    """D-1369 (the second review): the compatibility table and the lowest installed release the parts were compiled
    for, so the verifier refuses a box that does not match before anything changes. ``vocabulary_release``: the
    parts' terminology release (one, when any part pins one); the floor: the highest ``release_seq`` that compiled a
    part (a box on an older release runs an older engine). The serving model is the site's (D-1366) and the prompt pin
    is checked by the import against the box's registry, so those columns stay ``*``."""
    from tools import sign_bundle

    terms = {o["pins"].get("terminology_release") for o in origins} - {None}
    if len(terms) > 1:
        raise SystemExit(
            f"ruleset_bundle: the parts pin different terminology releases {sorted(terms)}: one bundle each"
        )
    compat = sign_bundle.permissive_compat(bundle_id)
    if terms:
        compat["rows"][0]["vocabulary_release"] = sorted(terms)
    seqs = [o["compiled_on"].get("release_seq") for o in origins]
    return compat, max([s for s in seqs if isinstance(s, int)], default=0)


def main(argv: list[str] | None = None) -> int:
    for p in (str(ROOT / "libs"), str(ROOT / "services"), str(ROOT)):  # services: the compiler's comment check
        if p not in sys.path:
            sys.path.insert(0, p)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", type=Path, required=True, help="the vendor's Ed25519 key")
    ap.add_argument("--id", required=True)
    ap.add_argument("--release-seq", type=int, required=True)
    ap.add_argument("--min-installed", type=int, default=0)
    ap.add_argument("--valid-days", type=int, default=VALID_DAYS, help="not_after = now + this many days (at most 90)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("parts", nargs="+", type=Path)
    args = ap.parse_args(argv)
    m = build(args.key, args.id, args.parts, args.out, release_seq=args.release_seq, min_installed=args.min_installed,
              valid_days=args.valid_days)  # fmt: skip
    print(f"wrote {args.out}: {len(m['files'])} rule-set part(s), bundle {m['bundle_id']}, release_seq "
          f"{m['release_seq']}; apply it with tools/apply_update.sh")  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
