"""Object storage (MinIO in deployment, local filesystem in tests). Keys are ``<bucket>/<path>``."""

from __future__ import annotations

import io
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


class MinioStore:
    """MinIO-backed store; buckets are created on first use."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool = False) -> None:
        from minio import Minio

        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._known: set[str] = set()

    def _bucket(self, bucket: str) -> str:
        if bucket not in self._known:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
            self._known.add(bucket)
        return bucket

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        bucket, name = _split(key)
        self.client.put_object(self._bucket(bucket), name, io.BytesIO(data), len(data), content_type=content_type)

    def get(self, key: str) -> bytes:
        from minio.error import S3Error

        bucket, name = _split(key)
        try:
            resp = self.client.get_object(self._bucket(bucket), name)
        except S3Error as exc:
            raise KeyError(key) from exc
        try:
            return bytes(resp.read())
        finally:
            resp.close()
            resp.release_conn()

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        bucket, name = _split(key)
        try:
            self.client.stat_object(self._bucket(bucket), name)
        except S3Error:
            return False
        return True

    def delete(self, key: str) -> None:
        bucket, name = _split(key)
        self.client.remove_object(self._bucket(bucket), name)

    def list(self, prefix: str) -> list[ObjectInfo]:
        bucket, _, rest = prefix.lstrip("/").partition("/")
        out: list[ObjectInfo] = []
        for obj in self.client.list_objects(self._bucket(bucket), prefix=rest, recursive=True):
            out.append(
                ObjectInfo(f"{bucket}/{obj.object_name}", int(obj.size or 0), obj.last_modified or datetime.now(UTC))
            )
        return out

    def ping(self) -> bool:
        self.client.list_buckets()
        return True


def from_env(
    object_store: str,
    minio_endpoint: str = "",
    access_key: str = "",
    secret_key: str = "",
    secure: bool = False,
    data_dir: str = "/data",
) -> ObjectStore:
    """``object_store`` is ``minio`` or ``fs:<path>`` (``fs`` alone means ``<data_dir>/objects``)."""
    if object_store == "minio":
        return MinioStore(minio_endpoint, access_key, secret_key, secure)
    if object_store.startswith("fs"):
        _, _, path = object_store.partition(":")
        return FsStore(Path(path) if path else Path(data_dir) / "objects")
    raise ValueError(f"unknown TB_OBJECT_STORE {object_store!r}")
