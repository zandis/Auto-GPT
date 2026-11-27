"""The release build's key check (hygiene item 2): the vendor public key that goes on the stick beside the bundle
verifies every signature the stick carries, or the build is refused.

    python tools/bundle_keycheck.py --pub dist/vendor_ed25519.pub --bundle dist/trialbox-<id>.tar \\
        --bootstrap dist/trialbox-bootstrap.sh --sums dist/trialbox-<id>.tar.sha256

Three signatures, each checked with the one public key:

* ``manifest.json.sig`` inside the bundle: base64 of the Ed25519 signature over ``manifest.json`` (``sign_bundle.py
  build``), what the box's update path checks;
* ``<bootstrap>.sig``: the raw signature over the bootstrap (``sign_bundle.py sign-file``), what RUNBOOK section 1
  checks with openssl before running it;
* ``<sums>.sig``: the raw signature over the ``.sha256`` sidecar, whose lines must also match the bundle, the
  bootstrap and the bootstrap's ``.sig`` as they are on disk.

Exit 0 when all hold, 1 with one line per failure otherwise (``make_bundle.sh`` then removes what it wrote). It
reads public material only; no private key is read or written here.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import sys
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _public_key(path: Path) -> Ed25519PublicKey:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    key = load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError(f"{path.name} is not an Ed25519 public key")
    return key


def _verifies(key: Ed25519PublicKey, signature: bytes, data: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature

    try:
        key.verify(signature, data)
    except InvalidSignature:
        return False
    return True


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def problems(pub: Path, bundle: Path, bootstrap: Path, sums: Path) -> list[str]:
    """Why the stick's key does not verify what the stick carries; empty when it does."""
    try:
        key = _public_key(pub)
    except (OSError, ValueError) as exc:
        return [f"the public key {pub.name} is not readable as Ed25519 ({exc})"]
    out: list[str] = []
    try:
        with tarfile.open(bundle, "r:") as tf:
            body = tf.extractfile("manifest.json")
            sig = tf.extractfile("manifest.json.sig")
            manifest = body.read() if body is not None else b""
            manifest_sig = base64.b64decode((sig.read() if sig is not None else b"").strip(), validate=True)
    except (OSError, KeyError, tarfile.TarError, binascii.Error) as exc:
        out.append(f"{bundle.name}: no readable manifest.json and manifest.json.sig ({type(exc).__name__})")
    else:
        if not _verifies(key, manifest_sig, manifest):
            out.append(f"{bundle.name}: manifest.json.sig does not verify with {pub.name}")
    for path in (bootstrap, sums):
        sig_path = path.with_name(path.name + ".sig")
        try:
            ok = _verifies(key, sig_path.read_bytes(), path.read_bytes())
        except OSError as exc:
            out.append(f"{sig_path.name}: not readable ({type(exc).__name__})")
            continue
        if not ok:
            out.append(f"{sig_path.name} does not verify {path.name} with {pub.name}")
    try:
        lines = sums.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    listed: dict[str, str] = {}
    for line in lines:
        digest, _, name = line.partition("  ")
        listed[name.strip()] = digest.strip()
    folder = sums.parent
    for name in (bundle.name, bootstrap.name, bootstrap.name + ".sig"):
        if name not in listed:
            out.append(f"{sums.name} does not list {name}")
        elif not (folder / name).is_file() or listed[name] != _sha256(folder / name):
            out.append(f"{sums.name}: {name} does not match its line")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--pub", type=Path, required=True, help="the vendor public key that goes on the stick")
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--bootstrap", type=Path, required=True)
    ap.add_argument("--sums", type=Path, required=True, help="the bundle's .sha256 sidecar")
    args = ap.parse_args(argv)
    found = problems(args.pub, args.bundle, args.bootstrap, args.sums)
    for line in found:
        print(f"bundle_keycheck: {line}", file=sys.stderr)
    if found:
        return 1
    print(f"bundle_keycheck: {args.pub.name} verifies the manifest, {args.bootstrap.name}.sig and {args.sums.name}.sig")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
