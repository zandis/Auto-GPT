"""Vendor side of the offline update channel (SPEC §10.1; DECISIONS D-77): create the Ed25519 key pair and build a
signed bundle that ``tools/apply_update.sh`` accepts.

    python tools/sign_bundle.py keygen --out keys/                       # vendor_ed25519.key (keep offline) + .pub
    python tools/sign_bundle.py build --key keys/vendor_ed25519.key --id 2026.10-1 --out update-2026.10-1.tar \\
        ruleset:dist/GOUT-COH-1.0.0.zip image:dist/trialbox-py-1.0.1.tar model:models/qwen/model.safetensors

``kind:path[=bundle/path]`` — the payload is stored as ``files/<bundle path>`` (default: the file name).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KINDS = ("model", "ruleset", "image", "other")


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


def build(
    key_path: Path,
    bundle_id: str,
    items: list[tuple[str, Path, str]],
    out: Path,
    signer: str = "TrialBox vendor",
    description: str | None = None,
    created_at: str | None = None,
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
    manifest: dict[str, Any] = {
        "bundle_id": bundle_id,
        "created_at": created_at or datetime.now(UTC).isoformat(timespec="seconds"),
        "signer": signer,
        "description": description,
        "files": files,
    }
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
        for (_, src, dest), _f in zip(items, files, strict=True):
            add(tf, f"files/{dest}", src=src)
    return manifest


def main(argv: list[str] | None = None) -> int:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs"))
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
    m = build(args.key, args.id, items, args.out, args.signer, args.description)
    print(f"wrote {args.out}: {len(m['files'])} files, bundle {m['bundle_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
