"""Append-only, hash-chained audit log (SPEC §10.2).

``audit/YYYY-MM-DD.jsonl``, one event per line::

    {ts, event, job_id, ruleset, ruleset_version, model, prompt_version, snapshot, actor,
     input_sha, output_sha, recipients, detail, prev_hash, hash}

``hash = sha256(prev_hash + canonical_json(line_without_hash))`` where canonical JSON has sorted keys, no
whitespace and UTF-8 text. The first line of a day file chains to the last hash of the previous day file;
the very first line of the log uses ``GENESIS`` (64 zeros). An event goes to the file of its own date, or to the
newest file when that is later (a timestamp taken before midnight, written after the next day began). Writers
serialise through ``flock`` on ``audit/.lock`` so several processes/containers sharing the volume keep one chain.

**A torn last line** (power lost or disk full in the middle of a write) is repaired by the next writer instead of
stopping every later write (D-127, review F-03): the bytes after the last complete line are moved to
``<day>.jsonl.torn-<n>`` (kept as evidence), the file is cut back to the last complete line, and an
``audit.repaired`` event chained to that line records the length and sha256 of what was moved. ``verify`` then
passes, and the repair is visible in the chain. **Disk space** is checked before each write: below
``TB_AUDIT_MIN_FREE_MB`` (default 64) the write is refused with :class:`AuditFull` rather than risking a torn line.

**The head anchor** (D-272, register CR-054): ``audit/HEAD.json`` holds the number of events and the hash of the last
one, rewritten (atomically, under the same lock) after every line. ``verify`` compares the end of the chain with it,
so dropping the last events, deleting the newest day file or every day file, or rewriting and rehashing the chain
without the anchor all fail; ``verify(..., anchor=...)`` also checks an anchor kept elsewhere (the audit archive's
``HEAD.json``), which catches a rewrite that rewrote this file too. A writer that finds the chain and the anchor apart
refuses to write (:class:`AuditAnchorBroken`) until a person looks and runs ``tools/audit_verify.py --reanchor``,
which records the gap in the chain. A chain made before the anchor existed is adopted by its next write, with an
``audit.anchored`` event. The anchor is not keyed; the signed heads below are (T-211a).

**Signed heads and off-box anchors** (T-211a, D-355, register CR-042): :meth:`AuditLog.sign_head` signs where the
chain stands (event count and last hash) with the site's Ed25519 audit key (``audit_sign.key`` in the secrets folder,
wrapped under the KEK of T-210b when the folder has one) and writes the signed head, write-once, to every configured
anchor folder (``TB_AUDIT_ANCHOR_TARGETS``: local paths, such as the mounted hospital share; never a cloud service).
``verify(..., signed_heads=..., trusted_keys=...)`` then fails on a chain whose event ``n`` no longer has the signed
hash, which catches a line removed and the rest recomputed even when ``HEAD.json`` was rewritten too: a process that
can write the audit volume cannot make a signature. A new key is trusted only through an ``audit.signing_key_rotated``
event endorsed by the old key, and an old key's head over events after its rotation is refused.

**One writer** (T-211b, D-394, register CR-042): on a box the services do not write here. They call
:func:`tb_common.audit_writer.open_audit`, which sends each event to the append-only ``audit.journal`` table, and one
process (the ``audit-writer`` service) copies the journal into this chain. An event that came that way carries
``journal: {seq, role, at}``, the database role that sent it included.

**The clock** (T-211a, OPS-055): :func:`clock_state` reads whether the kernel clock is NTP-synchronised and, when
``TB_NTP_SERVER`` names the site's time server, the offset from it. ``doctor`` FAILs beyond
``TB_CLOCK_MAX_SKEW_S`` (default 60 seconds), and an unsynchronised clock in VALIDATION and PRODUCTION.

**No name planted in the folder is followed** (H-68, D-1351): the writer opens the folder once (``O_DIRECTORY |
O_NOFOLLOW``; a folder that is a link, is writable by every account, or belongs to another account than this one or
root is refused) and creates and opens ``.lock``, the day files, ``.HEAD.json.tmp``, ``HEAD.json`` and the
``.torn-<n>`` evidence relative to it with ``O_NOFOLLOW``; after each open the file must be a plain file with one link,
owned by the folder's owner or this process. Anything else is :class:`AuditAnchorBroken`, logged, and nothing is
written through it: a root command can no longer be made to truncate or append to a file outside the folder.

**No chart number in clear** (D-272, register CR-016): writers pass request lines, subjects and options through
:func:`mask_ids` / :func:`mask_detail`; the console pages use the same functions, so the page mask and the stored form
are one rule.
"""

from __future__ import annotations

import base64
import ctypes
import errno
import fcntl
import hashlib
import json
import logging
import os
import re
import socket
import stat
import struct
import sys
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO
from zoneinfo import ZoneInfo

GENESIS = "0" * 64
_log = logging.getLogger(__name__)


class AuditFull(OSError):
    """Too little free disk to write the audit log safely: the action must not go ahead unlogged."""


class AuditAnchorBroken(OSError):
    """The chain does not end where the head anchor says: events were dropped or rewritten. No write until a person
    has looked (``tools/audit_verify.py --reanchor``)."""


_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.jsonl$")
HEAD = "HEAD.json"

