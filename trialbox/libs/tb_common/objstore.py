"""Object storage on the box's filesystem (ADR-16; MinIO removed in D-121). Keys are ``<bucket>/<path>``."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

BUCKETS = ("attachments", "outputs", "rulesets", "lake", "twpas")


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int
    last_modified: datetime


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str) -> list[ObjectInfo]: ...


def _split(key: str) -> tuple[str, str]:
    key = key.lstrip("/")
    bucket, _, name = key.partition("/")
    if not bucket or not name or ".." in key.split("/"):
        raise ValueError(f"invalid object key {key!r}")
    return bucket, name


class FsStore:
    """Filesystem-backed store rooted at ``root`` (used by tests and single-process dev runs)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        bucket, name = _split(key)
        return self.root / bucket / name

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise KeyError(key)
        return p.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def list(self, prefix: str) -> list[ObjectInfo]:
        bucket, _, rest = prefix.lstrip("/").partition("/")
        base = self.root / bucket
        out: list[ObjectInfo] = []
        if not base.exists():
            return out
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.name.endswith(".tmp"):
                rel = p.relative_to(base).as_posix()
                if rel.startswith(rest):
                    st = p.stat()
                    out.append(ObjectInfo(f"{bucket}/{rel}", st.st_size, datetime.fromtimestamp(st.st_mtime, UTC)))
        return out


def from_env(object_store: str, data_dir: str = "/data") -> ObjectStore:
    """``object_store`` is ``fs:<path>`` (``fs`` alone means ``<data_dir>/objects``). ``minio`` was removed in
    D-121: a shared volume mounted at the same path in each service replaces it."""
    if object_store == "minio":
        raise ValueError("TB_OBJECT_STORE=minio was removed (D-121); use fs:/data/objects")
    if object_store.startswith("fs"):
        _, _, path = object_store.partition(":")
        return FsStore(Path(path) if path else Path(data_dir) / "objects")
    raise ValueError(f"unknown TB_OBJECT_STORE {object_store!r}")


def from_config() -> ObjectStore:
    """Object store configured by the environment (``TB_OBJECT_STORE``)."""
    from tb_common.config import load_env

    env = load_env()
    return from_env(env.object_store, env.data_dir)
