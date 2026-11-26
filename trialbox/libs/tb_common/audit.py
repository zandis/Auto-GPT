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
``audit.anchored`` event; a chain that holds a signed head is not (R22-36: its anchor existed, so its loss may hide
removed events), and ``verify`` fails an adoption that follows a signed head until a person has re-anchored. The
anchor is not keyed; the signed heads below are (T-211a).

**The anchor is held to the signed heads on the box** (R22-36). The writer and ``verify`` read the anchor folders this
process is given (``TB_AUDIT_ANCHOR_TARGETS``): the chain must still hold the event of every signed head there, with
its hash, whatever ``HEAD.json`` says. So a chain cut below a signed head is refused even when the head anchor was
written again to match the cut, and a chain with no head anchor is never adopted while a folder holds a signed head.
What this does not cover: the events after the newest signed head (a cut there with a rewritten ``HEAD.json`` passes
until a head kept off the box says otherwise, so sign often and keep the folder off the box), a process that can also
write the anchor folders, and a writer that is not given the folders (the nightly ``trialbox audit-sign`` checks there).

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

**No chart number in clear** (D-272, register CR-016): writers pass request lines, subjects and options through
:func:`mask_ids` / :func:`mask_detail`; the console pages use the same functions, so the page mask and the stored form
are one rule.
"""

from __future__ import annotations

import base64
import contextlib
import ctypes
import fcntl
import hashlib
import json
import os
import re
import socket
import struct
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

GENESIS = "0" * 64


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


def _last_line(path: Path) -> str | None:
    with path.open("rb") as fh:
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
    rec = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rec, dict) or not isinstance(rec.get("lines"), int) or not isinstance(rec.get("hash"), str):
        raise ValueError(f"{path} is not a head anchor")
    return rec


def write_head(directory: Path, lines: int, last_hash: str, file: str | None) -> dict[str, Any]:
    """Replace the head anchor atomically (write, fsync, rename, fsync the folder)."""
    rec = {"file": file, "hash": last_hash, "lines": lines}
    tmp = directory / f".{HEAD}.tmp"
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(canonical(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, directory / HEAD)
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return rec


def _count_lines(files: list[Path]) -> int:
    n = 0
    for path in files:
        with path.open("rb") as fh:
            n += sum(1 for raw in fh if raw.strip())
    return n


def _hash_at(files: list[Path], lines: int, n: int) -> str | None:
    """The hash of event ``n`` of a chain of ``lines`` events, read back from its end; None when it is not there."""
    if n == 0:
        return GENESIS
    back = lines - n
    if back < 0:
        return None
    for path in reversed(files):
        for raw in lines_backward(path):
            if not raw.strip():
                continue
            if back:
                back -= 1
                continue
            try:
                return str(json.loads(raw)["hash"])
            except (ValueError, KeyError, TypeError):
                return None
    return None


_NEWEST: dict[str, tuple[int, tuple[int, str, str] | None]] = {}  # heads folder -> (its mtime, its newest head)
_HELD: dict[str, tuple[int, str, int, str]] = {}  # audit folder -> (signed event, its hash, chain length, chain end)


def _newest_in(folder: Path) -> tuple[int, str, str] | None:
    """The signed head over the most events in one ``heads`` folder: ``(event, hash, file)``. Read again only when
    the folder changed. A file that is not a head record is passed over here (``verify`` with heads reports it)."""
    try:
        stamp = folder.stat().st_mtime_ns
    except OSError:
        return None
    seen = _NEWEST.get(str(folder))
    if seen is not None and seen[0] == stamp:
        return seen[1]
    found: tuple[int, str, str] | None = None
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stem.rsplit("-", 1)[-1], reverse=True):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and isinstance(rec.get("lines"), int) and isinstance(rec.get("hash"), str):
            if found is None or rec["lines"] > found[0]:
                found = (int(rec["lines"]), str(rec["hash"]), str(path))
            if path.stem.rsplit("-", 1)[-1].isdigit():
                break  # the names carry the event number: the first well-formed one is the newest
    if len(_NEWEST) > 64:
        _NEWEST.clear()
    _NEWEST[str(folder)] = (stamp, found)
    return found


def newest_box_head(env: Mapping[str, str] | None = None) -> tuple[int, str, str] | None:
    """R22-36: the signed head over the most events in the anchor folders this process is given, or None."""
    best: tuple[int, str, str] | None = None
    for target in anchor_targets(env):
        got = _newest_in(target / _HEADS_DIR)
        if got is not None and (best is None or got[0] > best[0]):
            best = got
    return best


def box_heads(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """R22-36: every well-formed signed head in the anchor folders this process is given."""
    out: list[dict[str, Any]] = []
    for target in anchor_targets(env):
        if (target / _HEADS_DIR).is_dir():
            out += [h for h in read_signed_heads(target)
                    if isinstance(h.get("lines"), int) and isinstance(h.get("hash"), str)]  # fmt: skip
    return out


FIRST_SIGNING_MAX = timedelta(hours=48)  # M4: a chain this long with no earlier signing is looked at
RUNBOOK_WAITS = 'docs/runbook/05-updates-backup-restore-secrets.md, "The audit chain waits for a person"'


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
        lock_path = self.directory / ".lock"
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _check_space(self) -> None:
        need = int(os.environ.get("TB_AUDIT_MIN_FREE_MB", "64")) * 1024 * 1024
        st = os.statvfs(self.directory)
        if st.f_bavail * st.f_frsize < need:
            raise AuditFull(f"audit volume has less than {need // (1024 * 1024)} MB free: free disk space first")

    def _repair_torn(self, files: list[Path]) -> dict[str, Any] | None:
        """Cut a torn or unreadable last line off the newest file; return what was moved, or None."""
        if not files:
            return None
        path = files[-1]
        # T-697 (F-12): only the file's tail is read (each append did read the whole day file: quadratic over a day
        # of a million events, and a day file larger than the writer's memory cap would have killed it)
        with path.open("rb") as fh:
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
            while (dest := path.with_name(f"{path.name}.torn-{n}")).exists():
                n += 1
            digest = hashlib.sha256()
            fh.seek(cut)
            with dest.open("wb") as out:  # the torn bytes kept as evidence, copied in steps
                while block := fh.read(_TAIL_STEP):
                    digest.update(block)
                    out.write(block)
        with path.open("r+b") as fh:
            fh.truncate(cut)
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
        with path.open("a", encoding="utf-8") as fh:
            fh.write(canonical(body) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        # the line first, then the anchor: a crash in between leaves the chain one line past the anchor, chained
        # to it, which the next writer and verify accept; never an anchor past the chain
        write_head(self.directory, lines + 1, body["hash"], path.name)
        return _day_files(self.directory)

    def _prev_hash(self, files: list[Path]) -> str:
        for path in reversed(files):
            last = _last_line(path)
            if last:
                return str(json.loads(last)["hash"])
        return GENESIS

    def _last_record(self, files: list[Path]) -> dict[str, Any] | None:
        for path in reversed(files):
            last = _last_line(path)
            if last:
                return dict(json.loads(last))
        return None

    def _anchor(self, files: list[Path]) -> tuple[int | None, str]:
        """The number of events in the chain by the head anchor, and the last hash; None when there is no anchor
        (a chain made before D-272). Raises :class:`AuditAnchorBroken` when the chain and the anchor are apart."""
        chain_hash = self._prev_hash(files)
        try:
            head = read_head(self.directory)
        except (ValueError, UnicodeDecodeError) as exc:
            raise AuditAnchorBroken(f"the audit head anchor cannot be read ({exc}): run tools/audit_verify.py") from exc
        newest = newest_box_head()
        if head is None:
            if newest is not None and newest[0] > 0:
                # R22-36: the anchor folder says this chain was signed at an event; a chain with no head anchor (cut
                # at or below the signed head with the anchor removed, or emptied) is never adopted by a write
                raise AuditAnchorBroken(
                    f"the audit chain has no head anchor, but {newest[2]} is a signed head of it (event {newest[0]}): "
                    "events may have been removed with the anchor. Nothing is written until a person has looked "
                    f"(tools/audit_verify.py --heads, then --reanchor; {RUNBOOK_WAITS})"
                )
            if chain_hash == GENESIS:
                return 0, chain_hash
            # R22-36: a chain that holds a signed head always had its anchor; without it, the events after the last
            # signed head may have been removed with it. Adopted only by a person (--reanchor), never by a write
            for path in reversed(files):
                for raw in lines_backward(path):
                    if f'"event":"{SIGNED_EVENT}"'.encode() not in raw:
                        continue
                    try:
                        signed = json.loads(raw).get("event") == SIGNED_EVENT
                    except (ValueError, AttributeError):
                        signed = False
                    if signed:
                        raise AuditAnchorBroken(
                            f"the audit chain has no head anchor, but it holds a signed head ({SIGNED_EVENT}): events "
                            "after it may have been removed with the anchor. Nothing is written until a person has "
                            f"looked (tools/audit_verify.py --heads, then --reanchor; {RUNBOOK_WAITS})"
                        )
            return None, chain_hash
        if head["hash"] == chain_hash:
            lines = int(head["lines"])
        else:
            last = self._last_record(files)
            if last is None or last.get("prev_hash") != head["hash"]:
                raise AuditAnchorBroken(
                    f"the audit chain ends at {chain_hash[:16]}, its head anchor says {head['hash'][:16]} after "
                    f"{head['lines']} events: events were dropped or rewritten. Nothing is written until a person has "
                    "looked (tools/audit_verify.py, then --reanchor)"
                )
            lines = int(head["lines"]) + 1  # the line was written, the anchor not yet (crash)
        if newest is not None:
            self._held_to(files, lines, chain_hash, newest)
        return lines, chain_hash

    def _held_to(self, files: list[Path], lines: int, chain_hash: str, newest: tuple[int, str, str]) -> None:
        """R22-36: the newest signed head on the box must be this chain's end or an event before it, whatever the
        head anchor says (the anchor is not keyed; whoever cut the chain can write it again). What was shown once is
        kept, so the next write reads back only the events written since."""
        n, signed_hash, where = newest
        key = str(self.directory)
        held = _HELD.get(key)
        if held is not None and held[:2] == (n, signed_hash) and _hash_at(files, lines, held[2]) == held[3]:
            _HELD[key] = (n, signed_hash, lines, chain_hash)
            return
        _HELD.pop(key, None)
        if n > lines:
            raise AuditAnchorBroken(
                f"the audit chain has {lines} events, but {where} is a signed head over event {n}: events were "
                "removed after it was signed, and the head anchor was written to match. Nothing is written until a "
                f"person has looked (tools/audit_verify.py --heads; {RUNBOOK_WAITS})"
            )
        if _hash_at(files, lines, n) != signed_hash:
            raise AuditAnchorBroken(
                f"event {n} of the audit chain does not have the hash of the signed head {where}: the chain was cut "
                "below it or rewritten, and the head anchor was written to match. Nothing is written until a person "
                f"has looked (tools/audit_verify.py --heads; {RUNBOOK_WAITS})"
            )
        if len(_HELD) > 64:
            _HELD.clear()
        _HELD[key] = (n, signed_hash, lines, chain_hash)

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
            files = _day_files(self.directory)
            repaired = self._repair_torn(files)
            if repaired:
                files = _day_files(self.directory)
            lines, chain_hash = self._anchor(files)
            if lines is None:  # a chain from before the anchor: adopt it, visibly
                lines = _count_lines(files)
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
            files = _day_files(self.directory)
            try:
                before = read_head(self.directory)
            except (ValueError, UnicodeDecodeError):
                before = {"unreadable": True}
            lines = _count_lines(files)
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
    #: M4: the chain's own ``audit.head_signed`` events as (lines, head hash, anchor folders that took it, what
    #: ``failed`` says of those that did not), and the time of its first and last event, so that a head missing from the
    #: anchor or an anchor no event speaks of shows
    #: (OCR 1523-21) and the folders that took it (None: an event that does not name them)
    signed_events: list[tuple[int, str, int, tuple[str, ...], tuple[str, ...] | None]] = field(default_factory=list)
    first_ts: str | None = None
    last_ts: str | None = None

    def told(self, target: Path) -> list[tuple[int, str]]:
        """The heads (lines, hash) the chain says were written, without those ``target`` is named not to have taken
        (OCR 1523-4): by the signer (``<folder>: <why>``) or by the host before it (``sign_on_box``)."""
        missed = (f"{target}: ", f"the anchor folder {target} is not there")
        return [(n, h) for n, h, took, failed, to in self.signed_events
                if took >= 1 and (str(target) in to if to is not None  # OCR 1523-21: the folders that took it
                                  else not any(f.startswith(missed) for f in failed))]  # fmt: skip


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
    # R22-36: with no heads given, the signed heads in the anchor folders this process sees are still held to (their
    # event and hash; the signatures are checked when ``signed_heads`` is given)
    on_box: list[dict[str, Any]] = box_heads() if signed_heads is None else []
    wanted: set[int] = {int(h["lines"]) for h in [*(signed_heads or ()), *on_box] if isinstance(h.get("lines"), int)}
    at: dict[int, str] = {0: GENESIS} if 0 in wanted else {}
    rotations: list[tuple[int, dict[str, Any]]] = []
    at_anchor: str | None = GENESIS if want == 0 else None
    last_prev: str | None = None
    signed_at = 0  # R22-36: the chain's last audit.head_signed event so far
    adopted: list[tuple[str, int, int]] = []  # audit.anchored events not yet looked at by a person: where, n, signed_at
    for path in _day_files(directory):
        res.files += 1
        with path.open(encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, start=1):
                ended = raw.endswith("\n")
                raw = raw.rstrip("\n")
                if not raw:
                    res.errors.append(f"{path.name}:{lineno}: empty line")
                    continue
                res.lines += 1
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as exc:
                    cut = "" if ended else "; the line has no end: a write that was cut short (power or disk), " \
                                           "not tampering"  # fmt: skip
                    res.errors.append(f"{path.name}:{lineno}: invalid JSON ({exc}){cut}")
                    prev = "?"
                    continue
                if canonical(rec) != raw:
                    res.errors.append(f"{path.name}:{lineno}: not canonical JSON")
                claimed = rec.pop("hash", None)
                res.first_ts = res.first_ts or rec.get("ts")
                res.last_ts = rec.get("ts", res.last_ts)
                if rec.get("event") == SIGNED_EVENT and isinstance(rec.get("detail"), dict):
                    d = rec["detail"]
                    if isinstance(d.get("lines"), int) and isinstance(d.get("head"), str):
                        failed = d.get("failed") if isinstance(d.get("failed"), list) else []
                        to = tuple(map(str, d["to"])) if isinstance(d.get("to"), list) else None
                        res.signed_events.append((d["lines"], d["head"], int(d.get("anchors") or 0),
                                                  tuple(map(str, failed)), to))  # fmt: skip
                if rec.get("prev_hash") != prev:
                    res.errors.append(f"{path.name}:{lineno}: prev_hash does not match previous line")
                expected = line_hash(str(rec.get("prev_hash")), rec)
                if claimed != expected:
                    res.errors.append(f"{path.name}:{lineno}: hash mismatch")
                if rec.get("event") in ("audit.anchored", "audit.reanchored"):
                    res.notes.append(f"{path.name}:{lineno}: {rec.get('event')} {canonical(rec.get('detail') or {})}")
                if rec.get("event") == SIGNED_EVENT:
                    signed_at = res.lines
                elif rec.get("event") == "audit.anchored":
                    adopted.append((f"{path.name}:{lineno}", res.lines, signed_at))
                elif rec.get("event") == "audit.reanchored":
                    adopted.clear()  # a person has looked (tools/audit_verify.py --reanchor)
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
    for place, n, signed_before in adopted:
        # R22-36: adopting a chain without its anchor is for a chain from before D-272; after a signed head (the
        # chain's own event, or one in an anchor folder) the anchor existed, and its loss is what a removal looks like
        earlier = max([signed_before, *(k for k in wanted if k < n)])
        if signed_before or any(k < n for k in wanted):
            res.errors.append(
                f"{place}: audit.anchored after a signed head (event {earlier}): the head anchor was missing, so "
                "events after the signed head may have been removed with it; a person must look "
                f"(tools/audit_verify.py --heads, then --reanchor; {RUNBOOK_WAITS})"
            )
    for h in sorted(on_box, key=lambda h: int(h["lines"]), reverse=True):
        n = int(h["lines"])
        if n > res.lines:
            why = f"the chain has only {res.lines} events: events were removed after it was signed"
        elif at.get(n) != h["hash"]:
            why = f"event {n} does not have its hash: the chain was cut below it or rewritten"
        else:
            continue
        res.errors.append(f"signed head on the box (event {n}): {why}, whatever the head anchor says "
                          f"(tools/audit_verify.py --heads; {RUNBOOK_WAITS})")  # fmt: skip
        break  # the newest one that fails says it; --heads lists every one
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


def waits_for_a_person(directory: Path) -> str | None:
    """R22-36: why this chain waits for a person, or None. Two states: a writer before R22-36 adopted the chain
    without its head anchor after a signed head (``audit.anchored``; the way out is ``--reanchor``), or the chain no
    longer holds a signed head that an anchor folder holds. Until then nothing is signed or archived."""
    marks = ("audit.anchored after a signed head", "signed head on the box")
    for err in verify(directory, require_head=False).errors:
        if any(m in err for m in marks):
            return err
    return None


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
    have = {(h.get("lines"), h.get("hash")) for h in heads}
    if written := [e for e in res.signed_events if e[2] >= 1]:
        # M4: the newest head the chain says a folder took must be there; older ones may be pruned
        n, last_hash = max(written, key=lambda e: e[0])[:2]
        if (n, last_hash) not in have:
            res.errors.append(f"signed heads: the newest head the chain records as written (event {n}) is not in the "
                              "folder(s) checked: it was deleted, or the folder was replaced")  # fmt: skip
    if covered:
        res.notes.append(
            f"signed heads: events 1 to {covered} are covered by a valid signature; "
            f"{res.lines - covered} after it are not yet"
        )


def _ts(value: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def anchor_targets(env: Mapping[str, str] | None = None) -> list[Path]:
    """The off-box anchor folders: ``TB_AUDIT_ANCHOR_TARGETS``, paths separated by ``os.pathsep``."""
    env = os.environ if env is None else env
    return [Path(p) for p in (env.get(ANCHOR_TARGETS_ENV) or "").split(os.pathsep) if p.strip()]


def _write_once(path: Path, data: bytes) -> bool:
    """Write ``data`` to a new file; False when the file is already there with the same bytes. A different file of
    the same name is never replaced (:class:`AuditSignError`). M4: the bytes go to a temporary name first and are
    renamed into place, so a kill while writing leaves no half head under the real name, and the copy is read back:
    one that differs is removed and refused, so the next night writes it again."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == data:
            return False
        raise AuditSignError(f"{path} is already there with other content: it is never replaced")
    # OCR 1523-8: a leftover of a killed night is removed; a link planted there by another machine is never followed
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644), "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    with contextlib.suppress(OSError):  # the name too (a share may not let a folder be synced)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    if path.read_bytes() != data:
        path.unlink(missing_ok=True)
        raise AuditSignError(f"the copy in {path} differs from what was written (read back): it was removed and "
                             "will be written again at the next signing")  # fmt: skip
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
    files = _day_files(log.directory)
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


