"""Object storage on the box's filesystem (ADR-16; MinIO removed in D-121). Keys are ``<bucket>/<path>``.

**Sealed at rest (T-210c, CR-041 last third, D-354).** Uploads, chart uploads and mailed attachments
(``attachments/``), job outputs, the ``phi`` spreadsheets and sheets among them (``outputs/``), and TWPAS bundles
(``twpas/``) hold patient data. Once the store is sealed (``python -m tools.keys seal-objects``), every object of those
buckets is written as ``MAGIC + nonce + AES-256-GCM(objects.key, data)``. The associated data binds the object key,
so a file moved to another key is refused. ``objects.key`` lives wrapped under the site KEK in the secrets folder
(``tb_common.kek``, D-347); no plaintext of a sealed bucket touches the disk, not even the temporary file.

The seal file ``<root>/.sealed.json`` (on the shared objects volume, so every service sees it) names the object key's
fingerprint. With the seal file present a service that cannot open ``objects.key`` (no secrets folder, KEK not
unsealed, another key) fails closed: it neither writes plaintext nor reads. Reads tell sealed from plain objects by
the magic, so objects written before the seal still read until ``seal-objects`` converts them. Without a seal file
(demo, tests, a box before T-210c) the store is plain, as before.
"""

from __future__ import annotations

import hmac
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from tb_common import kek as K

BUCKETS = ("attachments", "outputs", "rulesets", "lake", "twpas")
#: the buckets that hold patient data and are sealed under ``objects.key`` (T-210c)
SEALED_BUCKETS = ("attachments", "outputs", "twpas")
SEAL_FILE = ".sealed.json"
SEAL_FORMAT = "tb-objects-sealed/1"
OBJECT_KEY = "objects.key"
MAGIC = b"TBSEAL1\x00"


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


class SealError(K.KekError):
    """A sealed object cannot be written or read safely: no object key here, another key, a damaged or moved file."""


def _aad(key: str) -> bytes:
    bucket, name = _split(key)
    return MAGIC + f"{bucket}/{name}".encode()


def is_sealed_blob(data: bytes) -> bool:
    return data[: len(MAGIC)] == MAGIC


def read_seal(root: Path) -> dict[str, Any] | None:
    """The seal file of the store at ``root``, or None when the store is plain."""
    path = root / SEAL_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise SealError(f"{path} cannot be read ({type(exc).__name__}): the store is treated as sealed") from None
    if not isinstance(doc, dict) or doc.get("format") != SEAL_FORMAT or not isinstance(doc.get("fingerprint"), str):
        raise SealError(f"{path} is not a {SEAL_FORMAT} file: the store is treated as sealed")
    return doc


def load_object_key(secrets_dir: Path | None, seal: Mapping[str, Any], env: Mapping[str, str] | None = None) -> bytes:
    """``objects.key``, opened under the KEK and checked against the seal file. Never made here, never plain."""
    if secrets_dir is None:
        raise SealError("the object store is sealed and this service has no secrets folder (TB_SECRETS_DIR)")
    path = secrets_dir / OBJECT_KEY
    if path.exists():
        raise SealError(f"{path} is plain: the object key is only kept wrapped under the KEK")
    if not K.wrapped_path(path).exists():
        raise SealError(f"the object store is sealed and {path}{K.WRAPPED_SUFFIX} is not here")
    dek = K.load_key_file(path, env)
    if len(dek) != 32 or not hmac.compare_digest(K.fingerprint(dek), str(seal["fingerprint"])):
        raise SealError(f"{path.name} is not the key the store was sealed with ({seal['fingerprint']})")
    return dek


