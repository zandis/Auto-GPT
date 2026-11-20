"""The coordinating centre's study package tool (10D-3, D-1372): write, verify and show a study package v1.

    python -m tools.study_package keygen --out keys/                 # cc_ed25519.key (mode 600, offline) + .pub
    python -m tools.study_package write /data/rulesets/RA-JAK --key /run/tb-study-key/cc_ed25519.key \\
        --out /data/study-out/RA-JAK-1.0.0.tbstudy [--created 2026-11-19] [--force] [--trust-file FILE]
    python -m tools.study_package verify RA-JAK-1.0.0.tbstudy --trust-file study-trust.json
    python -m tools.study_package show RA-JAK-1.0.0.tbstudy         # the header, NOT verified (exit status 3)

A command for the coordinating centre's operator: no console page or action calls it, and nothing on the live path
reads a package yet (import and the register of coordinating-centre keys are 10D-4's). The package carries the
study's protocol part and protocol files only (``tb_common.study_manifest``, D-1366): no scopes, routing, review or
IRB record, and no patient data. It never prints key material: a key is named by its key id.

``write`` never runs as root (:data:`SUPPORTED_RUN`): it runs in the criteria compiler's container as its service
account (uid 10001), as 10D-28's ``criteria_compiler.export_part`` does, and audits through the product's writer
(``tb_common.audit_writer.open_audit``: the journal with ``TB_AUDIT_WRITER=db``, as in that container; else the chain
in ``TB_AUDIT_DIR``, a folder the running account owns). It packs the bytes of the study's approval tag
``<ID>/v<version>`` in the box's rule-set store, which is fixed (:data:`RULESETS_STORE`, ``/data/rulesets``, the
declared default of ``TB_RULESETS_DIR``): no option names another, an environment that names another is refused, and
a store path that is or passes through a link is refused; the study folder's parent must be that folder. The tag
must be exactly as the criteria compiler writes an approval (the tag object named as its ref, message ``<ID>
v<version> approved by <who>``, tagger and the tagged manifest's ``review.approved_by`` that person): another store,
a folder whose files differ from that tag, a version with no tag, a tag that names nobody (a shipped example), an
approval that arrived in an update or any other tag is refused. That proves the box's store holds such a tag, not
that the person acted: the store's owner (uid 10001), root, and any account its folders let write can write one,
and whoever holds the signing key can call the library's ``build`` without an audit, so it is as strong as those
accounts and that key (D-1372). The audit event ``approve.study_package_exported`` (who: ``host:<account>``, the
sudo user only as a claim; the study, version, approval tag, its tag object and commit sha and the approver its
message names, the store's path, device, inode and owner uid, package id, the package's sha256 taken from the
descriptor that is linked, key id, the date; never content) is written BEFORE the package takes its name (part files
of an interrupted earlier run in the destination that no writer holds locked are removed first, and named); an event
that cannot be written, and no package is left (D-1372, H4). The package is written in a destination folder opened
without following a link, owned by the running account and writable by nobody else, and linked from its descriptor.

``verify`` takes a trust file (``read_trust_file``: read as a package file is, no link, nobody else may write it;
``load_trust``): each key
with the studies it may sign for and its purpose; a key trusted for updates is refused, and a key signs only the
studies its entry names (H5).
``show`` prints the header with its signature NOT checked: that line first, on stdout and on stderr, then the header
with every character outside printable ASCII escaped, and exits 3 ("shown, not verified"). No sentence of this command
echoes text a package's sender chose before its signature is checked; what it prints after is escaped the same way.
Every message the command prints is escaped to printable ASCII at its one exit point. Exit status: 0 done; 1
refused (one sentence on stderr); 2 usage, or an internal error (one sentence, no traceback; ``verify``'s refusal of
step ``internal`` too); 3 shown, not verified (``show``).
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import pwd
import re
import stat
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from tb_common import study_manifest as sm
from tb_common import study_package as sp
from tb_common.config import DECLARED
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
#: the operator's sentences, in the box's three languages (``--lang``, else the shell's ``LANG``)
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
    return TEXTS[key][lang_of(lang if lang is not None else os.environ.get("LANG"))].format(**values)


#: ``show``'s exit status: the header was shown and NOT verified (review of 02b55d8a, item 2), so a script that tests
#: for 0 cannot take a shown package for a verified one
SHOWN = 3
SHOWN_NOT_VERIFIED = "the signature is NOT checked: this header is shown, not verified (use verify; exit status 3)"


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


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
_NEW_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def keygen(out: Path) -> tuple[Path, Path, str]:
    """A coordinating-centre key pair: the private key (PEM, PKCS8, mode 600) and its public key (PEM, mode 644),
    and its key id. Both are created in the folder's descriptor (opened without following a link) with ``O_CREAT |
    O_EXCL | O_NOFOLLOW``, so an existing name, a link among them, is refused and nothing is written through it
    (review of 02b55d8a, item 8: ``keygen`` may run as root). Raises ``ValueError`` with one sentence."""
    out.mkdir(parents=True, exist_ok=True)
    try:
        dfd = os.open(out, _DIR_FLAGS)
    except OSError as exc:
        raise ValueError(f"the key folder {out} cannot be opened without following a link ({exc.strerror})") from None
    made: list[str] = []
    try:
        for name in (PRIVATE, PUBLIC):
            with contextlib.suppress(FileNotFoundError):
                os.stat(name, dir_fd=dfd, follow_symlinks=False)
                raise ValueError(f"{out / name} exists (a file or a link); a key is never replaced")
        private_pem, public_pem = ed25519_generate()
        for name, data, mode in ((PRIVATE, private_pem, 0o600), (PUBLIC, public_pem, 0o644)):
            try:
                fd = os.open(name, _NEW_FILE_FLAGS, mode, dir_fd=dfd)
            except FileExistsError:
                raise ValueError(f"{out / name} exists (a file or a link); a key is never replaced") from None
            made.append(name)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        made.clear()
    finally:
        for name in made:  # a pair is written whole or not at all
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=dfd)
        os.close(dfd)
    return out / PRIVATE, out / PUBLIC, sp.key_id(public_pem)


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


#: the box's rule-set store, fixed (review of b9937b0d, item 1): the declared default of ``TB_RULESETS_DIR``
#: (``tb_common.config``), the ``rulesets-data`` volume the criteria compiler's container mounts there. ``write``
#: never takes another from the caller: no option names one, and an environment that names another is refused
RULESETS_STORE = Path(DECLARED["TB_RULESETS_DIR"].default)


def rulesets_store() -> Path:
    """The store ``write`` packs from: :data:`RULESETS_STORE`, whatever the caller's environment says. A
    ``TB_RULESETS_DIR`` that names another folder is refused (``ValueError``, one sentence), not followed: the store
    is the box's, not the caller's."""
    named = os.environ.get("TB_RULESETS_DIR")
    if named and Path(named) != RULESETS_STORE:
        raise ValueError(
            f"TB_RULESETS_DIR names {named}; a study package is packed only from the box's rule-set store "
            f"{RULESETS_STORE} (the criteria compiler's), never from a folder the caller names: unset it"
        )
    return RULESETS_STORE


def _store_identity(store: Path) -> os.stat_result:
    """The store folder's ``stat``, reached from ``/`` one component at a time, each opened ``O_DIRECTORY |
    O_NOFOLLOW`` from its parent's descriptor, so a store path that is, or passes through, a symbolic link is refused
    (its real path is then the path itself); it must be an absolute path and a git repository (``.git`` a folder, not
    a link). Raises ``ValueError`` with one sentence."""
    if not store.is_absolute() or any(part in (".", "..") for part in store.parts):
        raise ValueError(f"the rule-set store {store} is not an absolute path without '.' or '..'")
    fd = os.open("/", _DIR_FLAGS)
    try:
        for part in store.parts[1:]:
            try:
                nxt = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except OSError as exc:
                raise ValueError(
                    f"the rule-set store {store} cannot be opened without following a link at {part} ({exc.strerror});"
                    " a store that is or passes through a symbolic link is not used"
                ) from None
            os.close(fd)
            fd = nxt
        st = os.fstat(fd)
        try:
            git = os.stat(".git", dir_fd=fd, follow_symlinks=False)
        except OSError:
            git = None
    finally:
        os.close(fd)
    if git is None or not stat.S_ISDIR(git.st_mode):
        raise ValueError(f"the rule-set store {store} is not a git repository (its .git is not a folder)")
    return st


@dataclass(frozen=True)
class Approval:
    """The approval a package was packed from: the tag's name, the tag object's sha, the commit it names and the
    approver its message names (what the audit event and the success line record, review of 02b55d8a, item 7), and
    the store that holds it: its real path, ``(st_dev, st_ino)`` and owner uid (review of b9937b0d, item 1)."""

    tag: str
    tag_sha: str
    commit: str
    by: str
    store: str
    store_dev: int
    store_ino: int
    store_uid: int


def _approver(message: str, sid: str, version: str) -> str | None:
    """The approver of an approval tag's message when it is exactly what the criteria compiler writes on approval
    (``criteria_compiler.service``: ``repo.tag(tag, branch, f"{ruleset} v{version} approved by {by}", by)``), else
    None: one line, printable, nothing before or after."""
    prefix = f"{sid} v{version} approved by "
    if not message.startswith(prefix):
        return None
    by = message[len(prefix) :]
    if not by or by != by.strip() or not by.isprintable() or SEEDED_TAG in by or "(offline update" in by:
        return None
    return by


def approved_files(
    study: Path, files: dict[str, bytes], store: Path | None = None
) -> tuple[dict[str, bytes], Approval]:
    """The files of ``study`` as its approval tag holds them, and that approval (item 4 of the review of ec90c1b4;
    item 7 of the review of 02b55d8a).

    The folder must be ``<store>/<ID>`` of the box's rule-set store (``store``, which only the tests give; else
    :func:`rulesets_store`, the fixed :data:`RULESETS_STORE`): its parent is that folder (the same device and inode),
    which is the criteria compiler's git repository, reached without following a link (:func:`_store_identity`); a
    store found above an arbitrary path is not. The approval must be the one the compiler writes:
    an annotated tag ``<ID>/v<version>`` naming a commit, the tag object's own name that same ``<ID>/v<version>``,
    its message exactly ``<ID> v<version> approved by <who>``,
    its tagger ``<who> <<who>>``, and the manifest at the tag ``status: approved``, that version, and
    ``review.approved_by`` that same person. The tag's blobs are read once. Refused (``ValueError``, one sentence):
    another store, a folder named otherwise than its manifest's id, no tag for the manifest's version, a bare tag or
    one that names nobody (a shipped example), an approval that arrived in an update, a message, tagger or tagged
    manifest that is not the compiler's approval, or a folder whose files differ from the tag's (a file edited after
    approval).

    What it cannot prove: the store's owner (the service account, uid 10001), root, and any account the store's
    folders let write can write such a tag without the approver's act on the console; so "approved on this box" is
    as strong as those accounts (D-1372)."""
    from dulwich.object_store import iter_tree_contents
    from dulwich.objects import Commit, Tag
    from dulwich.repo import Repo

    store = rulesets_store() if store is None else store
    here = _store_identity(store)
    try:
        there = os.stat(study.absolute().parent)
        same = (here.st_dev, here.st_ino) == (there.st_dev, there.st_ino)
    except OSError:
        same = False
    if not same:
        raise ValueError(
            f"the study folder is not in the box's rule-set store {store}: only a study approved on this box is packed"
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
        by = _approver(message, sid, version)
        if by is None:
            raise ValueError(
                f"{tag}: its message is not the criteria compiler's approval (exactly \"{sid} v{version} approved by "
                '<who>"); not packed'
            )
        if obj.tagger != f"{by} <{by}>".encode():
            raise ValueError(f"{tag}: its tagger is not the approver its message names; not packed")
        if obj.name != tag.encode():
            raise ValueError(f"{tag}: its tag object is named otherwise than its ref; not packed")
        tag_sha = obj.id.decode("ascii")
        commit: Any = repo[obj.object[1]] if obj.object[0] is Commit and obj.object[1] in repo else None
        if not isinstance(commit, Commit):
            raise ValueError(f"{tag}: the approval tag does not name a commit")
        tagged: dict[str, bytes] = {}
        for entry in iter_tree_contents(repo.object_store, commit.tree):
            path = entry.path.decode("utf-8", "replace") if entry.path else ""
            if path.startswith(f"{sid}/") and entry.sha is not None:
                rel = path[len(sid) + 1 :]
                if rel == sm.MANIFEST or sp.carriable(rel):
                    tagged[rel] = repo[entry.sha].as_raw_string()
        commit_sha = commit.id.decode("ascii")
    finally:
        repo.close()
    try:
        at_tag = yaml.safe_load(tagged.get(sm.MANIFEST, b"").decode("utf-8")) or {}
    except (ValueError, yaml.YAMLError):
        at_tag = {}
    if not isinstance(at_tag, dict) or at_tag.get("status") != "approved" or at_tag.get("version") != version:
        raise ValueError(f"{tag}: the tagged manifest is not the approved v{version}")
    review = at_tag.get("review")
    if not isinstance(review, dict) or review.get("approved_by") != by:
        raise ValueError(f"{tag}: the tagged manifest's review.approved_by is not the approver the tag names")
    if tagged != files:
        raise ValueError(
            f"the study folder differs from its approval tag {tag} (a file edited, added or removed after approval); "
            "only the approved files are packed: approve the change first"
        )
    return tagged, Approval(tag, tag_sha, commit_sha, by, str(store), here.st_dev, here.st_ino, here.st_uid)


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


#: the hidden name ``write`` gives a package before its name (``.<name>.<pid>.part``, and ``.final`` with ``--force``)
_PART_NAME = re.compile(r"\.[A-Za-z0-9._-]{1,200}\.(?P<pid>[0-9]{1,10})\.part(?:\.final)?")


def remove_stale_parts(dfd: int) -> list[str]:
    """Remove from the destination's descriptor the hidden part files an earlier run of this command left (a SIGKILL
    between its audit event and its link, review of 02b55d8a item 9) and return their names: only names of this
    command's own pattern (:data:`_PART_NAME`), only regular files (not followed: ``lstat``, and the descriptor
    opened ``O_NOFOLLOW`` is that file) owned by the running account, and only when this process can take
    ``flock(LOCK_EX | LOCK_NB)`` on it: a writer holds that lock on its part file from creation to the link (review of
    b9937b0d, item 3), whatever PID namespace it runs in, so a file nobody holds is one nobody writes. The pid in the
    name decides nothing. The caller holds the folder's own lock (:func:`write`), so no writer is between creating
    its part file and locking it."""
    gone: list[str] = []
    for name in sorted(os.listdir(dfd)):
        if _PART_NAME.fullmatch(name) is None:
            continue
        try:
            st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid():
            continue
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0), dir_fd=dfd)
        except OSError:
            continue
        try:
            mine = os.fstat(fd)
            if (mine.st_dev, mine.st_ino) != (st.st_dev, st.st_ino):
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue  # a writer holds it: a run still going, in this PID namespace or another
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=dfd)
                gone.append(name)
        finally:
            os.close(fd)
    return gone


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
    account or root), at most :data:`TRUST_FILE_MAX_BYTES`: ``study_package.read_capped``, the package file's reader,
    with those owner checks on its descriptor (review of b9937b0d, item 4). Raises ``ValueError`` with one
    sentence."""

    def owned(st: os.stat_result) -> None:
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError(
                f"the trust file {path} is a file others may write (mode {stat.S_IMODE(st.st_mode):o}); make it 644"
            )
        if st.st_uid not in (0, os.geteuid()):
            raise ValueError(f"the trust file {path} is owned by another account (uid {st.st_uid})")

    return sp.load_trust(sp.read_capped(path, TRUST_FILE_MAX_BYTES, "the trust file", check=owned))


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
    store: Path | None = None,
) -> dict[str, Any]:
    """Write the package of ``study`` to ``out`` and return its header, sha256, approval (:class:`Approval`) and the
    stale part files it removed (:func:`remove_stale_parts`); the event first (H4). ``store``: the rule-set store;
    only the tests give one (the command never does: :func:`rulesets_store`, the fixed :data:`RULESETS_STORE`).

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
    files, approval = approved_files(study, sp.read_folder(study), store)
    data = sp.build(files, _private_key(key, trusted), created)
    header = sp.header_of(data)
    who, sudo_claim = actor()
    part = f".{out.name}.{os.getpid()}.part"
    dfd = _destination(out.parent)
    fd = -1
    try:
        # the folder's lock while stale part files are swept and this run's is made and locked, so no sweep falls
        # between a writer's create and its lock; the part file's lock is held until it is closed, after the link
        fcntl.flock(dfd, fcntl.LOCK_EX)
        try:
            removed = remove_stale_parts(dfd)
            fd = os.open(part, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                         0o600, dir_fd=dfd)  # fmt: skip
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            fcntl.flock(dfd, fcntl.LOCK_UN)
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
            "approval_tag": approval.tag,
            "approval_tag_sha": approval.tag_sha,
            "approval_commit": approval.commit,
            "approved_by": approval.by,
            "store": approval.store,
            "store_dev": approval.store_dev,
            "store_ino": approval.store_ino,
            "store_uid": approval.store_uid,
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
    return {**header, "sha256": sha, "approval": approval, "removed_parts": removed}


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
    w.add_argument("--lang", help="en, ja or zh-TW (default: the shell's LANG)")
    v = sub.add_parser("verify", help="check a package against a trust file")
    v.add_argument("package", type=Path)
    v.add_argument(
        "--trust-file", type=Path, required=True, help="the trusted keys, each with its studies (tb-study-trust/1)"
    )
    s = sub.add_parser("show", help="print a package's header, NOT verified (exit status 3)")
    s.add_argument("package", type=Path)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "keygen":
            priv, pub, kid = keygen(args.out)
            print(sp.printable(f"wrote {priv} (mode 600; mounted only for a write, kept offline otherwise) and {pub} "
                               f"(key id {kid})"))  # fmt: skip
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
            if h["removed_parts"]:
                print(sp.printable(f"study package: removed {len(h['removed_parts'])} part file(s) an interrupted "
                                   f"earlier run left: {', '.join(h['removed_parts'])}"), file=sys.stderr)  # fmt: skip
            a = h["approval"]
            print(
                sp.printable(
                    f"wrote {args.out}: study {h['study_id']} version {h['version']} (protocol "
                    f"{h['protocol_version']}), package {h['package_id']}, criteria hash {h['criteria_sha256']}, "
                    f"signed by key {h['key_id']}, audited as {EVENT}; packed from the approval tag {a.tag} (tag "
                    f"object {a.tag_sha}, commit {a.commit}) in the rule-set store {a.store} (device {a.store_dev}, "
                    f"inode {a.store_ino}, owner uid {a.store_uid}), whose message says approved by {a.by}: that "
                    "proves such a tag is in the box's store, which its owner, root, or any account its folders "
                    "let write can write without the person's act, and whoever holds the signing key can build a "
                    "package with the library without an audit; so this is as strong as those accounts and that key"
                )
            )
            print(text("h1_limit", args.lang))
        elif args.cmd == "verify":
            got = sp.verify_file(args.package, read_trust_file(args.trust_file))
            h = got.header
            print(
                sp.printable(
                    f"verified {args.package}: study {h['study_id']} version {h['version']}, package "
                    f"{h['package_id']}, {len(got.files)} protocol files, criteria hash {h['criteria_sha256']}, "
                    f"signed by key {h['key_id']}"
                )
            )
        else:
            header = sp.header_of(sp.read_file(args.package))
            print(SHOWN_NOT_VERIFIED, file=sys.stderr)
            print(SHOWN_NOT_VERIFIED)
            print(json.dumps(header, ensure_ascii=True, indent=1, sort_keys=True).replace("\x7f", "\\u007f"))
            return SHOWN
    except (ValueError, OSError) as exc:  # PackageRefused is a ValueError
        # the one exit point of every subcommand: every message escaped (review of b9937b0d, item 2), but the root
        # refusal, the command's own sentence in the operator's language with nothing of a file or a caller in it
        said = str(exc) if type(exc) is RootRefused else sp.printable(str(exc))
        print(f"study package: {said}", file=sys.stderr)
        # verify's boundary refuses the unforeseen as step "internal": an internal error, exit 2 (D-1372)
        return 2 if isinstance(exc, sp.PackageRefused) and exc.step == "internal" else 1
    except Exception:  # the last resort: one sentence, no traceback (review of 02b55d8a, item 3)
        what = "the package could not be read" if args.cmd in ("verify", "show") else "the command stopped"
        print(f"study package: {what} (internal)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