# ---------------------------------------------------------------------------------------------- the anchor's state (M4)
ANCHOR_STATES = ("ok", "missing", "stale", "restored", "tampered")


def _scan(directory: Path, wanted: set[int]) -> tuple[int, dict[int, str], int | None, str | None]:
    """Lines of the chain, the hash at each wanted line, and where a ``backup.restored`` event first stands (its
    line number, and the time of the event before it). Reads the chain; verifies nothing (``verify`` does)."""
    n, at, restored, before, ts = 0, {0: GENESIS}, None, None, None
    for path in _day_files(directory):
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except ValueError:
                    rec = {}
                n += 1
                if restored is None and rec.get("event") == "backup.restored":
                    restored, before = n, ts
                ts = rec.get("ts", ts)
                if n in wanted:
                    at[n] = str(rec.get("hash"))
    return n, at, restored, before


def anchor_state(target: Path, audit_dir: Path, own: Mapping[str, bytes] | None, now: datetime,
                 limit_h: float = 36.0) -> tuple[str, str]:  # fmt: skip
    """One anchor folder against the chain: ``(state, sentence)``, state one of :data:`ANCHOR_STATES`.

    missing: the folder is not reachable, is on the audit volume (it protects nothing) or holds no head yet.
    tampered: a head that no key of this box signed, a head whose signature fails, or a chain that has no event the
    head names, or another hash there (named by the day the head was signed), or a folder emptied of every head the
    chain records as written to it. restored: the chain is a shorter
    copy that a ``backup.restored`` event closes, and every head it disagrees with is later than that event.
    stale: the newest head is older than ``limit_h``. ok: the chain holds every head and the newest is fresh.
    ``own`` None: this python3 has no crypto library, so the signatures are not checked here (said in the sentence;
    the nightly signer checks them)."""
    if not target.is_dir():
        return "missing", f"the anchor folder {target} is not reachable (not mounted?)"
    if _inside(target, audit_dir):
        return "missing", f"the anchor folder {target} is on the audit volume: it protects nothing"
    heads = read_signed_heads(target) if (target / _HEADS_DIR).is_dir() else []
    told = verify(audit_dir, require_head=False).told(target) if audit_dir.is_dir() else []  # what the chain says
    if not heads and told:  # OCR 1523-17: every head the chain names deleted is tampering, as one deleted head is
        return "tampered", (
            f"{target} holds no signed head, but the chain records {len(told)} written to it: "
            "emptied, replaced or not mounted; nothing is signed over it until a person looks"
        )
    if not heads:
        return "missing", f"no signed head in {target} yet (python3 -m tools.trialbox audit-sign)"
    for h in heads:
        day = str(h.get("ts") or "?")[:10]
        if own is None:  # no crypto library here: the record's form only
            if not (isinstance(h.get("lines"), int) and isinstance(h.get("hash"), str) and _ts(h.get("ts"))):
                return "tampered", f"a head in {target}/heads (day {day}) is not a {HEAD_FORMAT} record"
            continue
        pub = own.get(str(h.get("key_id")))
        if pub is None:
            return "tampered", (f"a head in {target}/heads (day {day}) is not signed by this box's audit key "
                                f"(key id {h.get('key_id')}): not a valid head")  # fmt: skip
        if (why := signed_head_problem(h, pub)) is not None:
            return "tampered", (f"the head of {day} in {target}/heads is not valid ({why}): it does not hold as "
                                "signed by this box's key")  # fmt: skip
    held = {(h.get("lines"), h.get("hash")) for h in heads}
    # OCR 1523-4: from the folder's own first head on. One before it was signed before the folder was set up, or pruned;
    # the newer heads cover the events it covered (_check_signed_heads)
    first_line = min(int(h["lines"]) for h in heads)
    if lost := [e for e in told if e[0] >= first_line and e not in held]:
        return "tampered", (f"the head of event {max(lost)[0]}, which the chain records as written, is not in "
                           f"{target}: it was deleted, or the folder was replaced")  # fmt: skip
    n, at, restored, before = _scan(audit_dir, {int(h["lines"]) for h in heads})
    off = [h for h in heads if int(h["lines"]) > n or at.get(int(h["lines"])) != h["hash"]]
    if off:
        first = min(off, key=lambda h: str(h["ts"]))
        if restored is not None and all(int(h["lines"]) >= restored for h in off):
            return "restored", (f"the audit trail was restored to {str(before or '?')[:19]} (a backup): "
                                f"{len(off)} head(s) in {target} are later than it; a person confirms once "
                                "(tools/audit_verify.py --heads, then --reanchor)")  # fmt: skip
        return "tampered", (f"the audit trail does not agree with the head signed on {str(first['ts'])[:10]} in "
                            f"{target} (event {first['lines']}; the trail has {n} events): events were removed or "
                            "rewritten; nothing was deleted, a person with the audit role looks")  # fmt: skip
    newest = max(datetime.fromisoformat(str(h["ts"])) for h in heads)
    newest = newest if newest.tzinfo else newest.replace(tzinfo=UTC)
    age = (now - newest).total_seconds() / 3600
    if abs(age) > limit_h:
        return "stale", (f"the newest signed head in {target} is {age:.0f} h old (limit {limit_h:g} h): the nightly "
                         "audit-sign did not run or did not reach the folder")  # fmt: skip
    said = "" if own is not None else " (signatures not checked: this python3 has no crypto library)"
    return "ok", f"{target}: newest signed head {age:.0f} h old{said}"
