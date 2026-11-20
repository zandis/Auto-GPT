"""The coordinating centre's study package tool (10D-3, D-1372): write, verify and show a study package v1.

    python -m tools.study_package keygen --out keys/                 # cc_ed25519.key (mode 600, keep offline) + .pub
    python -m tools.study_package write rulesets/RA-JAK --key keys/cc_ed25519.key --out RA-JAK-1.0.0.tbstudy \\
        [--created 2026-11-19] [--force] [--audit-dir DIR]
    python -m tools.study_package verify RA-JAK-1.0.0.tbstudy --trust-file study-trust.json
    python -m tools.study_package show RA-JAK-1.0.0.tbstudy         # the header; the signature is NOT checked

A host command for the coordinating centre's operator: no console page or action calls it, and nothing on the live
path reads a package yet (import and the register of coordinating-centre keys are 10D-4's). The package carries the
study's protocol part and protocol files only (``tb_common.study_manifest``, D-1366): no scopes, routing, review or
IRB record, and no patient data. It never prints key material: a key is named by its key id.

``write`` packs only a study whose manifest says ``status: approved``, and writes the box's audit event
``approve.study_package_exported`` (who: ``host:<user>``; the study, version, package id, the package's sha256, key id,
the date; never content) into the audit directory (``--audit-dir``, else ``TB_AUDIT_DIR``) BEFORE the package takes its
name: the package is first written beside ``--out`` under a hidden name, mode 600, and renamed only after the event is
written; no audit directory, or an event that cannot be written, and no package is left (D-1372, H4). Run as root, the
event's files are given back to the audit folder's owner by descriptor (``_give_back``, D-724).

``verify`` takes a trust file (``read_trust_file``: no link, nobody else may write it; ``load_trust``): each key
with the studies it may sign for and its purpose; a key trusted for updates is refused, and a key signs only the
studies its entry names (H5).
Exit status: 0 done; 1 refused (one sentence on stderr); 2 usage.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import hashlib
import json
import os
import stat
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from tb_common import study_manifest as sm
from tb_common import study_package as sp
from tb_common.crypto import ed25519_generate

PRIVATE = "cc_ed25519.key"
PUBLIC = "cc_ed25519.pub"
#: the audit event of a written package: in the approval family (what an approved protocol does next), as 10D-28's
#: ``approve.part_exported``; written by this host command to the box's chain directly (``tb_common.audit``)
EVENT = "approve.study_package_exported"


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


def actor() -> str:
    """Who runs the command, as the audit names a host command's user (10D-28's ``export_part``)."""
    try:
        return f"host:{getpass.getuser()}"
    except Exception:  # no user name (a container without one): the event still says it was a host command
        return "host command"


def _give_back(folder: Path) -> None:
    """D-724, by descriptor: run as root, the regular files of one link directly in the audit folder that belong to
    root (the event's day file, the writer's lock file: ``tb_common.audit`` writes only there) are given to the
    folder's owner with ``fchown`` on a descriptor opened without following a link. No subfolder, link, pipe or device
    is touched, and no mode is changed (root's ``fchown`` of a regular file also clears any set-id bit). Not
    ``backup._own_writes``, which changes owners by path. A no-op for any other user."""
    me = os.geteuid()
    if me != 0:
        return
    nofollow = os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    dfd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | nofollow)
    try:
        top = os.fstat(dfd)
        if top.st_uid == me:
            return
        for name in os.listdir(dfd):
            try:
                seen = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(seen.st_mode) or seen.st_uid != me or seen.st_nlink != 1:
                continue
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOCTTY | nofollow, dir_fd=dfd)
            except OSError:
                continue
            try:
                st = os.fstat(fd)
                if (
                    (st.st_dev, st.st_ino) == (seen.st_dev, seen.st_ino)
                    and stat.S_ISREG(st.st_mode)
                    and (st.st_uid == me and st.st_nlink == 1)
                ):
                    os.fchown(fd, top.st_uid, top.st_gid)
            finally:
                os.close(fd)
    finally:
        os.close(dfd)


#: a trust file is a few keys; a larger file is refused before it is read
TRUST_FILE_MAX_BYTES = 1 << 20


def read_trust_file(path: Path) -> list[sp.TrustedKey]:
    """The trusted keys of a ``tb-study-trust/1`` file (``study_package.load_trust``), read safely: opened without
    following a link, a regular file, which no other account may write (no group or other write bit; owned by this
    account or root), at most :data:`TRUST_FILE_MAX_BYTES`. Raises ``ValueError`` with one sentence."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        if os.path.islink(path):
            raise ValueError(f"the trust file {path} is a symbolic link; give the file itself") from None
        raise ValueError(f"the trust file {path} cannot be opened ({exc.strerror})") from None
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"the trust file {path} is not a regular file")
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError(
                f"the trust file {path} is a file others may write (mode {stat.S_IMODE(st.st_mode):o}); make it 644"
            )
        if st.st_uid not in (0, os.geteuid()):
            raise ValueError(f"the trust file {path} is owned by another account (uid {st.st_uid})")
        if st.st_size > TRUST_FILE_MAX_BYTES:
            raise ValueError(f"the trust file {path} is over {TRUST_FILE_MAX_BYTES:,} bytes")
        data = fh.read(TRUST_FILE_MAX_BYTES + 1)
    if len(data) > TRUST_FILE_MAX_BYTES:
        raise ValueError(f"the trust file {path} is over {TRUST_FILE_MAX_BYTES:,} bytes")
    return sp.load_trust(data)