# ------------------------------------------------------------------------------------------------ chart numbers
#: Option keys that name a patient. ``console.app`` hides them from the job line; the audit stores them masked.
ID_KEYS = frozenset({"mrn", "chart", "chart_no", "name", "patient", "patient_name", "dob", "birth_date", "phone"})
ID_MASK = "•••"
_KEYS_RE = "|".join(sorted(ID_KEYS, key=len, reverse=True))
#: ``mrn=70000054`` in a request line or a subject
ID_IN_TEXT = re.compile(rf"(?i)(?<![\w.-])({_KEYS_RE})\s*=\s*(\S+)")
#: ``'mrn': '70000054'`` / ``"mrn": 70000054`` (a dict printed as text, as a page does with a stored ``options``)
ID_IN_MAPPING = re.compile(rf"""(?i)(['"])({_KEYS_RE})\1(\s*:\s*)(?:(['"])((?:(?!\4).)*)\4|([^,}}\s]+))""")


def mask_ids(text: str) -> str:
    """``CASE GZQO mrn=70000054`` -> ``CASE GZQO mrn=•••``; the same for a printed mapping (``'mrn': '•••'``)."""
    out = ID_IN_TEXT.sub(lambda m: f"{m.group(1)}={ID_MASK}", text or "")
    return ID_IN_MAPPING.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(1)}{m.group(3)}'{ID_MASK}'", out)


