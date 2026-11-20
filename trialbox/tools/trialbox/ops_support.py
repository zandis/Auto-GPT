"""10K-5 (D-1381): the support bundle as an operations action, the host's half.

The console's "Make a support bundle" button writes an ``support_bundle`` request into the operations folder like
every other operation (``tools/trialbox/ops.py``); the host's runner takes it and calls the SAME builder as
``trialbox support-bundle`` (:func:`tools.support_bundle.build`), with its scrubbers, the line scan and the last look
at the finished archive (D-405, D-723, D-747, D-962). Nothing is added to what the bundle holds: no ``--add`` file,
and the request's ``args`` are never read (the console's user writes the request file). Some members are left out
and some texts marked, each by a constant of this module that the console cannot pass or change, and the MANIFEST
says which and why: the service logs (:data:`LOGS_LEFT_OUT`, the review of 83a0640a: they can carry patient
pseudonyms, which the scrubber does not catch); ``env.redacted``, ``docker compose config``, ``doctor`` and
``check_host.sh`` (:data:`LEFT_OUT`, the review of 31935cc4: the redaction is by name, and doctor prints setting
values and texts read from the database); and the error and detail texts of the update history and the ops snapshot
become a mark with their length and the error's type name (:data:`TEXTS_MARKED`: an error text can quote a
patient-linked value).

The folder: ``<ops>`` is opened without following a link and must belong to the runner's user (root on the host) and
not be writable by group or others; ``support`` (0750, root and the console's group) and ``support/.making`` (0700,
root) are made and set through fds, and a link or a non-folder there is refused (:class:`SupportFolderRefused`).

A bundle that fails the scan raises :class:`tools.support_bundle.BundleRefused`; the builder has then written
nothing, and the result says ``BundleRefused: ...`` (pattern ids and member names, never a value), which the page
shows as "not handed out". A bundle that passes is made in ``.making``, hashed, and the audit event ``console.ops``
``support_bundle.made`` (the request, file name, size and sha256, never a line of the bundle) is written; only then is
the file moved to ``<ops>/support/`` (file 0640). The sha256 is taken from the made file's fd and compared with the
sha256 of the copy the builder's last look scanned (else :class:`BundleChanged`, nothing released), and the name
in ``<ops>/support/`` is checked to be that fd's file after the move. No event, no bundle: the file is removed and
the result says ``BundleNotAudited: ...``. Its file name, size and sha256 are the result's last three lines, and only
the newest :data:`KEEP` bundles stay.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

ACTION = "support_bundle"
SUBDIR = "support"
KEEP = 3  # the newest bundles kept in <ops>/support/; an older one is removed when a new one is made
NAME = re.compile(r"trialbox-support-\d{8}T\d{6}Z\.tar\.gz", re.ASCII)  # the builder's file name, matched whole
LINE_FILE, LINE_BYTES, LINE_SHA = "file ", "bytes ", "sha256 "
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)
MAKING = ".making"  # <ops>/support/.making: root alone; a bundle is made here and moved out only once audited
#: D-1381 (the review of 83a0640a): the reason a bundle made from the button holds no service log, in its MANIFEST
LOGS_LEFT_OUT = (
    "left out of a bundle made from the console's button (D-1381): TrialBox's service logs can carry patient "
    "pseudonyms, which the scrubber does not catch; they are in a bundle only when it is made on the host with "
    "`trialbox support-bundle`, as root"
)
#: D-1381 (the review of 31935cc4): the members a bundle made from the button never holds, each with its reason in the
#: MANIFEST; the commands named are not run. Until the builder's redaction catches a secret by its value wherever it
#: stands (lane H's cure), these come back only through the host tool.
_BY_NAME = ("the builder redacts a secret by the setting's name and the user:password of a URL, so a secret under a "
            "name it does not know, or in a URL's query, would go through")  # fmt: skip
LEFT_OUT: Mapping[str, str] = MappingProxyType({
    "env.redacted": f"left out of a bundle made from the console's button (D-1381): {_BY_NAME}",
    "cmd/compose-config.yaml": "left out of a bundle made from the console's button (D-1381): docker compose config "
    f"prints every service's resolved settings; {_BY_NAME}",
    "cmd/doctor.json": "left out of a bundle made from the console's button (D-1381): doctor prints setting values "
    "(the gateway's and the verifier's URLs among them) without that redaction, and texts it reads from the database "
    "(the reason given for the hold after a restore, which a person may type)",
    "cmd/check_host.txt": "left out of a bundle made from the console's button (D-1381): check_host.sh runs doctor and "
    "prints what doctor prints",
})  # fmt: skip
#: D-1381 (the review of 31935cc4): why the free text of the history and the ops snapshot is marked
TEXTS_MARKED = (
    "replaced by a mark with the text's length and the error's type name in a bundle made from the console's button "
    "(D-1381): an error text can quote a patient-linked value (a failed migration's database error quotes the key "
    "that clashed, a pseudonym among them)"
)


def support_dir(ops_root: Path) -> Path:
    return Path(ops_root) / SUBDIR


def sha256_of(fh: Any) -> tuple[str, int]:
    """The sha256 and the size of an open binary file, read from where it stands to its end."""
    h, n = hashlib.sha256(), 0
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
        n += len(chunk)
    return h.hexdigest(), n


def record(result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The bundle a finished ``support_bundle`` result names (file, bytes, sha256), from the last three lines the
    runner (root) wrote; None for any other result, a failed one, or lines that do not have that exact form."""
    if not result or result.get("action") != ACTION or result.get("ok") is not True:
        return None
    lines = [str(x) for x in result.get("lines") or []][-3:]
    if len(lines) != 3 or not (
        lines[0].startswith(LINE_FILE) and lines[1].startswith(LINE_BYTES) and lines[2].startswith(LINE_SHA)
    ):
        return None
    name, size, sha = lines[0][len(LINE_FILE) :], lines[1][len(LINE_BYTES) :], lines[2][len(LINE_SHA) :]
    if not NAME.fullmatch(name) or not size.isdigit() or not _SHA.fullmatch(sha):
        return None
    return {"file": name, "bytes": int(size), "sha256": sha}


