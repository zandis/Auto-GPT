"""Vendor side of the offline update channel (SPEC §10.1; DECISIONS D-77): create the Ed25519 key pair and build a
signed bundle that ``tools/apply_update.sh`` accepts.

    python tools/sign_bundle.py keygen --out keys/                       # vendor_ed25519.key (keep offline) + .pub
    python tools/sign_bundle.py build --key keys/vendor_ed25519.key --id 2026.10-1 --release-seq 7 \\
        --out update-2026.10-1.tar [--min-installed 5] [--valid-days 365] [--compat compat.json] \\
        [--release release.json --images-lock deploy/images.lock] [--rotate-add new.pub [--rotate-retire KEY_ID]] \\
        ruleset:dist/GOUT-COH-1.0.0.zip image:dist/trialbox-py-1.0.1.tar model:models/qwen/model.safetensors

``kind:path[=bundle/path]`` — the payload is stored as ``files/<bundle path>`` (default: the file name).

D-210 (manifest 1.2.0): ``release_seq`` (monotonic; a box refuses one not above what it has), ``min_installed_version``,
``key_id`` (computed from the signing key), ``not_after``, the compatibility table ``compat.json`` (default: one row
that accepts any installed state; a release that changes a schema or a pin ships its own, see
``tools/update_status.py``), and, for a bundle with images, ``release.json`` and ``images.lock`` (T-110's release build
writes both; ``verify_update.py`` refuses images without them or with a null digest). ``--rotate-add`` makes a key
rotation bundle: signed by a trusted key, it adds the new key and may retire one; a box accepts it once.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

KINDS = ("model", "ruleset", "image", "refdata", "other")


def keygen(out: Path) -> tuple[Path, Path]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    out.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    priv = out / "vendor_ed25519.key"
    pub = out / "vendor_ed25519.pub"
    priv.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    priv.chmod(0o600)
    pub.write_bytes(
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    return priv, pub


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _json(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def permissive_compat(bundle_id: str) -> dict[str, Any]:
    """A compatibility table with one row that accepts any installed state (a bundle that changes no schema)."""
    return {"format": "trialbox-update-compat/1", "bundle_id": bundle_id,
            "rows": [{"vocabulary_release": "*", "model_pin": "*", "prompt_registry": "*"}]}  # fmt: skip


def rotation_for(new_pub: Path, retire: str | None = None) -> dict[str, Any]:
    """The manifest's ``rotation`` that adds the key in ``new_pub`` (and retires ``retire``)."""
    from tools.verify_update import key_id, load_public_key, raw_public

    k = load_public_key(new_pub)
    return {"add_key_id": key_id(k), "add_public_key": base64.b64encode(raw_public(k)).decode(),
            "retire_key_id": retire}  # fmt: skip


