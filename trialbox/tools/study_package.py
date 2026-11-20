"""The coordinating centre's study package tool (10D-3, D-1372): write, verify and show a study package v1.

    python -m tools.study_package keygen --out keys/                 # cc_ed25519.key (mode 600, keep offline) + .pub
    python -m tools.study_package write /data/rulesets/RA-JAK --key /run/tb-study-key/cc_ed25519.key \\
        --out /data/study-out/RA-JAK-1.0.0.tbstudy [--created 2026-11-19] [--force] [--trust-file FILE]
    python -m tools.study_package verify RA-JAK-1.0.0.tbstudy --trust-file study-trust.json
    python -m tools.study_package show RA-JAK-1.0.0.tbstudy         # the header; the signature is NOT checked

A command for the coordinating centre's operator: no console page or action calls it, and nothing on the live path
reads a package yet (import and the register of coordinating-centre keys are 10D-4's). The package carries the
study's protocol part and protocol files only (``tb_common.study_manifest``, D-1366): no scopes, routing, review or
IRB record, and no patient data. It never prints key material: a key is named by its key id.

``write`` never runs as root (:data:`SUPPORTED_RUN`): it runs in the criteria compiler's container as its service
account (uid 10001), as 10D-28's ``criteria_compiler.export_part`` does, and audits through the product's writer
(``tb_common.audit_writer.open_audit``: the journal with ``TB_AUDIT_WRITER=db``, as in that container; else the chain
in ``TB_AUDIT_DIR``, a folder the running account owns). It packs the bytes of the study's approval tag
``<ID>/v<version>`` in the box's rule-set store (the folder's parent, a git repository): a folder whose files differ
from that tag, a version with no tag, a tag that names nobody (a shipped example) or an approval that arrived in an
update is refused. The audit event ``approve.study_package_exported`` (who: ``host:<account>``, the sudo user only
as a claim; the study, version, approval tag, package id, the package's sha256 taken from the descriptor that is
linked, key id, the date; never content) is written BEFORE the package takes its name; an event that cannot be
written, and no package is left (D-1372, H4). The package is written in a destination folder opened without
following a link, owned by the running account and writable by nobody else, and linked from its descriptor.

``verify`` takes a trust file (``read_trust_file``: no link, nobody else may write it; ``load_trust``): each key
with the studies it may sign for and its purpose; a key trusted for updates is refused, and a key signs only the
studies its entry names (H5).
Exit status: 0 done; 1 refused (one sentence on stderr); 2 usage.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pwd
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from tb_common import study_manifest as sm
from tb_common import study_package as sp
from tb_common.crypto import ed25519_generate, ed25519_public_of
from tb_common.preflight import lang_of
from tb_common.ruleset import SEEDED_TAG

PRIVATE = "cc_ed25519.key"
PUBLIC = "cc_ed25519.pub"
#: the audit event of a written package: in the approval family the criteria compiler's database role writes
#: (``tb_common.audit_writer.ROLE_EVENTS``), as 10D-28's ``approve.part_exported``: it packs an approval tag
EVENT = "approve.study_package_exported"
#: the one supported way to run ``write`` (D-1372): the criteria compiler's container, as its service account, with
#: the key folder and an output folder (both owned by uid 10001) mounted for that one run; the study comes from the
#: ``rulesets-data`` volume at ``/data/rulesets``, the event goes to the audit journal (``TB_AUDIT_WRITER=db``)
SUPPORTED_RUN = (
    "docker compose run --rm -v <key folder>:/run/tb-study-key:ro -v <output folder>:/data/study-out "
    "criteria-compiler python -m tools.study_package write /data/rulesets/<ID> --key "
    "/run/tb-study-key/cc_ed25519.key --out /data/study-out/<ID>-<version>.tbstudy"
)
#: the operator's sentences, in the box's three languages (``--lang``, else ``TB_LANG``)
TEXTS: dict[str, dict[str, str]] = {
    "root": {
        "en": "a study package is never written as root; run it as the criteria compiler's service account, from the "
        "folder deploy/: {run}",
        "ja": "研究パッケージは root では書き出しません。deploy/ フォルダーから、"
        "基準コンパイラーのサービスアカウントで実行してください: {run}",
        "zh-TW": "研究套件不會以 root 寫出；請在 deploy/ 資料夾中，以條件編譯器的服務帳號執行：{run}",
    },
    "h1_limit": {
        "en": "The check of the test patients shows they were pseudonymised as the synthetic hospital's, not that what "
        "they say is synthetic; the person who packs the study answers for that.",
        "ja": "テスト患者の確認でわかるのは、合成病院の仮名で作られたことだけで、内容が合成であることは証明できません。"
        "それはパッケージを作る人が責任を持ちます。",
        "zh-TW": "測試病人的檢查只能看出它們是以合成醫院的假名產生，無法證明內容是合成的；這由打包研究的人負責。",
    },
}


def text(key: str, lang: str | None = None, **values: str) -> str:
    return TEXTS[key][lang_of(lang if lang is not None else os.environ.get("TB_LANG"))].format(**values)


class RootRefused(ValueError):
    """``write`` run as root (review of ec90c1b4, item 1)."""


#: a private key file is a few hundred bytes; a larger file is refused before it is read
KEY_FILE_MAX_BYTES = 1 << 16


def _private_key(path: Path, trusted: list[sp.TrustedKey] | None = None) -> bytes:
    """The private key (PEM) at ``path``, opened once without following a link and read from that descriptor: a
    regular file, owned by the running account, no group or other bit. With ``trusted`` (a trust file), a key whose
    public half is trusted there for updates is refused: the writer cannot otherwise tell an update key (10D-4 keeps
    the two apart). Raises ``ValueError`` with one sentence."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        if os.path.islink(path):
            raise ValueError(f"the key file {path} is a symbolic link; give the file itself") from None
        raise ValueError(f"the key file {path} cannot be opened ({exc.strerror})") from None
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"the key file {path} is not a regular file")
        if st.st_uid != os.geteuid():
            raise ValueError(
                f"the key file {path} is owned by another account (uid {st.st_uid}); it must be this one's"
            )
        if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError(
                f"the key file {path} may be read by others (mode {stat.S_IMODE(st.st_mode):o}); make it 600 first"
            )
        data = fh.read(KEY_FILE_MAX_BYTES + 1)
    if len(data) > KEY_FILE_MAX_BYTES:
        raise ValueError(f"the key file {path} is over {KEY_FILE_MAX_BYTES:,} bytes; it is not a key")
    if trusted:
        try:
            mine = sp.key_id(ed25519_public_of(data))
        except (TypeError, ValueError):
            mine = None
        updates = {sp.key_id(t.public_pem) for t in trusted if t.purpose != sp.STUDY_PURPOSE}
        if mine is not None and mine in updates:
            raise ValueError(
                f"the key {mine} is trusted for updates in the trust file; a study package is signed with its own key"
            )
    return data


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


