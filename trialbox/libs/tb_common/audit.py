"""Append-only, hash-chained audit log (SPEC §10.2).

``audit/YYYY-MM-DD.jsonl``, one event per line::

    {ts, event, job_id, ruleset, ruleset_version, model, prompt_version, snapshot, actor,
     input_sha, output_sha, recipients, detail, prev_hash, hash}

``hash = sha256(prev_hash + canonical_json(line_without_hash))`` where canonical JSON has sorted keys, no
whitespace and UTF-8 text. The first line of a day file chains to the last hash of the previous day file;
the very first line of the log uses ``GENESIS`` (64 zeros). Writers serialise through ``flock`` on
``audit/.lock`` so several processes/containers sharing the volume keep one chain.
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
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.jsonl$")


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

    def _prev_hash(self) -> str:
        files = _day_files(self.directory)
        for path in reversed(files):
            last = _last_line(path)
            if last:
                return str(json.loads(last)["hash"])
        return GENESIS

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
        with self._locked():
            prev = self._prev_hash()
            body["prev_hash"] = prev
            body["hash"] = line_hash(prev, body)
            day = now.astimezone(self.zone).date().isoformat()
            path = self.directory / f"{day}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(canonical(body) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return body


@dataclass
class VerifyResult:
    ok: bool
    files: int = 0
    lines: int = 0
    last_hash: str = GENESIS
    errors: list[str] = field(default_factory=list)


def verify(directory: Path) -> VerifyResult:
    """Recompute the whole chain across all day files; report every broken link."""
    res = VerifyResult(ok=True)
    prev = GENESIS
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
                prev = str(claimed)
    res.last_hash = prev
    res.ok = not res.errors
    return res
