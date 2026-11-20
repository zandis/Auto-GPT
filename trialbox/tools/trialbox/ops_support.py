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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.trialbox import support_fields as sf

ACTION = "support_bundle"
SUBDIR = "support"
KEEP = 3  # the newest bundles kept in <ops>/support/; an older one is removed when a new one is made
NAME = re.compile(r"trialbox-support-\d{8}T\d{6}Z\.tar\.gz", re.ASCII)  # the builder's file name, matched whole
LINE_FILE, LINE_BYTES, LINE_SHA = "file ", "bytes ", "sha256 "
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)
MAKING = ".making"  # <ops>/support/.making: root alone; a bundle is made here and moved out only once audited
MAX_AGE_DAYS = 14  # a kept bundle older than this is removed by the runner's next pass (the review of 48b3210c, L6)
#: D-1381 (the review of 48b3210c): the reasons in the MANIFEST of a bundle made from the button. Every member is made
#: from allow-listed fields of closed kinds (tools/trialbox/support_fields.py); everything else stays on the box.
ALLOWED = ("made from the console's button (D-1381): only the fields on this member's allow-list, each a number, a "
           "yes/no, a time, a value from a fixed set or a string of a declared pattern; every other field (texts, "
           "paths, file names, command lines, ids) stays on the box")  # fmt: skip
LEFT_OUT: tuple[tuple[str, str], ...] = (
    ("logs/", "a bundle made from the console's button holds no service log (D-1381): a log line is free text and "
              "can carry a patient pseudonym"),
    ("env.redacted, cmd/compose-config.yaml, cmd/doctor.json, cmd/check_host.txt",
     "a bundle made from the console's button holds no setting and no command's text (D-1381): settings are "
     "redacted by name, and these print setting values and texts a person typed"),
    ("the raw ops snapshot, update history, audit verification and command outputs",
     "a bundle made from the console's button holds their allow-listed fields only (D-1381)"),
)  # fmt: skip


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


def _old(d: Path, keep: int, now: float) -> list[tuple[str, str]]:
    """The kept bundles to remove, with why: beyond the newest ``keep``, or older than :data:`MAX_AGE_DAYS`."""
    names = sorted(p.name for p in d.iterdir() if NAME.fullmatch(p.name) and p.is_file())
    out = [(n, "count") for n in names[:-keep]] if keep else [(n, "count") for n in names]
    for n in names[-keep:] if keep else []:
        with contextlib.suppress(OSError):
            if now - (d / n).stat().st_mtime > MAX_AGE_DAYS * 86400:
                out.append((n, "age"))
    return out


def _prune(runner: Any, d: Path, keep: int) -> list[str]:
    """Remove the bundles :func:`_old` names, each with the event ``support_bundle.removed`` (the file and why).
    Removing is the safe direction: a bundle is removed even when its event cannot be written (best effort)."""
    import time

    gone = []
    for name, why in _old(d, keep, time.time()):
        with contextlib.suppress(Exception):
            _audit(runner, {"action": f"{ACTION}.removed", "file": name, "why": why})
        with contextlib.suppress(OSError):
            (d / name).unlink()
            gone.append(name)
    return gone


def sweep(runner: Any) -> list[str]:
    """``OpsRunner.sweep_support``: each runner pass removes the kept bundles older than :data:`MAX_AGE_DAYS`."""
    d = support_dir(runner.ops.root)
    if not d.is_dir() or d.is_symlink():
        return []
    return _prune(runner, d, KEEP)


def _audit_made(runner: Any, rec: Mapping[str, Any], rid: str) -> None:
    """``console.ops`` with ``support_bundle.made``, the request, the file name, its size and its sha256, BEFORE the
    file gets its final name. Never best effort: no event, no bundle."""
    _audit(runner, {"action": f"{ACTION}.made", "request": rid, **rec})


def _audit(runner: Any, detail: Mapping[str, Any]) -> None:
    """One ``console.ops`` event of the runner. On a site box it is written inside the orchestrator as
    :meth:`tools.trialbox.ops.OpsRunner.audit` writes the result's event, and a failure raises (the command's exit);
    on the in-process box through the console's own writer (``audit_local``, set by ``console/ops_pages.py``), else
    the box's writer (:func:`tb_common.audit_writer.open_audit`)."""
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