class SupportFolderRefused(RuntimeError):
    """``<ops>`` or ``<ops>/support`` is not what the runner may write into (a link, not a folder, not owned by the
    runner's user, writable by group or others): nothing is made."""


class BundleChanged(RuntimeError):
    """The made file is not the copy the builder's last look scanned (another hash), or the released name is not the
    file that was hashed: removed, never released."""


class BundleNotAudited(RuntimeError):
    """The audit event of the making could not be written: the bundle is removed, never released."""


_DIR = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _euid() -> int:
    return os.geteuid() if hasattr(os, "geteuid") else -1


def _sub(parent: int, name: str, mode: int, where: str) -> int:
    """The folder ``name`` inside the open folder ``parent``, made when missing, opened without following a link and
    refused when it is a link or not a folder; an fd."""
    with contextlib.suppress(FileExistsError):
        os.mkdir(name, mode, dir_fd=parent)
    st = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise SupportFolderRefused(f"{where} is {'a link' if stat.S_ISLNK(st.st_mode) else 'not a folder'}: refused")
    try:
        fd = os.open(name, _DIR, dir_fd=parent)
    except OSError as exc:  # swapped for a link or a file between the look and the open
        raise SupportFolderRefused(f"{where} cannot be opened as a folder ({exc.strerror}): refused") from exc
    got = os.fstat(fd)
    if (got.st_dev, got.st_ino) != (st.st_dev, st.st_ino):
        os.close(fd)
        raise SupportFolderRefused(f"{where} changed while it was opened: refused")
    return fd


def _open_support(ops_root: Path, uid: int) -> tuple[int, int]:
    """``<ops>/support`` and its ``.making`` folder, as fds. ``<ops>`` is opened without following a link and must be
    owned by the runner's user (root on the host) and not writable by group or others, so nobody else can swap what is
    under it; ``support`` gets root and the console's group, 0750, ``.making`` root alone, 0700 (set on the fds)."""
    try:
        ofd = os.open(ops_root, _DIR)
    except OSError as exc:
        raise SupportFolderRefused(f"{ops_root} is not a folder that can be opened without a link "
                                   f"({exc.strerror}): refused") from exc  # fmt: skip
    sfd = mfd = -1
    try:
        st = os.fstat(ofd)
        if st.st_uid != _euid():
            who = f"uid {st.st_uid}, not by the runner (uid {_euid()})"
            raise SupportFolderRefused(f"{ops_root} is owned by {who}: refused")
        if st.st_mode & 0o022:
            mode = f"{stat.S_IMODE(st.st_mode):o}"
            raise SupportFolderRefused(f"{ops_root} may be written by group or others ({mode}): refused")
        sfd = _sub(ofd, SUBDIR, 0o750, f"{ops_root / SUBDIR}")
        if _euid() == 0:  # the host's runner: root owns it, the console's group reads
            os.fchown(sfd, 0, uid)
            os.fchmod(sfd, 0o750)
        mfd = _sub(sfd, MAKING, 0o700, f"{ops_root / SUBDIR / MAKING}")
        if _euid() == 0:
            os.fchown(mfd, 0, 0)
        os.fchmod(mfd, 0o700)
        for left in os.listdir(mfd):  # a making cut off before: never released, removed
            with contextlib.suppress(OSError):
                os.unlink(left, dir_fd=mfd)
        return sfd, mfd
    except BaseException:
        for fd in (sfd, mfd):
            if fd >= 0:
                os.close(fd)
        raise
    finally:
        os.close(ofd)


def _prune(d: Path, keep: int) -> list[str]:
    old = sorted(p.name for p in d.iterdir() if NAME.fullmatch(p.name) and p.is_file())[:-keep]
    for name in old:
        with contextlib.suppress(OSError):
            (d / name).unlink()
    return old


