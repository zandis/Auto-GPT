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
``audit.anchored`` event. The anchor is not keyed: signed heads and one writer are task T-211 (register CR-042).

**No chart number in clear** (D-272, register CR-016): writers pass request lines, subjects and options through
:func:`mask_ids` / :func:`mask_detail`; the console pages use the same functions, so the page mask and the stored form
are one rule.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
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
        data = path.read_bytes()
        if not data:
            return None
        cut = len(data)
        if not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1  # keep every complete line
        else:
            last_start = data.rfind(b"\n", 0, len(data) - 1) + 1
            try:
                rec = json.loads(data[last_start:-1].decode("utf-8"))
                if not isinstance(rec, dict) or "hash" not in rec:
                    raise ValueError("no hash")
            except (ValueError, UnicodeDecodeError):
                cut = last_start  # a complete but unreadable last line: the same damage
        if cut == len(data):
            return None
        torn = data[cut:]
        n = 1
        while (dest := path.with_name(f"{path.name}.torn-{n}")).exists():
            n += 1
        dest.write_bytes(torn)
        with path.open("r+b") as fh:
            fh.truncate(cut)
            fh.flush()
            os.fsync(fh.fileno())
        return {"file": path.name, "bytes": len(torn), "sha256": hashlib.sha256(torn).hexdigest(), "kept_as": dest.name}

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


@dataclass
class VerifyResult:
    ok: bool
    files: int = 0
    lines: int = 0
    last_hash: str = GENESIS
    errors: list[str] = field(default_factory=list)
    head: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


def verify(directory: Path, *, anchor: dict[str, Any] | None = None, require_head: bool = True) -> VerifyResult:
    """Recompute the whole chain across all day files; report every broken link, and check the end of the chain
    against the head anchor (``HEAD.json``; required unless ``require_head`` is False, for a copy such as the
    archive) and, when given, against ``anchor`` (``{"lines": n, "hash": h}`` kept elsewhere: event ``n`` of the
    chain must have hash ``h``)."""
    res = VerifyResult(ok=True)
    prev = GENESIS
    want = int(anchor["lines"]) if anchor else -1
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
                last_prev = str(rec.get("prev_hash"))
                prev = str(claimed)
                if res.lines == want:
                    at_anchor = prev
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
    res.ok = not res.errors
    return res