def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def members(runner: Any, run: sf.Runner | None = None) -> tuple[dict[str, str], list[dict[str, str]]]:
    """The button's members, each from its allow-list (:mod:`tools.trialbox.support_fields`), and the MANIFEST's
    ``left_out`` rows: what was dropped, member by member, and what is never in such a bundle."""
    from tb_common import audit, metrics

    from tools import support_bundle
    from tools.trialbox import logs as tb_logs
    from tools.trialbox import ops as tb_ops

    box, deploy = runner.box, Path(runner.box.deploy)
    env = {**support_bundle._env_file(deploy), **dict(box.env or {}),
           **{k: v for k, v in os.environ.items() if k in ("TB_LOG_DIR", "TB_AUDIT_HOST_DIR")}}  # fmt: skip
    updates = deploy / "updates"
    installed = _read_json(updates / "installed.json")
    labels = sf.Labels(str(installed.get("bundle_id") or "") if isinstance(installed, Mapping) else "")
    targets = [str(t) for t in box.targets()]
    disks = sf.Disks(deploy, str(env.get("TB_DOCKER_ROOT") or "/var/lib/docker"), targets)
    raw: dict[str, Any] = {}
    try:
        snap = tb_ops.snapshot(box)
    except Exception as exc:  # the bundle reports, it does not stop: the type only
        snap = {"error": type(exc).__name__}
    raw["ops-snapshot.json"] = sf.snapshot(snap, labels, disks)
    facts = snap.get("health") if isinstance(snap.get("health"), Mapping) else None
    try:
        evaluated = metrics.evaluate(facts, None, datetime.now(UTC), metrics.Thresholds.from_env(env)).as_dict()
    except Exception:
        evaluated = {}
    raw["health.json"] = sf.health(evaluated)
    rel = _read_json(deploy / "release.json")
    raw["release.json"] = sf.release(tb_ops._version(), installed, rel, labels)
    try:
        hist = (updates / "history.jsonl").read_text(encoding="utf-8").splitlines()[-support_bundle.HISTORY_LINES :]
    except OSError:
        hist = None
    adir = Path(env.get("TB_AUDIT_HOST_DIR") or tb_logs.DEFAULT_AUDIT)
    try:
        raw["audit-verify.json"] = (sf.audit_verify(audit.verify(adir), state="verified") if adir.is_dir()
                                    else sf.audit_verify(state="not_here"))  # fmt: skip
    except PermissionError as exc:
        raw["audit-verify.json"] = sf.audit_verify(state="unreadable", error=type(exc).__name__)
    except Exception as exc:
        raw["audit-verify.json"] = sf.audit_verify(state="failed", error=type(exc).__name__)
    left: list[dict[str, str]] = [{"what": w, "why": y} for w, y in LEFT_OUT]
    if box.kind == "compose":
        run = run or support_bundle.run_cmd
        comp = tb_logs.compose(deploy)
        rc, ids = run([*comp, *sf.PS_IDS], 60)
        lines: list[str] = []
        if rc == 0 and ids.split():
            rc, out = run(["docker", "inspect", "--format", sf.INSPECT_FORMAT, *ids.split()], 60)
            lines = out.splitlines() if rc == 0 else []
        raw["services.json"] = sf.services(lines)
        rc, out = run(list(sf.DF), 30)
        raw["disks.json"] = sf.df(out.splitlines() if rc == 0 else [], disks)
        rc, out = run(list(sf.GPU), 60)
        raw["gpu.json"] = sf.gpu(out.splitlines() if rc == 0 else [])
    else:
        left.append({"what": "services.json, disks.json, gpu.json", "why": "the in-process box runs no command"})
    given: dict[str, str] = {}
    for name, value in raw.items():
        kept, dropped = sf.keep(sf.SCHEMAS[name], value)
        given[name] = json.dumps(kept, indent=1, ensure_ascii=True, sort_keys=True) + "\n"
        if dropped:
            left.append({"what": f"{name}: {dropped} field(s) not on its allow-list", "why": ALLOWED})
    if hist is not None:
        rows, dropped = [], 0
        for line in hist:
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            kept, n = sf.keep(sf.SCHEMAS["history.jsonl"], sf.history_line(row, labels))
            dropped += n + (not isinstance(row, Mapping))
            if kept is not None and kept is not sf._DROP:
                rows.append(json.dumps(kept, ensure_ascii=True, sort_keys=True))
        given["history.jsonl"] = "\n".join(rows) + ("\n" if rows else "")
        if dropped:
            left.append({"what": f"history.jsonl: {dropped} field(s) or line(s) not on its allow-list", "why": ALLOWED})
    return given, left


def do_support_bundle(runner: Any, args: Mapping[str, str]) -> tuple[str, list[str]]:
    """``OpsRunner.do_support_bundle``: the members (:func:`members`), checked and written by
    :func:`tools.support_bundle.build` into ``<ops>/support/.making``, audited, then given their final name in
    ``<ops>/support``; ``args`` unread."""
    from tools import support_bundle
    from tools.trialbox.ops import SERVICE_UID

    out = support_dir(runner.ops.root)
    sfd, mfd = _open_support(runner.ops.root, SERVICE_UID)
    try:
        said: list[str] = []
        looked: list[tuple[str, int]] = []
        given, left = members(runner)
        made = support_bundle.build(runner.box.deploy, out / MAKING, commands=False, say=said.append, given=given,
                                    given_left_out=left, scanned=lambda h, n: looked.append((h, n)))  # fmt: skip
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
            rid = str(getattr(runner, "request_id", "") or "")  # set by OpsRunner.run_one from the request itself
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
    removed = _prune(runner, out, KEEP)
    lines = [x.replace(str(out / MAKING) + os.sep, "").replace(str(out) + os.sep, "") for x in said][-30:]
    if removed:
        lines.append(f"older bundles removed (the newest {KEEP} are kept): {', '.join(removed)}")
    lines += [f"{LINE_FILE}{name}", f"{LINE_BYTES}{size}", f"{LINE_SHA}{sha}"]
    return f"support bundle made: {name}, {size} bytes, sha256 {sha[:16]}", lines