def mask_detail(value: Any) -> Any:
    """``value`` with every identifying key's value replaced by ``•••`` and :func:`mask_ids` applied to every text."""
    if isinstance(value, dict):
        return {
            k: (ID_MASK if str(k).lower() in ID_KEYS and v not in (None, "") else mask_detail(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [mask_detail(v) for v in value]
    if isinstance(value, str):
        return mask_ids(value)
    return value


def clear_ids(value: Any, path: str = "") -> list[str]:
    """Where in ``value`` an identifying value stands in clear (paths such as ``detail.options.mrn``), never what."""
    found: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            sub = f"{path}.{k}" if path else str(k)
            if str(k).lower() in ID_KEYS and v not in (None, "", ID_MASK) and not isinstance(v, dict | list):
                found.append(sub)
            else:
                found.extend(clear_ids(v, sub))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found.extend(clear_ids(v, f"{path}[{i}]"))
    elif isinstance(value, str):
        hits = [m.group(1).lower() for m in ID_IN_TEXT.finditer(value) if m.group(2) != ID_MASK]
        hits += [m.group(2).lower() for m in ID_IN_MAPPING.finditer(value) if (m.group(5) or m.group(6)) != ID_MASK]
        found.extend(f"{path}:{k}" for k in sorted(set(hits)))
    return found


def canonical(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def line_hash(prev_hash: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical(body)).encode("utf-8")).hexdigest()


def _day_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.jsonl") if _DAY_RE.match(p.name))


def _last_line_of(fh: BinaryIO) -> str | None:
    """The last non-empty line of an open binary file (by path, or through the audit folder: H-68)."""
    fh.seek(0, os.SEEK_END)
    pos = fh.tell()
    data = b""
    while pos > 0:
        step = min(4096, pos)
        pos -= step
        fh.seek(pos)
        data = fh.read(step) + data
        stripped = data.rstrip(b"\n")
        if b"\n" in stripped:
            return stripped.rsplit(b"\n", 1)[1].decode("utf-8")
    stripped = data.rstrip(b"\n")
    return stripped.decode("utf-8") if stripped else None


_TAIL_STEP = 1 << 16  # T-697: the tail is read back in steps of 64 KiB, never the whole day file


def _line_start(fh: Any, end: int) -> int:
    """The offset just after the last ``\\n`` before ``end`` (0 when there is none), read backwards from ``end``."""
    pos = end
    while pos > 0:
        step = min(_TAIL_STEP, pos)
        pos -= step
        fh.seek(pos)
        i: int = fh.read(step).rfind(b"\n")
        if i >= 0:
            return int(pos + i + 1)
    return 0


def lines_backward(path: Path) -> Iterator[bytes]:
    """T-697: the file's lines from the last to the first (without their ``\\n``), read back from its end in steps:
    a reader that wants the newest lines never reads the whole day file."""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        end = fh.tell()
        if not end:
            return
        fh.seek(end - 1)
        if fh.read(1) == b"\n":
            end -= 1
        while True:
            start = _line_start(fh, end)
            fh.seek(start)
            yield fh.read(end - start)
            if start == 0:
                return
            end = start - 1


def read_head(directory: Path) -> dict[str, Any] | None:
    """The head anchor of ``directory``, or None when there is none. An unreadable anchor raises ``ValueError``."""
    path = directory / HEAD
    if not path.is_file():
        return None
    return _head_record(path.read_text(encoding="utf-8"), str(path))


def _head_record(text: str, where: str) -> dict[str, Any]:
    rec = json.loads(text)
    if not isinstance(rec, dict) or not isinstance(rec.get("lines"), int) or not isinstance(rec.get("hash"), str):
        raise ValueError(f"{where} is not a head anchor")
    return rec


def write_head(directory: Path, lines: int, last_hash: str, file: str | None) -> dict[str, Any]:
    """Replace the head anchor atomically (write, fsync, rename, fsync the folder), through the folder (H-68)."""
    with _Folder(directory) as folder:
        return folder.write_head(lines, last_hash, file)


# ------------------------------------------------------------------------------------------------ the folder (H-68)
#: H-68 (D-1351): the folder is opened once, never through a link in its last name; every file in it is opened
#: relative to that descriptor, never through a link, and never blocks on a FIFO put in a file's place
_O_FOLDER = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_O_FILE = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_NEW_FILE_MODE = 0o666  # what open() gave before H-68, under the umask: the files keep their modes


def _owners_allowed(folder_stat: os.stat_result) -> set[int]:
    """The owners a file in the audit folder may have: the folder's owner, and this process (root appending in the
    service account's folder, as a restore does, makes root's files; D-724 gives them back after)."""
    return {folder_stat.st_uid, os.geteuid()}


def _refused(name: str, why: str) -> AuditAnchorBroken:
    """H-68: the refusal of a name in the audit folder, logged; the message names the name, never a link's target."""
    msg = (f"the audit folder's {name} {why}: refused, nothing was written through it. A person must look at the "
           "folder before the next write (H-68)")  # fmt: skip
    _log.error("%s", msg)
    return AuditAnchorBroken(msg)


class _Folder:
    """The audit folder, opened once (``O_DIRECTORY | O_NOFOLLOW``): every file of the chain is created and opened
    relative to it with ``O_NOFOLLOW``, checked after the open (a plain file, one link, an allowed owner), and
    renamed within it. Nothing is reopened by path. Refusals are :class:`AuditAnchorBroken`."""

    def __init__(self, directory: Path) -> None:
        self.path = directory
        try:
            self.fd = os.open(directory, _O_FOLDER)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                raise _refused("folder itself", "is a symbolic link or not a folder") from None
            raise
        try:
            st = os.fstat(self.fd)
            me = os.geteuid()
            if st.st_mode & stat.S_IWOTH:
                raise _refused("folder itself", "is writable by every account (any of them could plant a name)")
            if me != 0 and st.st_uid not in (me, 0):
                raise _refused("folder itself", f"is owned by uid {st.st_uid}, neither this account nor root")
            self.owners = _owners_allowed(st)
        except BaseException:
            os.close(self.fd)
            raise

    def __enter__(self) -> _Folder:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def open(self, name: str, flags: int, *, create: bool = False, exclusive: bool = False) -> int:
        """A descriptor of ``name`` in the folder; refuses a link, anything but a plain file, a file with another
        hard link, or a file of an owner the folder does not allow. Never truncates: a caller truncates after."""
        fl = flags | _O_FILE | (os.O_CREAT if create else 0) | (os.O_EXCL if exclusive else 0)
        try:
            fd = os.open(name, fl, _NEW_FILE_MODE, dir_fd=self.fd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise _refused(name, "is a symbolic link") from None
            if exc.errno in (errno.EISDIR, errno.ENXIO, errno.ENOTDIR):
                raise _refused(name, "is not a plain file") from None
            raise
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise _refused(name, "is not a plain file")
            if st.st_nlink != 1:
                raise _refused(name, f"has {st.st_nlink} hard links (one may be a file outside the folder)")
            if st.st_uid not in self.owners:
                raise _refused(name, f"is owned by uid {st.st_uid}, not by the folder's owner or this account")
        except BaseException:
            os.close(fd)
            raise
        return fd

    def present(self, name: str) -> bool:
        try:
            os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    def day_files(self) -> list[Path]:
        return [self.path / n for n in sorted(os.listdir(self.fd)) if _DAY_RE.match(n)]

    def last_line(self, name: str) -> str | None:
        with os.fdopen(self.open(name, os.O_RDONLY), "rb") as fh:
            return _last_line_of(fh)

    def count_lines(self, files: list[Path]) -> int:
        n = 0
        for path in files:
            with os.fdopen(self.open(path.name, os.O_RDONLY), "rb") as fh:
                n += sum(1 for raw in fh if raw.strip())
        return n

    def read_head(self) -> dict[str, Any] | None:
        if not self.present(HEAD):
            return None
        with os.fdopen(self.open(HEAD, os.O_RDONLY), "r", encoding="utf-8") as fh:
            return _head_record(fh.read(), HEAD)

    def write_head(self, lines: int, last_hash: str, file: str | None) -> dict[str, Any]:
        """Replace the head anchor atomically (write, fsync, rename, fsync the folder)."""
        rec = {"file": file, "hash": last_hash, "lines": lines}
        tmp = f".{HEAD}.tmp"
        fd = self.open(tmp, os.O_WRONLY, create=True)
        os.ftruncate(fd, 0)  # after the checks, so never through a name planted in its place
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(canonical(rec) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, HEAD, src_dir_fd=self.fd, dst_dir_fd=self.fd)
        os.fsync(self.fd)
        return rec


class AuditLog:
    """Writer for the audit chain in ``directory``."""

    FIELDS = (
        "job_id",
        "ruleset",
        "ruleset_version",
        "model",
        "prompt_version",
        "snapshot",
        "actor",
        "input_sha",
        "output_sha",
        "recipients",
        "detail",
        "journal",  # set by the drain only (tb_common.audit_writer, D-394): the journal row the event came from
    )

    def __init__(self, directory: Path, tz: str = "Asia/Taipei") -> None:
        self.directory = directory
        self.zone = ZoneInfo(tz)
        directory.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        # H-68 (D-1351): the folder is opened once here and every file below goes through it (never by path)
        # (held per thread: one AuditLog may serve several threads, and the flock lets one of them in at a time)
        held = self.__dict__.setdefault("_held", threading.local())
        with _Folder(self.directory) as folder:
            fd = folder.open(".lock", os.O_RDWR | os.O_APPEND, create=True)
            with os.fdopen(fd, "a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                held.folder = folder
                try:
                    yield
                finally:
                    held.folder = None
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _dir(self) -> _Folder:
        folder: _Folder | None = getattr(self.__dict__.get("_held"), "folder", None)
        if folder is None:
            raise RuntimeError("the audit folder is read and written only under the writer's lock (H-68)")
        return folder

    def _check_space(self) -> None:
        need = int(os.environ.get("TB_AUDIT_MIN_FREE_MB", "64")) * 1024 * 1024
        st = os.fstatvfs(self._dir().fd)
        if st.f_bavail * st.f_frsize < need:
            raise AuditFull(f"audit volume has less than {need // (1024 * 1024)} MB free: free disk space first")

    def _repair_torn(self, files: list[Path]) -> dict[str, Any] | None:
        """Cut a torn or unreadable last line off the newest file; return what was moved, or None."""
        if not files:
            return None
        path = files[-1]
        folder = self._dir()
        # T-697 (F-12): only the file's tail is read (each append did read the whole day file: quadratic over a day
        # of a million events, and a day file larger than the writer's memory cap would have killed it)
        with os.fdopen(folder.open(path.name, os.O_RDWR), "r+b") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if not size:
                return None
            fh.seek(size - 1)
            if fh.read(1) != b"\n":
                cut = _line_start(fh, size)  # keep every complete line
            else:
                cut = size
                last_start = _line_start(fh, size - 1)
                fh.seek(last_start)
                try:
                    rec = json.loads(fh.read(size - 1 - last_start).decode("utf-8"))
                    if not isinstance(rec, dict) or "hash" not in rec:
                        raise ValueError("no hash")
                except (ValueError, UnicodeDecodeError):
                    cut = last_start  # a complete but unreadable last line: the same damage
            if cut == size:
                return None
            n = 1
            while True:  # the first free .torn-<n>, made new (O_EXCL): a name already there is never written
                dest = path.with_name(f"{path.name}.torn-{n}")
                try:
                    out_fd = folder.open(dest.name, os.O_WRONLY, create=True, exclusive=True)
                    break
                except FileExistsError:
                    n += 1
            digest = hashlib.sha256()
            fh.seek(cut)
            with os.fdopen(out_fd, "wb") as out:  # the torn bytes kept as evidence, copied in steps
                while block := fh.read(_TAIL_STEP):
                    digest.update(block)
                    out.write(block)
            fh.truncate(cut)  # the same descriptor, never the name again
            fh.flush()
            os.fsync(fh.fileno())
        return {"file": path.name, "bytes": size - cut, "sha256": digest.hexdigest(), "kept_as": dest.name}

    def _write(self, files: list[Path], now: datetime, body: dict[str, Any], lines: int) -> list[Path]:
        """Chain ``body`` to the end of the chain, append it, then move the head anchor to it. Returns the files."""
        prev = self._prev_hash(files)
        body["prev_hash"] = prev
        body["hash"] = line_hash(prev, body)
        day = now.astimezone(self.zone).date().isoformat()
        if files and files[-1].stem > day:
            # stamped before midnight but written after an event of the next day (e.g. the gateway's
            # mail.received after the orchestrator's job events): stay on the newest file, so that the files
            # read in name order remain the chain order; the event keeps its own timestamp
            day = files[-1].stem
        path = self.directory / f"{day}.jsonl"
        folder = self._dir()
        with os.fdopen(folder.open(path.name, os.O_WRONLY | os.O_APPEND, create=True), "a", encoding="utf-8") as fh:
            fh.write(canonical(body) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        # the line first, then the anchor: a crash in between leaves the chain one line past the anchor, chained
        # to it, which the next writer and verify accept; never an anchor past the chain
        folder.write_head(lines + 1, body["hash"], path.name)
        return folder.day_files()

    def _prev_hash(self, files: list[Path]) -> str:
        for path in reversed(files):
            last = self._dir().last_line(path.name)
            if last:
                return str(json.loads(last)["hash"])
        return GENESIS

    def _last_record(self, files: list[Path]) -> dict[str, Any] | None:
        for path in reversed(files):
            last = self._dir().last_line(path.name)
            if last:
                return dict(json.loads(last))
        return None

    def _anchor(self, files: list[Path]) -> tuple[int | None, str]:
        """The number of events in the chain by the head anchor, and the last hash; None when there is no anchor
        (a chain made before D-272). Raises :class:`AuditAnchorBroken` when the chain and the anchor are apart."""
        chain_hash = self._prev_hash(files)
        try:
            head = self._dir().read_head()
        except (ValueError, UnicodeDecodeError) as exc:
            raise AuditAnchorBroken(f"the audit head anchor cannot be read ({exc}): run tools/audit_verify.py") from exc
        if head is None:
            return (0 if chain_hash == GENESIS else None), chain_hash
        if head["hash"] == chain_hash:
            return int(head["lines"]), chain_hash
        last = self._last_record(files)
        if last is not None and last.get("prev_hash") == head["hash"]:
            return int(head["lines"]) + 1, chain_hash  # the line was written, the anchor not yet (crash)
        raise AuditAnchorBroken(
            f"the audit chain ends at {chain_hash[:16]}, its head anchor says {head['hash'][:16]} after "
            f"{head['lines']} events: events were dropped or rewritten. Nothing is written until a person has looked "
            "(tools/audit_verify.py, then --reanchor)"
        )

    def append(self, event: str, *, ts: datetime | None = None, **fields: Any) -> dict[str, Any]:
        """Append one event; unknown keyword fields go into ``detail``. Returns the written record."""
        now = ts or datetime.now(self.zone)
        if now.tzinfo is None:
            raise ValueError("audit timestamps must be timezone-aware")
        body: dict[str, Any] = {"ts": now.isoformat(timespec="milliseconds"), "event": event}
        detail: dict[str, Any] = dict(fields.pop("detail", None) or {})
        for key, val in fields.items():
            if key in self.FIELDS:
                if val is not None:
                    body[key] = val
            else:
                detail[key] = val
        if detail:
            body["detail"] = detail
        stamp = now.isoformat(timespec="milliseconds")
        with self._locked():
            self._check_space()
            files = self._dir().day_files()
            repaired = self._repair_torn(files)
            if repaired:
                files = self._dir().day_files()
            lines, chain_hash = self._anchor(files)
            if lines is None:  # a chain from before the anchor: adopt it, visibly
                lines = self._dir().count_lines(files)
                files = self._write(files, now, {"ts": stamp, "event": "audit.anchored", "actor": "tb_common.audit",
                                                 "detail": {"lines": lines, "head": chain_hash}}, lines)  # fmt: skip
                lines += 1
            if repaired:
                files = self._write(files, now, {"ts": stamp, "event": "audit.repaired", "actor": "tb_common.audit",
                                                 "detail": repaired}, lines)  # fmt: skip
                lines += 1
            self._write(files, now, body, lines)
        return body

    def reanchor(self, actor: str, reason: str, *, ts: datetime | None = None) -> dict[str, Any]:
        """A person has looked at a chain that does not match its head anchor: record the gap in the chain (the old
        anchor, the chain as found, the reason) and anchor the chain where it now ends. Never rewrites a line."""
        if not reason.strip():
            raise ValueError("a reason is required")
        now = ts or datetime.now(self.zone)
        with self._locked():
            self._check_space()
            files = self._dir().day_files()
            try:
                before = self._dir().read_head()
            except (ValueError, UnicodeDecodeError):
                before = {"unreadable": True}
            lines = self._dir().count_lines(files)
            body: dict[str, Any] = {
                "ts": now.isoformat(timespec="milliseconds"),
                "event": "audit.reanchored",
                "actor": actor,
                "detail": {"before": before, "chain": {"lines": lines, "hash": self._prev_hash(files)},
                           "reason": reason.strip()[:500]},
            }  # fmt: skip
            self._write(files, now, body, lines)
        return body

    def sign_head(
        self,
        private_pem: bytes,
        public_pem: bytes,
        targets: Sequence[Path],
        *,
        actor: str = "tb_common.audit",
        ts: datetime | None = None,
    ) -> dict[str, Any]:
        """T-211a: sign where the chain stands and write the signed head to every anchor folder in ``targets``
        (write-once); then record an ``audit.head_signed`` event. Refuses a chain that does not verify. Returns the
        signed head with ``failed`` (the folders that did not take it); :class:`AuditSignError` when none did."""
        now = ts or datetime.now(self.zone)
        with self._locked():
            self._check_space()
            return _sign_and_publish(self, private_pem, public_pem, targets, actor, now)

    def rotate_signing_key(
        self,
        old_private_pem: bytes,
        old_public_pem: bytes,
        new_public_pem: bytes,
        *,
        actor: str,
        reason: str,
        ts: datetime | None = None,
    ) -> dict[str, Any]:
        """T-211a: record the hand-over from the old signing key to a new one, endorsed by the old key. Heads signed
        by the old key after this event are refused by :func:`verify`; the new key is trusted from here on."""
        from tb_common.crypto import ed25519_sign

        if not reason.strip():
            raise ValueError("a reason is required")
        old_id, new_id = signing_key_id(old_public_pem), signing_key_id(new_public_pem)
        if old_id == new_id:
            raise ValueError("the new key is the old key")
        pub = new_public_pem.decode("ascii").strip() + "\n"
        endorsement = ed25519_sign(old_private_pem, endorsement_bytes(old_id, new_id, pub))
        return self.append(ROTATED_EVENT, ts=ts, actor=actor, detail={
            "old_key_id": old_id, "new_key_id": new_id, "new_public": pub, "reason": reason.strip()[:500],
            "endorsement": base64.b64encode(endorsement).decode("ascii")})  # fmt: skip


@dataclass
class VerifyResult:
    ok: bool
    files: int = 0
    lines: int = 0
    last_hash: str = GENESIS
    errors: list[str] = field(default_factory=list)
    head: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


def verify(
    directory: Path,
    *,
    anchor: dict[str, Any] | None = None,
    require_head: bool = True,
    signed_heads: Sequence[Mapping[str, Any]] | None = None,
    trusted_keys: Mapping[str, bytes] | None = None,
) -> VerifyResult:
    """Recompute the whole chain across all day files; report every broken link, and check the end of the chain
    against the head anchor (``HEAD.json``; required unless ``require_head`` is False, for a copy such as the
    archive) and, when given, against ``anchor`` (``{"lines": n, "hash": h}`` kept elsewhere: event ``n`` of the
    chain must have hash ``h``).

    With ``signed_heads`` (T-211a; read from an off-box anchor folder with :func:`read_signed_heads`), every signed
    head must carry a valid signature of a trusted key (``trusted_keys``: key id -> public PEM, plus the keys that
    ``audit.signing_key_rotated`` events of the chain endorse) and event ``lines`` of the chain must have its hash.
    An empty list is a failure: the caller asked for signed heads and none was found."""
    res = VerifyResult(ok=True)
    prev = GENESIS
    want = int(anchor["lines"]) if anchor else -1
    wanted: set[int] = {int(h["lines"]) for h in signed_heads or () if isinstance(h.get("lines"), int)}
    at: dict[int, str] = {0: GENESIS} if 0 in wanted else {}
    rotations: list[tuple[int, dict[str, Any]]] = []
    at_anchor: str | None = GENESIS if want == 0 else None
    last_prev: str | None = None
    for path in _day_files(directory):
        res.files += 1
        with path.open(encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                raw = raw.rstrip("\n")
                if not raw:
                    res.errors.append(f"{path.name}:{lineno}: empty line")
                    continue
                res.lines += 1
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as exc:
                    res.errors.append(f"{path.name}:{lineno}: invalid JSON ({exc})")
                    prev = "?"
                    continue
                if canonical(rec) != raw:
                    res.errors.append(f"{path.name}:{lineno}: not canonical JSON")
                claimed = rec.pop("hash", None)
                if rec.get("prev_hash") != prev:
                    res.errors.append(f"{path.name}:{lineno}: prev_hash does not match previous line")
                expected = line_hash(str(rec.get("prev_hash")), rec)
                if claimed != expected:
                    res.errors.append(f"{path.name}:{lineno}: hash mismatch")
                if rec.get("event") in ("audit.anchored", "audit.reanchored"):
                    res.notes.append(f"{path.name}:{lineno}: {rec.get('event')} {canonical(rec.get('detail') or {})}")
                if rec.get("event") == ROTATED_EVENT and rec.get("journal") is not None:
                    # NEW-SEC-2 (D-718): the chain's writer records a rotation itself; one that came through the
                    # journal was sent by a service (a chain written before the drain refused the name)
                    sender = (rec.get("journal") or {}).get("role")
                    res.notes.append(f"{path.name}:{lineno}: {ROTATED_EVENT} from the journal ({sender}): "
                                     "not taken as a key rotation")  # fmt: skip
                elif rec.get("event") == ROTATED_EVENT:
                    rotations.append((res.lines, dict(rec.get("detail") or {})))
                last_prev = str(rec.get("prev_hash"))
                prev = str(claimed)
                if res.lines == want:
                    at_anchor = prev
                if res.lines in wanted:
                    at[res.lines] = prev
    res.last_hash = prev
    try:
        res.head = read_head(directory)
    except (ValueError, UnicodeDecodeError) as exc:
        res.errors.append(f"{HEAD}: unreadable ({exc})")
    else:
        if res.head is None:
            if require_head:
                res.errors.append(
                    f"{HEAD}: no head anchor, so dropped events, a deleted day file or an emptied folder cannot be "
                    "told from a short chain (a chain from before D-272 gets one at its next write)"
                )
        elif (res.head["lines"], res.head["hash"]) != (res.lines, res.last_hash):
            if res.lines == res.head["lines"] + 1 and last_prev == res.head["hash"]:
                res.notes.append(f"{HEAD}: the chain is one event past the anchor (a write in progress, or cut short)")
            else:
                res.errors.append(
                    f"{HEAD}: the chain ends at event {res.lines} ({res.last_hash[:16]}), the head anchor says event "
                    f"{res.head['lines']} ({str(res.head['hash'])[:16]}): events dropped, a day file deleted, or the "
                    "chain rewritten"
                )
    if anchor:
        if res.lines < want:
            res.errors.append(f"anchor: the chain has {res.lines} events, the anchor kept elsewhere says {want}")
        elif at_anchor != anchor.get("hash"):
            res.errors.append(f"anchor: event {want} does not have the hash kept elsewhere: the chain was rewritten")
    if signed_heads is not None:
        _check_signed_heads(res, signed_heads, dict(trusted_keys or {}), at, rotations)
    res.ok = not res.errors
    return res


# ------------------------------------------------------------------------------------------------ signed heads (T-211a)
HEAD_FORMAT = "tb-audit-head/1"
SIGN_KEY_FILE = "audit_sign.key"  # the Ed25519 private key (PEM), in the secrets folder, wrapped under the KEK
SIGN_PUB_FILE = "audit_sign.pub"  # its public key (PEM), beside it and in every anchor folder
SIGNED_EVENT = "audit.head_signed"
ROTATED_EVENT = "audit.signing_key_rotated"
ANCHOR_TARGETS_ENV = "TB_AUDIT_ANCHOR_TARGETS"
_HEADS_DIR = "heads"
_KEYS_DIR = "keys"


class AuditSignError(RuntimeError):
    """A head cannot be signed or published: no key, a key that is not its public key's pair, a broken chain, or no
    anchor folder that took it."""


def signing_key_id(public_pem: bytes) -> str:
    """The id of an audit signing key: a fingerprint of its public key (``tb_common.crypto.key_fingerprint``)."""
    from tb_common.crypto import key_fingerprint

    return key_fingerprint(public_pem.strip())


def _signed_bytes(rec: Mapping[str, Any]) -> bytes:
    return canonical({k: v for k, v in rec.items() if k != "sig"}).encode("utf-8")


def make_signed_head(
    lines: int, last_hash: str, file: str | None, private_pem: bytes, public_pem: bytes, *, ts: datetime
) -> dict[str, Any]:
    """A signed head over event ``lines`` with hash ``last_hash``. The signature is checked with ``public_pem``
    before it is returned, so a key file that is not its public key's pair is found here, not at the next audit."""
    from tb_common.crypto import ed25519_sign, ed25519_verify

    rec: dict[str, Any] = {"format": HEAD_FORMAT, "lines": lines, "hash": last_hash, "file": file,
                           "ts": ts.isoformat(timespec="seconds"), "key_id": signing_key_id(public_pem)}  # fmt: skip
    sig = ed25519_sign(private_pem, _signed_bytes(rec))
    if not ed25519_verify(public_pem, _signed_bytes(rec), sig):
        raise AuditSignError(f"the audit signing key is not the pair of {SIGN_PUB_FILE}: nothing was signed")
    rec["sig"] = base64.b64encode(sig).decode("ascii")
    return rec


def signed_head_problem(rec: Mapping[str, Any], public_pem: bytes) -> str | None:
    """Why ``rec`` is not a valid signed head under ``public_pem``, or None."""
    from tb_common.crypto import ed25519_verify

    if (
        rec.get("format") != HEAD_FORMAT
        or not isinstance(rec.get("lines"), int)
        or not isinstance(rec.get("hash"), str)
    ):
        return f"not a {HEAD_FORMAT} record"
    try:
        sig = base64.b64decode(str(rec.get("sig") or ""), validate=True)
        good = ed25519_verify(public_pem, _signed_bytes(rec), sig)
    except ValueError:
        good = False
    return None if good else "the signature does not verify: the head was changed or signed by another key"


def endorsement_bytes(old_key_id: str, new_key_id: str, new_public: str) -> bytes:
    """What the old key signs when it hands over to a new one (``audit.signing_key_rotated``)."""
    return canonical({"format": "tb-audit-key-rotation/1", "new_key_id": new_key_id, "new_public": new_public,
                      "old_key_id": old_key_id}).encode("utf-8")  # fmt: skip


def _check_signed_heads(
    res: VerifyResult,
    heads: Sequence[Mapping[str, Any]],
    trust: dict[str, bytes],
    at: Mapping[int, str],
    rotations: list[tuple[int, dict[str, Any]]],
) -> None:
    from tb_common.crypto import ed25519_verify

    retired: dict[str, int] = {}
    handed: dict[str, str] = {}
    for idx, d in rotations:  # chain order: each new key is endorsed by a key trusted before it
        old, new, pub = str(d.get("old_key_id")), str(d.get("new_key_id")), str(d.get("new_public") or "")
        try:
            sig = base64.b64decode(str(d.get("endorsement") or ""), validate=True)
            good = old in trust and ed25519_verify(trust[old], endorsement_bytes(old, new, pub), sig)
        except ValueError:
            good = False
        if not good or signing_key_id(pub.encode()) != new:
            res.errors.append(f"signed heads: the key rotation at event {idx} is not endorsed by a trusted key")
            continue
        if old in handed and handed[old] != new:  # a key rotated out (perhaps because it leaked) endorses no other
            res.errors.append(f"signed heads: event {idx}: key {old} was rotated out at event {retired[old]}")
            continue
        trust[new] = pub.encode()
        retired.setdefault(old, idx)
        handed[old] = new
        res.notes.append(f"signed heads: key {old} handed over to {new} at event {idx}")
    if not heads:
        res.errors.append("signed heads: none found in the anchor folder, so the chain is checked by nothing signed")
        return
    covered = 0
    for h in heads:
        n, kid = h.get("lines"), str(h.get("key_id"))
        name = f"signed head {h.get('ts')} (event {n}, key {kid})"
        if kid not in trust:
            res.errors.append(f"{name}: not a trusted key, and no rotation record in the chain hands over to it")
            continue
        why = signed_head_problem(h, trust[kid])
        if why:
            res.errors.append(f"{name}: {why}")
            continue
        assert isinstance(n, int)
        if kid in retired and n >= retired[kid]:
            res.errors.append(f"{name}: the key was rotated out at event {retired[kid]} and cannot sign after it")
            continue
        if n > res.lines:
            res.errors.append(f"{name}: the chain has only {res.lines} events: events were dropped after signing")
        elif at.get(n) != h.get("hash"):
            res.errors.append(f"{name}: event {n} does not have the signed hash: the chain was rewritten")
        else:
            covered = max(covered, n)
    if covered:
        res.notes.append(
            f"signed heads: events 1 to {covered} are covered by a valid signature; "
            f"{res.lines - covered} after it are not yet"
        )


def anchor_targets(env: Mapping[str, str] | None = None) -> list[Path]:
    """The off-box anchor folders: ``TB_AUDIT_ANCHOR_TARGETS``, paths separated by ``os.pathsep``."""
    env = os.environ if env is None else env
    return [Path(p) for p in (env.get(ANCHOR_TARGETS_ENV) or "").split(os.pathsep) if p.strip()]


def _write_once(path: Path, data: bytes) -> bool:
    """Write ``data`` to a new file; False when the file is already there with the same bytes. A different file of
    the same name is never replaced (:class:`AuditSignError`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        if path.read_bytes() == data:
            return False
        raise AuditSignError(f"{path} is already there with other content: it is never replaced") from None
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    return True


def publish_head(target: Path, rec: Mapping[str, Any], public_pem: bytes) -> Path:
    """Write a signed head to an anchor folder (``heads/<ts>-<lines>.json``) and the signing public key
    (``keys/<key id>.pub``), both write-once."""
    if not target.is_dir():
        raise AuditSignError(f"the anchor folder {target} is not there (not mounted?)")
    _write_once(target / _KEYS_DIR / f"{rec['key_id']}.pub", public_pem)
    stamp = str(rec["ts"]).replace(":", "").replace("-", "")
    path = target / _HEADS_DIR / f"{stamp}-{int(rec['lines']):012d}.json"
    _write_once(path, (canonical(dict(rec)) + "\n").encode("utf-8"))
    return path


def read_signed_heads(target: Path) -> list[dict[str, Any]]:
    """Every signed head in an anchor folder, oldest first. An unreadable file is returned as an empty record, so
    that :func:`verify` reports it instead of skipping it."""
    out: list[dict[str, Any]] = []
    for path in sorted((target / _HEADS_DIR).glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = {}
        out.append(rec if isinstance(rec, dict) else {})
    return out


def read_public_keys(paths: Sequence[Path]) -> dict[str, bytes]:
    """Trusted public keys by id, from ``.pub`` files or folders of them (an anchor folder's ``keys/``)."""
    out: dict[str, bytes] = {}
    for p in paths:
        for f in sorted(p.glob("*.pub")) if p.is_dir() else [p]:
            pem = f.read_bytes()
            out[signing_key_id(pem)] = pem
    return out


def _sign_and_publish(log: AuditLog, private_pem: bytes, public_pem: bytes, targets: Sequence[Path], actor: str,
                      now: datetime) -> dict[str, Any]:  # fmt: skip
    """Under the writer's lock: sign the chain as it stands, publish to every target, record it in the chain."""
    for t in targets:
        if _inside(t, log.directory):
            raise AuditSignError(f"the anchor folder {t} is inside the audit folder: it must be off the audit volume")
    files = log._dir().day_files()
    lines, chain_hash = log._anchor(files)
    if lines is None:
        raise AuditSignError("the chain has no head anchor yet: write one event first, then sign")
    res = verify(log.directory)
    if not res.ok:
        raise AuditSignError(f"the chain does not verify ({res.errors[0]}): nothing was signed")
    last = files[-1].name if files else None
    rec = make_signed_head(lines, chain_hash, last, private_pem, public_pem, ts=now)
    written: list[str] = []
    failed: list[str] = []
    for t in targets:
        try:
            written.append(publish_head(t, rec, public_pem).name)
        except (OSError, AuditSignError) as exc:
            failed.append(f"{t}: {exc}")
    detail: dict[str, Any] = {"lines": lines, "head": chain_hash, "key_id": rec["key_id"], "anchors": len(written)}
    if failed:
        detail["failed"] = failed
    log._write(files, now, {"ts": now.isoformat(timespec="milliseconds"), "event": SIGNED_EVENT, "actor": actor,
                            "detail": detail}, lines)  # fmt: skip
    if not written:
        raise AuditSignError("no anchor folder took the signed head: " + "; ".join(failed or ["none is configured"]))
    rec["failed"] = failed
    return rec


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


# ------------------------------------------------------------------------------------------------ the clock (T-211a)
NTP_SERVER_ENV = "TB_NTP_SERVER"
MAX_SKEW_ENV = "TB_CLOCK_MAX_SKEW_S"
DEFAULT_MAX_SKEW_S = 60.0
_NTP_EPOCH = 2208988800  # seconds from 1900-01-01 to 1970-01-01
_TIME_ERROR = 5  # adjtimex: the clock is not synchronised (STA_UNSYNC)


@dataclass(frozen=True)
class ClockState:
    synced: bool | None  # the kernel's NTP state; None when it cannot be read here
    offset: float | None  # seconds this clock is ahead (+) or behind (-) the site's time server; None: not measured
    server: str | None
    error: str | None = None  # why the server was not measured


def kernel_clock_synced() -> bool | None:
    """Whether the kernel says its clock is NTP-synchronised (``adjtimex`` read-only, as ``timedatectl`` reads it);
    None when this is not Linux or the call fails. A container reads the host's kernel clock."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        buf = ctypes.create_string_buffer(512)  # struct timex, zeroed: modes 0 is a read, never a change
        rc: int = ctypes.CDLL(None, use_errno=True).adjtimex(buf)
    except (OSError, AttributeError):
        return None
    if rc < 0:
        return None
    return rc != _TIME_ERROR


def sntp_offset(server: str, timeout: float = 3.0) -> float:
    """The offset of this clock from ``server`` (``host`` or ``host:port``, UDP 123), by one SNTP exchange
    (RFC 4330): positive when this clock is ahead. ``OSError`` when the server does not answer."""
    host, port = server.split(":") if server.count(":") == 1 else (server, "123")
    packet = b"\x23" + b"\0" * 47  # LI 0, version 4, mode 3 (client)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        t1 = time.time()
        sock.sendto(packet, (host, int(port)))
        data, _ = sock.recvfrom(512)
        t4 = time.time()
    if len(data) < 48:
        raise OSError(f"{server} sent a short answer")
    rx_s, rx_f, tx_s, tx_f = struct.unpack("!IIII", data[32:48])
    if tx_s == 0:
        raise OSError(f"{server} is not synchronised itself (kiss-o'-death or no time)")
    t2 = rx_s - _NTP_EPOCH + rx_f / 2**32
    t3 = tx_s - _NTP_EPOCH + tx_f / 2**32
    return float(((t1 - t2) + (t4 - t3)) / 2)


def max_skew(env: Mapping[str, str] | None = None) -> float:
    env = os.environ if env is None else env
    try:
        return float(env.get(MAX_SKEW_ENV) or DEFAULT_MAX_SKEW_S)
    except ValueError:
        return DEFAULT_MAX_SKEW_S


def clock_state(env: Mapping[str, str] | None = None) -> ClockState:
    """The kernel's NTP state and, when ``TB_NTP_SERVER`` is set, the offset from the site's time server."""
    env = os.environ if env is None else env
    server = (env.get(NTP_SERVER_ENV) or "").strip() or None
    offset: float | None = None
    error: str | None = None
    if server:
        try:
            offset = sntp_offset(server)
        except (OSError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
    return ClockState(kernel_clock_synced(), offset, server, error)
