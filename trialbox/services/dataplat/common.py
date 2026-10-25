"""Shared helpers of the data platform: injected clocks, content-derived ids, write-once files, key derivation."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from tb_common.timeutil import now as tz_now

Clock = Callable[[], datetime]

# namespace of the deterministic OpenLineage run ids (uuid5)
RUN_NAMESPACE = uuid.UUID("5b0f6a3e-9d2c-4f61-a1d7-1f3e2c4b5a60")


def utc_now() -> datetime:
    """Default clock: the current time in UTC (§5 conventions: manifests are UTC)."""
    return tz_now("UTC").astimezone(UTC)


def fixed_clock(at: datetime) -> Clock:
    """A clock that always returns ``at`` (tests, reproducible runs)."""
    if at.tzinfo is None:
        raise ValueError("naive datetime")
    return lambda: at


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def stable_id(prefix: str, *parts: object) -> str:
    """A content-derived id: ``<prefix>_<24 hex>`` of the canonical JSON of ``parts`` (no clock, no randomness)."""
    return f"{prefix}_{sha256_hex(canonical([str(p) for p in parts]).encode('utf-8'))[:24]}"


def run_uuid(*parts: object) -> str:
    """Deterministic OpenLineage ``runId`` (a UUID, as the spec requires)."""
    return str(uuid.uuid5(RUN_NAMESPACE, canonical([str(p) for p in parts])))


def hkdf(root: bytes, salt: str, info: str, length: int = 32) -> bytes:
    """``HKDF-SHA-256(root, salt, info)`` (§7.5 key hierarchy)."""
    if len(root) < 16:
        raise ValueError("root key must be at least 16 bytes")
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt.encode("utf-8"), info=info.encode("utf-8")).derive(
        root
    )


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_once(path: Path, data: bytes) -> None:
    """Create ``path`` with ``data`` and make it read-only. An existing file is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    path.chmod(0o444)


def write_json(path: Path, obj: Any) -> None:
    write_atomic(path, (canonical(obj) + "\n").encode("utf-8"))


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
