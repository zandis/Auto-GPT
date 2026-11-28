"""The release build's key check (hygiene item 2): the vendor public key that goes on the stick beside the bundle
verifies every signature the stick carries, or the build is refused.

    python tools/bundle_keycheck.py --pub dist/vendor_ed25519.pub --bundle dist/trialbox-<id>.tar \\
        --bootstrap dist/trialbox-bootstrap.sh --sums dist/trialbox-<id>.tar.sha256

Three signatures, each checked with the one public key:

* ``manifest.json.sig`` inside the bundle: base64 of the Ed25519 signature over ``manifest.json`` (``sign_bundle.py
  build``), what the box's update path checks;
* ``<bootstrap>.sig``: the raw signature over the bootstrap (``sign_bundle.py sign-file``), what RUNBOOK section 1
  checks with openssl before running it;
* ``<sums>.sig``: the raw signature over the ``.sha256`` sidecar, which is read once (the bytes verified are the
  bytes parsed) and holds exactly one line for each of the bundle, the bootstrap and the bootstrap's ``.sig``, each
  matching the file at the path given, and no other line.

Exit 0 when all hold, 1 with one line per failure otherwise (``make_bundle.sh`` then publishes nothing). It
reads public material only; no private key is read or written here.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import re
import sys
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


_ENTRY = re.compile(r"(?P<digest>[0-9a-f]{64})  (?P<name>[^/\\\n]+)")  # sha256sum's own line


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


def _read(path: Path, out: list[str]) -> bytes | None:
    """The file's bytes, read once; None, and a line in ``out``, when it cannot be read."""
    try:
        return path.read_bytes()
    except OSError as exc:
        out.append(f"{path.name}: not readable ({type(exc).__name__})")
        return None


def problems(pub: Path, bundle: Path, bootstrap: Path, sums: Path) -> list[str]:
    """Why the stick's key does not verify what the stick carries; empty when it does."""
    from cryptography.exceptions import UnsupportedAlgorithm

    try:
        key = _public_key(pub)
    except (OSError, ValueError, UnsupportedAlgorithm) as exc:
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
    # each signed file is read once: the bytes that are verified are the bytes that are parsed
    boot_sig = bootstrap.with_name(bootstrap.name + ".sig")
    sums_sig = sums.with_name(sums.name + ".sig")
    boot_data, boot_sig_data = _read(bootstrap, out), _read(boot_sig, out)
    sums_data, sums_sig_data = _read(sums, out), _read(sums_sig, out)
    for name, sig_name, data, signature in (
        (bootstrap.name, boot_sig.name, boot_data, boot_sig_data),
        (sums.name, sums_sig.name, sums_data, sums_sig_data),
    ):
        if data is not None and signature is not None and not _verifies(key, signature, data):
            out.append(f"{sig_name} does not verify {name} with {pub.name}")
    if sums_data is None:
        return out
    try:
        text = sums_data.decode("utf-8")
    except UnicodeDecodeError:
        return [*out, f"{sums.name}: not UTF-8 text"]
    # split as sha256sum -c reads it: on LF only (a vertical tab or a CR is part of a line), one final LF allowed
    lines = text.removesuffix("\n").split("\n")
    if bundle.name in (bootstrap.name, boot_sig.name):
        return [*out, f"the bundle and the bootstrap are both named {bundle.name}: one sidecar cannot cover both"]
    # one entry for each of the three files and none for any other; each file is hashed at the path given
    covered = {bundle.name: bundle, bootstrap.name: bootstrap, boot_sig.name: boot_sig}
    listed: dict[str, str] = {}
    repeated: set[str] = set()
    for number, line in enumerate(lines, 1):
        entry = _ENTRY.fullmatch(line)
        if entry is None:
            out.append(f"{sums.name}: line {number} is not '<sha256>  <name>'")
        elif entry["name"] not in covered:
            out.append(f"{sums.name} lists {entry['name']}, which is not one of the three it covers")
        elif entry["name"] in listed:
            repeated.add(entry["name"])
            out.append(f"{sums.name} lists {entry['name']} more than once")
        else:
            listed[entry["name"]] = entry["digest"]
    for name, path in covered.items():
        if name not in listed:
            out.append(f"{sums.name} does not list {name}")
            continue
        try:
            matches = listed[name] == _sha256(path)
        except OSError:
            matches = False
        if not matches and name not in repeated:
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