def seal_bytes(dek: bytes, key: str, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(dek).encrypt(nonce, data, _aad(key))


def open_bytes(dek: bytes, key: str, blob: bytes) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    body = blob[len(MAGIC) :]
    try:
        return AESGCM(dek).decrypt(body[:12], body[12:], _aad(key))
    except (InvalidTag, ValueError):
        raise SealError(f"the sealed object {key} does not open: damaged, or moved from another key") from None


class FsStore:
    """Filesystem-backed store rooted at ``root``. ``secrets_dir`` (and ``env``, for the KEK) open the object key
    when the store is sealed (see the module text); a plain store never needs them."""

    def __init__(self, root: Path, secrets_dir: Path | None = None, env: Mapping[str, str] | None = None) -> None:
        self.root = root
        self.secrets_dir = secrets_dir
        self.env = env
        self._dek: tuple[str, bytes] | None = None  # (fingerprint, key) once opened
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        bucket, name = _split(key)
        return self.root / bucket / name

    def _key(self, seal: Mapping[str, Any]) -> bytes:
        fp = str(seal["fingerprint"])
        if self._dek is None or self._dek[0] != fp:
            self._dek = (fp, load_object_key(self.secrets_dir, seal, self.env))
        return self._dek[1]

    def sealed(self) -> bool:
        return read_seal(self.root) is not None

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        if _split(key)[0] in SEALED_BUCKETS:
            seal = read_seal(self.root)
            if seal is not None:
                data = seal_bytes(self._key(seal), key, data)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        # durable before put returns: a job's done is durable at the database's commit, so its outputs must be on
        # disk by then (a power cut after a screening left a done job with no list; deep review 2026-11-13)
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
        fd = os.open(p.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def get(self, key: str) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise KeyError(key)
        data = p.read_bytes()
        if not is_sealed_blob(data):
            return data  # a plain store, or an object written before the seal (seal-objects converts it)
        seal = read_seal(self.root)
        if seal is None:
            raise SealError(f"{key} is sealed but the store has no {SEAL_FILE}: put the seal file back from the backup")
        return open_bytes(self._key(seal), key, data)

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


def from_env(object_store: str, data_dir: str = "/data", secrets_dir: str | None = None) -> FsStore:
    """``object_store`` is ``fs:<path>`` (``fs`` alone means ``<data_dir>/objects``). ``minio`` was removed in
    D-121: a shared volume mounted at the same path in each service replaces it. ``secrets_dir`` opens the object
    key of a sealed store (T-210c)."""
    if object_store == "minio":
        raise ValueError("TB_OBJECT_STORE=minio was removed (D-121); use fs:/data/objects")
    if object_store.startswith("fs"):
        _, _, path = object_store.partition(":")
        return FsStore(Path(path) if path else Path(data_dir) / "objects", Path(secrets_dir) if secrets_dir else None)
    raise ValueError(f"unknown TB_OBJECT_STORE {object_store!r}")


def from_config() -> ObjectStore:
    """Object store configured by the environment (``TB_OBJECT_STORE``; ``TB_SECRETS_DIR`` for a sealed store)."""
    from tb_common.config import load_env

    env = load_env()
    return from_env(env.object_store, env.data_dir, env.secrets_dir)


# ------------------------------------------------------------------------------------------------ sealing (T-210c)


@dataclass
class SealReport:
    fingerprint: str
    key_made: bool
    converted: int
    already: int


def plain_objects(root: Path) -> list[Path]:
    """Files of the sealed buckets that are still plaintext (``.tmp`` left-overs included: they hold data too)."""
    out = []
    for bucket in SEALED_BUCKETS:
        base = root / bucket
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file() and not p.is_symlink():
                    with p.open("rb") as fh:
                        if not is_sealed_blob(fh.read(len(MAGIC))):
                            out.append(p)
    return out


def seal_store(root: Path, secrets_dir: Path, env: Mapping[str, str] | None = None) -> SealReport:
    """Seal the store at ``root``: make ``objects.key`` wrapped under the KEK when there is none (the folder must
    have a KEK, unsealed), write the seal file (from then on every service writes sealed objects), then convert every
    plain object of the sealed buckets in place (sealed copy beside it, checked, then renamed over it). Run again
    after an interruption: it finishes the conversion and changes nothing else."""
    if K.read_meta(secrets_dir) is None:
        raise SealError(f"{secrets_dir} has no KEK ({K.META_FILE}): run `python -m tools.keys init` first")
    path = secrets_dir / OBJECT_KEY
    made = K.create_key_file(path, 32, env)  # wrapped, since the folder has a KEK; never replaces a key
    seal = read_seal(root)
    if seal is None:
        doc = K.read_wrapped(path)
        seal = {"format": SEAL_FORMAT, "key": OBJECT_KEY, "fingerprint": str(doc["fingerprint"]),
                "buckets": list(SEALED_BUCKETS)}  # fmt: skip
        root.mkdir(parents=True, exist_ok=True)
        K._write_private(root / SEAL_FILE, (json.dumps(seal, indent=1, sort_keys=True) + "\n").encode())
        os.chmod(root / SEAL_FILE, 0o644)  # every service reads it; it holds no secret
    dek = load_object_key(secrets_dir, seal, env)
    converted = 0
    for p in plain_objects(root):
        if p.name.endswith(".tmp"):
            p.unlink()  # an interrupted write's left-over: never an object (list() skips it)
            continue
        key = p.relative_to(root).as_posix()
        data = p.read_bytes()
        blob = seal_bytes(dek, key, data)
        if open_bytes(dek, key, blob) != data:
            raise SealError(f"{key}: the sealed copy does not open to the same bytes; left plain")
        tmp = p.with_name(f".{p.name}.seal.tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, p)
        converted += 1
    total = sum(1 for b in SEALED_BUCKETS if (root / b).is_dir() for f in (root / b).rglob("*") if f.is_file())
    return SealReport(str(seal["fingerprint"]), made, converted, total - converted)