def _audit_made(runner: Any, rec: Mapping[str, Any], rid: str) -> None:
    """``console.ops`` with ``support_bundle.made``, the request, the file name, its size and its sha256, BEFORE the
    file gets its final name. On a site box it is written inside the orchestrator as
    :meth:`tools.trialbox.ops.OpsRunner.audit` writes the result's event, and a failure raises (the command's exit);
    on the in-process box through the console's own writer (``audit_local``, set by ``console/ops_pages.py``), else
    the box's writer (:func:`tb_common.audit_writer.open_audit`). Never best effort: no event, no bundle."""
    detail = {"action": f"{ACTION}.made", "request": rid, **rec}
    if runner.box.kind == "compose":
        from tools.trialbox.update import ComposeBox

        code = (
            "import json, sys\nfrom tb_common.audit_writer import open_audit\n"
            "open_audit().append('console.ops', actor='trialbox-ops', detail=json.loads(sys.argv[1]))\n"
        )
        argv = [*ComposeBox(runner.box.deploy).compose, "exec", "-T", "orchestrator", "python", "-c", code,
                json.dumps(detail)]  # fmt: skip
        runner.box.run(argv, 120)  # raises on a non-zero exit (tools.trialbox.ops.run_cmd)
        return
    local = getattr(runner, "audit_local", None)
    if local is not None:
        local(detail)
        return
    from tb_common.audit_writer import open_audit

    open_audit(env=runner.box.env).append("console.ops", actor="trialbox-ops", detail=detail)


def do_support_bundle(runner: Any, args: Mapping[str, str]) -> tuple[str, list[str]]:
    """``OpsRunner.do_support_bundle``: the bundle, made by :func:`tools.support_bundle.build` into
    ``<ops>/support/.making``, audited, then given its final name in ``<ops>/support``; ``args`` unread."""
    from tools import support_bundle
    from tools.trialbox.ops import SERVICE_UID

    out = support_dir(runner.ops.root)
    sfd, mfd = _open_support(runner.ops.root, SERVICE_UID)
    try:
        said: list[str] = []
        looked: list[tuple[str, int]] = []
        # a site box runs docker, df and nvidia-smi as the command does; the in-process box has no docker.
        # D-1381: no service log, whatever the days; no .env, compose config, doctor or check_host.sh; the history's
        # and the snapshot's texts marked. All constants of this module: the console passes nothing.
        made = support_bundle.build(runner.box.deploy, out / MAKING, commands=runner.box.kind == "compose",
                                    say=said.append, logs_left_out=LOGS_LEFT_OUT, left_out=LEFT_OUT,
                                    texts_marked=TEXTS_MARKED, scanned=lambda h, n: looked.append((h, n)))  # fmt: skip
        name = made.name
        if not NAME.fullmatch(name):
            raise SupportFolderRefused(f"the builder named its file {name[:80]!r}: not released")
        fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=mfd)
        with os.fdopen(fd, "rb") as fh:
            if _euid() == 0:
                os.fchown(fh.fileno(), 0, SERVICE_UID)
                os.fchmod(fh.fileno(), 0o640)
            sha, size = sha256_of(fh)
            hashed = os.fstat(fh.fileno())
            if looked != [(sha, size)]:  # the file released is the file the last look scanned: checked, not assumed
                os.unlink(name, dir_fd=mfd)
                raise BundleChanged("not released: the made file is not the copy the scan read (another sha256); "
                                    "the bundle was removed")  # fmt: skip
            with contextlib.suppress(FileNotFoundError):
                os.stat(name, dir_fd=sfd, follow_symlinks=False)
                os.unlink(name, dir_fd=mfd)
                raise SupportFolderRefused(f"{name} is already in {out}: not released")
            rec = {"file": name, "bytes": size, "sha256": sha}
            rid = next((str(r.get("id")) for r in runner.ops.running() if r.get("action") == ACTION), "")
            try:
                _audit_made(runner, rec, rid)
            except Exception as exc:
                os.unlink(name, dir_fd=mfd)
                raise BundleNotAudited(f"not released: the audit event of its making could not be written "
                                       f"({type(exc).__name__}); the bundle was removed") from exc  # fmt: skip
            os.rename(name, name, src_dir_fd=mfd, dst_dir_fd=sfd)
            moved = os.stat(name, dir_fd=sfd, follow_symlinks=False)
            if (moved.st_dev, moved.st_ino) != (hashed.st_dev, hashed.st_ino):
                os.unlink(name, dir_fd=sfd)
                raise BundleChanged("not released: the file under its final name is not the file that was hashed; "
                                    "removed")  # fmt: skip
    finally:
        os.close(mfd)
        os.close(sfd)
    removed = _prune(out, KEEP)
    lines = [x.replace(str(out / MAKING) + os.sep, "").replace(str(out) + os.sep, "") for x in said][-30:]
    if removed:
        lines.append(f"older bundles removed (the newest {KEEP} are kept): {', '.join(removed)}")
    lines += [f"{LINE_FILE}{name}", f"{LINE_BYTES}{size}", f"{LINE_SHA}{sha}"]
    return f"support bundle made: {name}, {size} bytes, sha256 {sha[:16]}", lines
