"""Verify (and stage) a signed offline update bundle (SPEC §10.1 "Updates"; DECISIONS D-77).

Bundle = an uncompressed tar holding exactly:

* ``manifest.json``     — ``UpdateManifest`` (schemas/update_manifest.schema.json): bundle id, signer, files with
                          path, kind (model | ruleset | image | other), sha256 and size;
* ``manifest.json.sig`` — base64 Ed25519 signature of the manifest bytes by the vendor key;
* ``files/<path>``      — one payload per manifest entry, nothing else.

Rejected (exit 1, nothing staged) when: the tar has unexpected members, links, absolute or ``..`` paths; the signature
does not verify with the box's vendor public key; the manifest violates its schema; a payload is missing, extra, or
its size / sha256 differs. ``--stage DIR`` copies the verified payloads into ``DIR/<kind>/<path>`` (re-hashed while
copying) for ``tools/apply_update.sh``.

    python tools/verify_update.py bundle.tar --pubkey deploy/keys/vendor_ed25519.pub [--stage /tmp/stage]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST = "manifest.json"
SIGNATURE = "manifest.json.sig"
PAYLOAD = "files/"


class Rejected(Exception):
    pass


def _safe(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or not p.parts or name != str(p):
        raise Rejected(f"unsafe path in bundle: {name!r}")
    return p


def load_public_key(path: Path) -> Any:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    data = path.read_bytes()
    if data.lstrip().startswith(b"-----BEGIN"):
        key = load_pem_public_key(data)
    else:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(data.strip()))
    if not isinstance(key, Ed25519PublicKey):
        raise Rejected("vendor key is not an Ed25519 public key")
    return key


def verify(bundle: Path, pubkey: Path, stage: Path | None = None) -> dict[str, Any]:
    from cryptography.exceptions import InvalidSignature

    key = load_public_key(pubkey)
    try:
        tf = tarfile.open(bundle, "r:")  # noqa: SIM115 - closed below
    except (tarfile.TarError, OSError) as exc:
        raise Rejected(f"not a tar bundle: {exc}") from exc
    with tf:
        members = {}
        for m in tf.getmembers():
            if m.isdir():
                _safe(m.name.rstrip("/"))
                continue
            if not m.isfile():
                raise Rejected(f"bundle member {m.name!r} is not a regular file")
            _safe(m.name)
            if m.name in members:
                raise Rejected(f"duplicate member {m.name!r}")
            members[m.name] = m
        if MANIFEST not in members or SIGNATURE not in members:
            raise Rejected("manifest.json and manifest.json.sig are required")

        def read(name: str) -> bytes:
            f = tf.extractfile(members[name])
            assert f is not None
            return f.read()

        manifest_bytes = read(MANIFEST)
        try:
            sig = base64.b64decode(read(SIGNATURE).strip(), validate=True)
            key.verify(sig, manifest_bytes)
        except (InvalidSignature, ValueError) as exc:
            raise Rejected("signature does not verify with the vendor key") from exc
        manifest = json.loads(manifest_bytes)
        from tb_contracts import schema_errors

        errs = schema_errors("update_manifest", manifest)
        if errs:
            raise Rejected("manifest violates update_manifest schema: " + "; ".join(errs[:5]))
        listed = {f"{PAYLOAD}{_safe(f['path'])}": f for f in manifest["files"]}
        if len(listed) != len(manifest["files"]):
            raise Rejected("manifest lists a path twice")
        present = {n for n in members if n not in (MANIFEST, SIGNATURE)}
        if present - set(listed):
            raise Rejected(f"files not in the manifest: {sorted(present - set(listed))[:5]}")
        if set(listed) - present:
            raise Rejected(f"files missing from the bundle: {sorted(set(listed) - present)[:5]}")
        try:
            _check_payloads(tf, members, listed, stage)
        except Rejected:
            if stage is not None:
                _cleanup(stage)
            raise
        if stage is not None:
            for part in stage.rglob("*.part"):
                part.rename(part.with_suffix(""))
            (stage / MANIFEST).write_bytes(manifest_bytes)
    manifest["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    return dict(manifest)


def _check_payloads(
    tf: tarfile.TarFile, members: dict[str, tarfile.TarInfo], listed: dict[str, Any], stage: Path | None
) -> None:
    for name, entry in sorted(listed.items()):
        m = members[name]
        if entry.get("size") is not None and m.size != entry["size"]:
            raise Rejected(f"{entry['path']}: size {m.size} != manifest {entry['size']}")
        f = tf.extractfile(m)
        assert f is not None
        h = hashlib.sha256()
        out = None
        if stage is not None:
            target = stage / entry["kind"] / str(_safe(entry["path"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            out = target.with_suffix(target.suffix + ".part").open("wb")
        try:
            while chunk := f.read(1 << 20):
                h.update(chunk)
                if out is not None:
                    out.write(chunk)
        finally:
            if out is not None:
                out.close()
        if h.hexdigest() != entry["sha256"]:
            raise Rejected(f"{entry['path']}: sha256 mismatch")


def _cleanup(stage: Path) -> None:
    for p in sorted(stage.rglob("*"), reverse=True):
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            p.rmdir()


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs"))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--pubkey", type=Path, required=True)
    ap.add_argument("--stage", type=Path)
    args = ap.parse_args(argv)
    try:
        m = verify(args.bundle, args.pubkey, args.stage)
    except Rejected as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "bundle_id": m["bundle_id"],
                "signer": m["signer"],
                "manifest_sha256": m["manifest_sha256"],
                "files": [{"path": f["path"], "kind": f["kind"]} for f in m["files"]],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