def write(
    study: Path,
    key: Path,
    out: Path,
    created: str,
    *,
    audit_dir: Path | None,
    tz: str | None = None,
    force: bool = False,
    by: str | None = None,
    own: Callable[[Path], None] = _give_back,
) -> dict[str, Any]:
    """Write the package of ``study`` to ``out`` and return its header and sha256; the audit event first (H4).

    Refused (``ValueError``, one sentence, nothing left at ``out`` or beside it) with no audit directory, an ``out``
    that exists without ``force``, a study whose manifest is not ``status: approved``, a study the writer refuses,
    or an audit event that cannot be written. ``own`` gives what this process wrote in the audit folder to the
    folder's owner (:func:`_give_back`: only as root; a test passes its own). The package is written in the
    destination folder's descriptor under a hidden name (``O_EXCL | O_NOFOLLOW``, mode 600) and takes its name only
    after the event: by ``link`` (never over a file), or with ``force`` by ``rename`` over a regular file. When the
    event is written and the name cannot be taken, the sentence says so: an event then names a package that does not
    exist, and the command may be run again (it writes a new event)."""
    if audit_dir is None:
        raise ValueError(
            "no audit directory: give --audit-dir or set TB_AUDIT_DIR; a study package is written only with its "
            "audit event"
        )
    if not audit_dir.is_dir():
        raise ValueError(f"the audit directory {audit_dir} is not a folder; no package was written")
    try:
        there = os.lstat(out)
    except FileNotFoundError:
        there = None
    if there is not None and not force:
        raise ValueError(f"{out} exists; give --force to replace it")
    if there is not None and not stat.S_ISREG(there.st_mode):
        raise ValueError(f"{out} is not a regular file (a link, a folder or a device); --force replaces only a package")
    files = sp.read_folder(study)
    try:
        status = (yaml.safe_load(files.get(sm.MANIFEST, b"").decode("utf-8")) or {}).get("status")
    except (ValueError, yaml.YAMLError, AttributeError):
        status = None
    if status != "approved":
        raise ValueError(
            "the study's manifest does not say status: approved; only an approved protocol is packed (a draft is "
            "not: decision 51 is open)"
        )
    data = sp.build(files, _private_key(key), created)
    header = sp.header_of(data)
    sha = hashlib.sha256(data).hexdigest()
    part = f".{out.name}.{os.getpid()}.part"
    dfd = os.open(out.parent, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
        with os.fdopen(fd, "wb") as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            from tb_common.audit import AuditLog

            log = AuditLog(audit_dir, tz=tz) if tz else AuditLog(audit_dir)
            log.append(
                EVENT,
                actor=by or actor(),
                ruleset=header["study_id"],
                ruleset_version=header["version"],
                output_sha=sha,
                detail={
                    "package_id": header["package_id"],
                    "key_id": header["key_id"],
                    "created": header["created"],
                    "protocol_version": header["protocol_version"],
                    "criteria_sha256": header["criteria_sha256"],
                },
            )
        except Exception as exc:
            raise ValueError(
                f"the audit event could not be written ({type(exc).__name__}); no package was written"
            ) from None
        finally:
            with contextlib.suppress(OSError):
                own(audit_dir)  # D-724: the event and the writer's lock file, written as root, go to the folder's owner
        try:
            if force:
                os.replace(part, out.name, src_dir_fd=dfd, dst_dir_fd=dfd)
            else:  # never over a file that appeared meanwhile
                os.link(part, out.name, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
            os.fsync(dfd)
        except OSError as exc:
            why = "it exists now; give --force to replace it" if isinstance(exc, FileExistsError) else exc.strerror
            raise ValueError(
                f"the audit event {EVENT} was written for package {header['package_id']} (sha256 {sha}), but the "
                f"package could not take the name {out} ({why}): no package was left, so that event names a package "
                "that does not exist; run the command again (it writes a new event)"
            ) from None
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(part, dir_fd=dfd)
        os.close(dfd)
    return {**header, "sha256": sha}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen", help="a coordinating-centre key pair")
    k.add_argument("--out", type=Path, required=True)
    w = sub.add_parser("write", help="the package of an approved study folder rulesets/<ID>/, audited")
    w.add_argument("study", type=Path)
    w.add_argument("--key", type=Path, required=True, help="the coordinating centre's Ed25519 private key (PEM)")
    w.add_argument("--out", type=Path, required=True)
    w.add_argument("--created", help="the package's date, YYYY-MM-DD (default: today, UTC)")
    w.add_argument("--force", action="store_true", help="replace --out when it exists")
    w.add_argument("--audit-dir", type=Path, help="the box's audit folder (default: TB_AUDIT_DIR)")
    v = sub.add_parser("verify", help="check a package against a trust file")
    v.add_argument("package", type=Path)
    v.add_argument(
        "--trust-file", type=Path, required=True, help="the trusted keys, each with its studies (tb-study-trust/1)"
    )
    s = sub.add_parser("show", help="print a package's header (the signature is not checked)")
    s.add_argument("package", type=Path)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "keygen":
            priv, pub = keygen(args.out)
            print(f"wrote {priv} (keep it offline, mode 600) and {pub} (key id {sp.key_id(pub.read_bytes())})")
        elif args.cmd == "write":
            env_dir = os.environ.get("TB_AUDIT_DIR")
            h = write(
                args.study,
                args.key,
                args.out,
                args.created or datetime.now(UTC).date().isoformat(),
                audit_dir=args.audit_dir or (Path(env_dir) if env_dir else None),
                tz=os.environ.get("TB_TZ") or None,
                force=args.force,
            )
            print(
                f"wrote {args.out}: study {h['study_id']} version {h['version']} (protocol {h['protocol_version']}), "
                f"package {h['package_id']}, criteria hash {h['criteria_sha256']}, signed by key {h['key_id']}, "
                f"audited as {EVENT}"
            )
        elif args.cmd == "verify":
            got = sp.verify_file(args.package, read_trust_file(args.trust_file))
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