def actor() -> tuple[str, str | None]:
    """Who runs the command: ``host:<account>`` from the account database by the real uid (not ``LOGNAME`` or
    ``USER``, which the caller sets), ``host:uid:<n>`` when the uid has no name; and ``SUDO_USER``, when set, as a
    claim (``sudo_user_claimed``): whoever starts the process can set it."""
    uid = os.getuid()
    try:
        who = f"host:{pwd.getpwuid(uid).pw_name}"
    except KeyError:
        who = f"host:uid:{uid}"
    return who, (os.environ.get("SUDO_USER") or None)


def approved_files(study: Path, files: dict[str, bytes]) -> tuple[dict[str, bytes], str]:
    """The files of ``study`` as its approval tag holds them, and the tag's name (item 4 of the review of ec90c1b4).

    The folder is ``<store>/<ID>`` of the box's rule-set store (``TB_RULESETS_DIR``, a git repository whose approval
    is an annotated tag ``<ID>/v<version>`` that says who approved it). The tag's blobs are read once. Refused
    (``ValueError``, one sentence): no store behind the folder, a folder named otherwise than its manifest's id, no
    tag for the manifest's version, a tag that names nobody (a shipped example), an approval that arrived in an
    update, a tagged manifest that is not the approved version, or a folder whose files differ from the tag's (a file
    edited after approval)."""
    from dulwich.object_store import iter_tree_contents
    from dulwich.objects import Commit, Tag
    from dulwich.repo import Repo

    store = study.absolute().parent
    if not (store / ".git").is_dir():
        raise ValueError(
            f"the study folder is not in the box's rule-set store ({store} is not a git repository with approval "
            "tags): only a study approved on this box is packed"
        )
    try:
        manifest = yaml.safe_load(files.get(sm.MANIFEST, b"").decode("utf-8")) or {}
    except (ValueError, yaml.YAMLError):
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    sid, version = manifest.get("id"), manifest.get("version")
    if manifest.get("status") != "approved":
        raise ValueError(
            "the study's manifest does not say status: approved; only an approved protocol is packed (a draft is "
            "not: decision 51 is open)"
        )
    if not isinstance(sid, str) or study.absolute().name != sid or not isinstance(version, str):
        raise ValueError("the study folder is not named as its manifest's id, with a version, in the rule-set store")
    tag = f"{sid}/v{version}"
    repo = Repo(str(store))
    try:
        refs: Any = repo.refs
        ref = f"refs/tags/{tag}".encode()
        if ref not in refs:
            raise ValueError(f"{tag}: no approval tag in the rule-set store; only an approved version is packed")
        obj: Any = repo[refs[ref]]
        message = obj.message.decode("utf-8", "replace") if isinstance(obj, Tag) else ""
        if not message or SEEDED_TAG in message:
            raise ValueError(f"{tag}: its approval names nobody at this box (a shipped example); not packed")
        if "(offline update" in message:
            raise ValueError(f"{tag} arrived in an update (approved elsewhere); only this box's own approval is packed")
        while isinstance(obj, Tag):
            obj = repo[obj.object[1]]
        if not isinstance(obj, Commit):
            raise ValueError(f"{tag}: the approval tag does not name a commit")
        tagged: dict[str, bytes] = {}
        for entry in iter_tree_contents(repo.object_store, obj.tree):
            path = entry.path.decode("utf-8", "replace") if entry.path else ""
            if path.startswith(f"{sid}/") and entry.sha is not None:
                rel = path[len(sid) + 1 :]
                if rel == sm.MANIFEST or sp.carriable(rel):
                    tagged[rel] = repo[entry.sha].as_raw_string()
    finally:
        repo.close()
    try:
        at_tag = yaml.safe_load(tagged.get(sm.MANIFEST, b"").decode("utf-8")) or {}
    except (ValueError, yaml.YAMLError):
        at_tag = {}
    if not isinstance(at_tag, dict) or at_tag.get("status") != "approved" or at_tag.get("version") != version:
        raise ValueError(f"{tag}: the tagged manifest is not the approved v{version}")
    if tagged != files:
        raise ValueError(
            f"the study folder differs from its approval tag {tag} (a file edited, added or removed after approval); "
            "only the approved files are packed: approve the change first"
        )
    return tagged, tag