def build(
    key_path: Path,
    bundle_id: str,
    items: list[tuple[str, Path, str]],
    out: Path,
    signer: str = "TrialBox vendor",
    description: str | None = None,
    created_at: str | None = None,
    *,
    release_seq: int = 1,
    min_installed_version: int = 0,
    not_after: str | None = None,
    compat: dict[str, Any] | None = None,
    release: dict[str, Any] | None = None,
    images_lock: dict[str, Any] | None = None,
    rotation: dict[str, Any] | None = None,
    valid_days: int = 365,
) -> dict[str, Any]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    key = load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("vendor key must be Ed25519")
    files = []
    for kind, src, dest in items:
        if kind not in KINDS:
            raise SystemExit(f"unknown kind {kind!r} (one of {', '.join(KINDS)})")
        files.append({"path": dest, "kind": kind, "sha256": _sha(src), "size": src.stat().st_size})
    from tools.verify_update import key_id

    created = created_at or datetime.now(UTC).isoformat(timespec="seconds")
    meta: dict[str, bytes] = {"compat.json": _json(compat or permissive_compat(bundle_id))}
    if release is not None:
        meta["release.json"] = _json(release)
    if images_lock is not None:
        meta["images.lock"] = _json(images_lock)
    manifest: dict[str, Any] = {
        "bundle_id": bundle_id,
        "created_at": created,
        "signer": signer,
        "description": description,
        "files": files,
        "release_seq": release_seq,
        "min_installed_version": min_installed_version,
        "key_id": key_id(key.public_key()),
        "not_after": not_after
        or (datetime.fromisoformat(created) + timedelta(days=valid_days)).isoformat(timespec="seconds"),
    }
    for name, field in (("compat.json", "compat_sha256"), ("release.json", "release_sha256"),
                        ("images.lock", "images_lock_sha256")):  # fmt: skip
        if name in meta:
            manifest[field] = hashlib.sha256(meta[name]).hexdigest()
    if rotation is not None:
        manifest["rotation"] = rotation
    from tb_contracts import validate

    validate("update_manifest", manifest)
    body = (json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    sig = base64.b64encode(key.sign(body)) + b"\n"

    def add(tf: tarfile.TarFile, name: str, data: bytes | None = None, src: Path | None = None) -> None:
        info = tarfile.TarInfo(name)
        info.mtime = 0
        info.mode = 0o644
        if src is not None:
            info.size = src.stat().st_size
            with src.open("rb") as fh:
                tf.addfile(info, fh)
        else:
            assert data is not None
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

    with tarfile.open(out, "w:", format=tarfile.PAX_FORMAT) as tf:
        add(tf, "manifest.json", body)
        add(tf, "manifest.json.sig", sig)
        for name, data in meta.items():
            add(tf, name, data)
        for (_, src, dest), _f in zip(items, files, strict=True):
            add(tf, f"files/{dest}", src=src)
    return manifest


def main(argv: list[str] | None = None) -> int:
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "libs"), str(root)]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    kg = sub.add_parser("keygen")
    kg.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("build")
    b.add_argument("--key", type=Path, required=True)
    b.add_argument("--id", required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--signer", default="TrialBox vendor")
    b.add_argument("--description")
    b.add_argument("--release-seq", type=int, required=True, help="monotonic release counter (D-210)")
    b.add_argument("--min-installed", type=int, default=0, help="lowest installed release_seq it applies over")
    b.add_argument("--valid-days", type=int, default=365, help="not_after = created + this many days")
    b.add_argument("--compat", type=Path, help="compat.json (default: accepts any installed state)")
    b.add_argument("--release", type=Path, help="release.json (T-110; required with images)")
    b.add_argument("--images-lock", type=Path, help="the release's deploy/images.lock (required with images)")
    b.add_argument("--rotate-add", type=Path, help="a key rotation bundle: the new vendor public key")
    b.add_argument("--rotate-retire", help="with --rotate-add: the key_id to retire")
    b.add_argument("items", nargs="+", help="kind:path[=bundle/path]")
    args = ap.parse_args(argv)
    if args.cmd == "keygen":
        priv, pub = keygen(args.out)
        print(f"wrote {priv} (keep offline) and {pub} (install on boxes as deploy/keys/vendor_ed25519.pub)")
        return 0
    items = []
    for it in args.items:
        kind, _, rest = it.partition(":")
        src, _, dest = rest.partition("=")
        items.append((kind, Path(src), dest or Path(src).name))

    def load(p: Path | None) -> dict[str, Any] | None:
        return json.loads(p.read_text(encoding="utf-8")) if p else None

    m = build(args.key, args.id, items, args.out, args.signer, args.description, release_seq=args.release_seq,
              min_installed_version=args.min_installed, valid_days=args.valid_days, compat=load(args.compat),
              release=load(args.release), images_lock=load(args.images_lock),
              rotation=rotation_for(args.rotate_add, args.rotate_retire) if args.rotate_add else None)  # fmt: skip
    print(f"wrote {args.out}: {len(m['files'])} files, bundle {m['bundle_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
