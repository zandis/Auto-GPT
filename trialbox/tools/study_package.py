"""The coordinating centre's study package tool (10D-3, D-1372): write, verify and show a study package v1.

    python -m tools.study_package keygen --out keys/                 # cc_ed25519.key (mode 600, keep offline) + .pub
    python -m tools.study_package write rulesets/RA-JAK --key keys/cc_ed25519.key --out RA-JAK-1.0.0.tbstudy \\
        [--created 2026-11-19]
    python -m tools.study_package verify RA-JAK-1.0.0.tbstudy --trust keys/cc_ed25519.pub [--trust other.pub]
    python -m tools.study_package show RA-JAK-1.0.0.tbstudy         # the header; the signature is NOT checked

A tool for the coordinating centre's operator: no console page or action calls it, and nothing on the live path reads
a package yet (import and the register of coordinating-centre keys are 10D-4's). The package carries the study's
protocol part and protocol files only (``tb_common.study_manifest``, D-1366): no scopes, routing, review or IRB
record, and no patient data. It never prints key material: a key is named by its key id.
Exit status: 0 done; 1 refused (one sentence on stderr); 2 usage.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

from tb_common import study_package as sp
from tb_common.crypto import ed25519_generate

PRIVATE = "cc_ed25519.key"
PUBLIC = "cc_ed25519.pub"


def _private_key(path: Path) -> bytes:
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError(f"the key file {path} may be read by others (mode {stat.S_IMODE(mode):o}); make it 600 first")
    return path.read_bytes()


def keygen(out: Path) -> tuple[Path, Path]:
    """A coordinating-centre key pair: the private key (PEM, PKCS8, mode 600) and its public key (PEM)."""
    out.mkdir(parents=True, exist_ok=True)
    priv, pub = out / PRIVATE, out / PUBLIC
    if priv.exists():
        raise ValueError(f"{priv} exists; a key is never replaced")
    private_pem, public_pem = ed25519_generate()
    fd = os.open(priv, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(private_pem)
    pub.write_bytes(public_pem)
    return priv, pub


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen", help="a coordinating-centre key pair")
    k.add_argument("--out", type=Path, required=True)
    w = sub.add_parser("write", help="the package of a study folder rulesets/<ID>/")
    w.add_argument("study", type=Path)
    w.add_argument("--key", type=Path, required=True, help="the coordinating centre's Ed25519 private key (PEM)")
    w.add_argument("--out", type=Path, required=True)
    w.add_argument("--created", help="the package's date, YYYY-MM-DD (default: today, UTC)")
    v = sub.add_parser("verify", help="check a package against trusted public keys")
    v.add_argument("package", type=Path)
    v.add_argument("--trust", type=Path, action="append", required=True, help="a trusted public key (PEM)")
    s = sub.add_parser("show", help="print a package's header (the signature is not checked)")
    s.add_argument("package", type=Path)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "keygen":
            priv, pub = keygen(args.out)
            print(f"wrote {priv} (keep it offline, mode 600) and {pub} (key id {sp.key_id(pub.read_bytes())})")
        elif args.cmd == "write":
            created = args.created or datetime.now(UTC).date().isoformat()
            data = sp.build_dir(args.study, _private_key(args.key), created)
            args.out.write_bytes(data)
            h = sp.header_of(data)
            print(
                f"wrote {args.out}: study {h['study_id']} version {h['version']} (protocol {h['protocol_version']}), "
                f"package {h['package_id']}, criteria hash {h['criteria_sha256']}, signed by key {h['key_id']}"
            )
        elif args.cmd == "verify":
            got = sp.verify_file(args.package, [p.read_bytes() for p in args.trust])
            h = got.header
            print(
                f"verified {args.package}: study {h['study_id']} version {h['version']}, package {h['package_id']}, "
                f"{len(got.files)} protocol files, criteria hash {h['criteria_sha256']}, signed by key {h['key_id']}"
            )
        else:
            header = sp.header_of(sp.read_file(args.package))
            print(json.dumps(header, ensure_ascii=False, indent=1, sort_keys=True))
            print("(the signature is not checked here: use verify)")
    except (ValueError, OSError) as exc:
        print(f"study package: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