def _destination(folder: Path) -> int:
    """The destination folder as a descriptor: opened without following a link, owned by the running account and
    writable by nobody else (no group or other write bit). Raises ``ValueError`` with one sentence."""
    try:
        dfd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:
        if os.path.islink(folder):
            raise ValueError(f"the destination folder {folder} is a symbolic link; give the folder itself") from None
        raise ValueError(f"the destination folder {folder} cannot be opened ({exc.strerror})") from None
    st = os.fstat(dfd)
    if st.st_uid != os.geteuid() or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        os.close(dfd)
        raise ValueError(
            f"the destination folder {folder} is not this account's alone (owner uid {st.st_uid}, mode "
            f"{stat.S_IMODE(st.st_mode):o}); write the package into a folder only this account may change"
        )
    return dfd


def _sha_of_fd(fd: int) -> str:
    h = hashlib.sha256()
    offset = 0
    while chunk := os.pread(fd, 1 << 20, offset):
        h.update(chunk)
        offset += len(chunk)
    return h.hexdigest()


def _link_from_fd(fd: int, part: str, name: str, dfd: int, *, force: bool) -> None:
    """Give the file open at ``fd`` the name ``name`` in ``dfd``: linked from the descriptor (``/proc/self/fd``),
    never over a file without ``force``; with ``force`` linked to a second hidden name and renamed over ``name``.
    Without ``/proc`` the hidden name ``part`` is linked; the caller checks the result's identity either way."""
    proc = f"/proc/self/fd/{fd}"
    src: tuple[str, int | None] = (proc, None) if os.path.exists(proc) else (part, dfd)
    if not force:
        os.link(src[0], name, src_dir_fd=src[1], dst_dir_fd=dfd, follow_symlinks=src[1] is None)
        return
    final = f"{part}.final"
    os.link(src[0], final, src_dir_fd=src[1], dst_dir_fd=dfd, follow_symlinks=src[1] is None)
    try:
        os.replace(final, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(final, dir_fd=dfd)


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
    audit: Any,
    force: bool = False,
    by: str | None = None,
    trusted: list[sp.TrustedKey] | None = None,
    euid: Any = None,
) -> dict[str, Any]:
    """Write the package of ``study`` to ``out`` and return its header, sha256 and approval tag; the event first (H4).

    ``audit`` is the product's writer (``open_audit``). Refused (``ValueError``, one sentence, nothing left at
    ``out`` or beside it): run as root (:class:`RootRefused`; ``euid`` is ``os.geteuid`` unless a test gives one), no
    writer, an ``out`` that exists without ``force``, a destination folder not this account's alone, a study not at
    its approval tag (:func:`approved_files`), a study the writer refuses, or an event that cannot be written. The
    package is written under a hidden name (``O_EXCL | O_NOFOLLOW``, mode 600) in the destination's descriptor; its
    sha256 is read back from that descriptor for the event; the name is linked from the same descriptor (never over a
    file without ``force``), and the named file is checked to be that descriptor's and hashed again from it before
    success is said. When the event is written and the name cannot be taken, or the name holds another file, the
    sentence says so and the name is removed: that event then names a package that does not exist."""
    if (euid or os.geteuid)() == 0:
        raise RootRefused(text("root", run=SUPPORTED_RUN))
    if audit is None:
        raise ValueError("no audit writer; a study package is written only with its audit event")
    try:
        there = os.lstat(out)
    except FileNotFoundError:
        there = None
    if there is not None and not force:
        raise ValueError(f"{out} exists; give --force to replace it")
    if there is not None and not stat.S_ISREG(there.st_mode):
        raise ValueError(f"{out} is not a regular file (a link, a folder or a device); --force replaces only a package")
    files, tag = approved_files(study, sp.read_folder(study))
    data = sp.build(files, _private_key(key, trusted), created)
    header = sp.header_of(data)
    who, sudo_claim = actor()
    part = f".{out.name}.{os.getpid()}.part"
    dfd = _destination(out.parent)
    fd = -1
    try:
        fd = os.open(part, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600,
                     dir_fd=dfd)  # fmt: skip
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
        sha = _sha_of_fd(fd)
        if sha != hashlib.sha256(data).hexdigest():
            raise ValueError("the package read back from its file is not the package written; no package was written")
        detail: dict[str, Any] = {
            "package_id": header["package_id"],
            "key_id": header["key_id"],
            "created": header["created"],
            "protocol_version": header["protocol_version"],
            "criteria_sha256": header["criteria_sha256"],
            "approval_tag": tag,
        }
        if sudo_claim:
            detail["sudo_user_claimed"] = sudo_claim
        try:
            audit.append(EVENT, actor=by or who, ruleset=header["study_id"], ruleset_version=header["version"],
                         output_sha=sha, detail=detail)  # fmt: skip
        except Exception as exc:
            raise ValueError(
                f"the audit event could not be written ({type(exc).__name__}); no package was written"
            ) from None
        written = f"the audit event {EVENT} was written for package {header['package_id']} (sha256 {sha}), but"
        try:
            _link_from_fd(fd, part, out.name, dfd, force=force)
            os.fsync(dfd)
        except OSError as exc:
            why = "it exists now; give --force to replace it" if isinstance(exc, FileExistsError) else exc.strerror
            raise ValueError(
                f"{written} the package could not take the name {out} ({why}): no package was left, so that event "
                "names a package that does not exist; run the command again (it writes a new event)"
            ) from None
        mine = os.fstat(fd)
        try:
            named = os.stat(out.name, dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            named = None
        if named is None or (named.st_dev, named.st_ino) != (mine.st_dev, mine.st_ino) or _sha_of_fd(fd) != sha:
            if named is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(out.name, dir_fd=dfd)
            raise ValueError(
                f"{written} the file named {out} is not that package (it was changed or replaced meanwhile); the name "
                "was removed, so that event names a package that does not exist; run the command again"
            )
    finally:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(part, dir_fd=dfd)
        os.close(dfd)
    return {**header, "sha256": sha, "approval_tag": tag}


def _file_audit_dir(directory: Path) -> None:
    """The file writer's folder (no journal): a folder, not a link, owned by the running account, so nothing another
    account planted there is followed with this account's rights. Raises ``ValueError`` with one sentence."""
    try:
        st = os.lstat(directory)
    except FileNotFoundError:
        raise ValueError(f"the audit directory {directory} is not a folder; no package was written") from None
    if not stat.S_ISDIR(st.st_mode):
        raise ValueError(f"the audit directory {directory} is not a folder (a link or a file); no package was written")
    if st.st_uid != os.geteuid() or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError(
            f"the audit directory {directory} is not this account's alone (owner uid {st.st_uid}); the file writer "
            "writes only into its own folder"
        )


def open_writer(audit_dir: Path | None) -> Any:
    """The product's audit writer (``tb_common.audit_writer.open_audit``, as 10D-28's export): the journal when
    ``TB_AUDIT_WRITER=db`` (the criteria compiler's container); otherwise the chain in ``--audit-dir`` or
    ``TB_AUDIT_DIR``, a folder of the running account's (:func:`_file_audit_dir`)."""
    from tb_common.audit_writer import MODE_ENV, open_audit

    tz = os.environ.get("TB_TZ") or None
    if (os.environ.get(MODE_ENV) or "file").strip().lower() == "db":
        return open_audit(audit_dir, tz)
    env_dir = os.environ.get("TB_AUDIT_DIR")
    directory = audit_dir or (Path(env_dir) if env_dir else None)
    if directory is None:
        raise ValueError(
            "no audit directory: give --audit-dir or set TB_AUDIT_DIR (or TB_AUDIT_WRITER=db); a study package is "
            "written only with its audit event"
        )
    _file_audit_dir(directory)
    return open_audit(directory, tz)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen", help="a coordinating-centre key pair")
    k.add_argument("--out", type=Path, required=True)
    w = sub.add_parser("write", help="the package of a study at its approval tag in the rule-set store, audited")
    w.add_argument("study", type=Path, help="the study's folder in the rule-set store, /data/rulesets/<ID>")
    w.add_argument("--key", type=Path, required=True, help="the coordinating centre's Ed25519 private key (PEM)")
    w.add_argument("--out", type=Path, required=True)
    w.add_argument("--created", help="the package's date, YYYY-MM-DD (default: today, UTC)")
    w.add_argument("--force", action="store_true", help="replace --out when it exists")
    w.add_argument("--audit-dir", type=Path, help="without the journal: the audit folder (default: TB_AUDIT_DIR)")
    w.add_argument("--trust-file", type=Path, help="a trust file: a key it trusts for updates is refused")
    w.add_argument("--lang", help="en, ja or zh-TW (default: TB_LANG)")
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
            if os.geteuid() == 0:  # before any file or the journal is touched
                raise RootRefused(text("root", args.lang, run=SUPPORTED_RUN))
            trusted = read_trust_file(args.trust_file) if args.trust_file else None
            h = write(
                args.study,
                args.key,
                args.out,
                args.created or datetime.now(UTC).date().isoformat(),
                audit=open_writer(args.audit_dir),
                force=args.force,
                trusted=trusted,
            )
            print(
                f"wrote {args.out}: study {h['study_id']} version {h['version']} (protocol {h['protocol_version']}) "
                f"at its approval tag {h['approval_tag']}, package {h['package_id']}, criteria hash "
                f"{h['criteria_sha256']}, signed by key {h['key_id']}, audited as {EVENT}"
            )
            print(text("h1_limit", args.lang))
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
