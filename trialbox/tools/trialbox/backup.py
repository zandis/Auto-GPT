"""``trialbox backup`` / ``trialbox restore`` (TB-PLAN-04 step 2, D-126): the whole box in one encrypted file.

    trialbox backup-keygen --private /media/usb/trialbox-backup.key --public deploy/secrets/backup.pub
    trialbox backup  --to /mnt/nas/trialbox --to /media/usb/trialbox [--keep 14]
    trialbox backup-verify <file> --key /media/usb/trialbox-backup.key
    trialbox restore <file> --key /media/usb/trialbox-backup.key --yes

What is in a backup (``*.tbbak``, layout 2, D-187): a ``pg_dump`` (custom format, compressed only by the backup's
zstd stream) of ``trialbox_wf`` (``TB_DB_URL``) without the rows of the schema ``refdata`` (the public reference
pack: load it again after a restore; the manifest lists the packs that were loaded) and, when ``TB_HAPI_DB_URL`` is
set, of ``hapi``; every directory of the layout (lake, objects, audit, rulesets, orchestrator files, mail, secrets),
where the lake keeps every Parquet and DuckDB file, the vector store and the site inputs, but the NDJSON only of
``CURRENT`` and of the two newest snapshots (a delta night merges over the newest older one), and never ``tmp/``
(spill) or a ``.building`` file; a manifest with the sha256 and size of every member, taken from the bytes as they
go into the tar (a file is read once, never a second time to hash it), what was left out and why, and the row count
and content hash of every table that was dumped with its rows.

**Encryption to the hospital's key.** The box holds only the public key (X25519). Each backup takes a fresh key pair,
derives an AES-256-GCM key with HKDF-SHA256 from the shared secret, and encrypts the tar stream in 1 MiB chunks. The
header is authenticated with every chunk, and the last chunk is marked, so truncation, reordering and edits are all
refused. Only the private key, kept by hospital IT in a sealed envelope (D-126), opens a backup. The box cannot read
its own backups, and Aimedics never holds the key.

**Targets.** Each ``--to`` is a directory: a mounted hospital NAS share, a USB disk, a second disk, or an off-site
mount. The file is written to the first (to ``.part``, fsync, rename) while the sha256 of the encrypted bytes is
taken; every other target gets a copy, hashed as it is written and then read back once from that target.
``<file>.sha256`` (``sha256sum -c`` format) beside each file marks it complete: ``trialbox backup-status`` counts a
backup as good only with it. The newest ``--keep`` are kept. The nightly schedule, the off-box rule and the age alert
are in ``tools/trialbox/backup_schedule.py``.

**Restore** checks every hash before touching anything, moves each directory aside (``<dir>.pre-restore-<time>``)
before writing it, and restores the databases with ``pg_restore --clean --if-exists``. Every older format restores:
layout 1 with gzip (before D-149) and layout 1 with zstd (D-149).

The database tools are ``pg_dump`` / ``pg_restore`` on the path, or the command in ``TB_PG_DUMP_CMD`` /
``TB_PG_RESTORE_CMD`` (on a box: ``docker compose --project-directory deploy exec -T db pg_dump``). Nothing here logs
or prints a row or a file's content: only names, counts, sizes and hashes.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import shlex
import shutil
import socket
import struct
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import zstandard
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# shared with the host-side schedule, which has only the standard library (re-exported: bk.prune, bk.read_sidecar ...)
from tools.trialbox import backup_schedule as _sched

EXCLUDE_DATA_SCHEMAS = _sched.EXCLUDE_DATA_SCHEMAS
SUFFIX = _sched.SUFFIX
prune = _sched.prune
read_sidecar = _sched.read_sidecar
sidecar = _sched.sidecar
stamp_of = _sched.stamp_of

MAGIC = b"TBBAK1\n"
LAYOUT = 2  # D-187: stream hashes, sizes, the lake and refdata rules. 1: every backup before (no key in the header)
ZSTD_LEVEL = 3  # D-149: 400-640 MB/s a core here, a better ratio than gzip -9 (dataflow review §0.2, §7.3)
CHUNK = 1 << 20
KEY_HEADER = "TRIALBOX BACKUP PRIVATE KEY"
# compose volumes on the box (deploy/docker-compose.yml): name -> host path; TB_BACKUP_DIRS overrides
VOLUME_ROOT = "/var/lib/docker/volumes/trialbox_{}/_data"
DEFAULT_DIRS = {
    "lake": "lake-data",
    "objects": "objects-data",
    "audit": "audit-data",
    "rulesets": "rulesets-data",
    "orchestrator": "orch-data",
    "mail": "mail-data",
    "secrets": "tb-secrets",
    "console": "console-data",  # as the update path's backup (update.ComposeBox) already takes it
}
# D-187: the rows of EXCLUDE_DATA_SCHEMAS ("refdata") of the trial database are not dumped (their tables are): the
# reference pack is public, several GB, and loaded again from the pack (tb_common.refdata). The nightly run's own
# pg_dump (backup_schedule) leaves out the same.
LAKE_SKIP_TOP = ("tmp",)  # DuckDB spill (lake.store temp_dir default)


class BackupError(RuntimeError):
    pass


class _HashReader:
    """A read-only file wrapper that hashes and counts every byte read through it (the stream hash)."""

    def __init__(self, fh: IO[bytes]) -> None:
        self._fh, self.sha, self.n = fh, hashlib.sha256(), 0

    def read(self, size: int = -1) -> bytes:
        b = self._fh.read(size)
        self.sha.update(b)
        self.n += len(b)
        return b


class _HashWriter(io.RawIOBase):
    """A write-only file wrapper that hashes every byte written through it (the encrypted file's sha256)."""

    def __init__(self, fh: IO[bytes]) -> None:
        self._fh, self.sha, self.n = fh, hashlib.sha256(), 0

    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int:
        data = bytes(b)
        self.sha.update(data)
        self.n += len(data)
        self._fh.write(data)
        return len(data)


# ------------------------------------------------------------------------------------------------ keys
def keygen(private_out: Path, public_out: Path) -> str:
    """Write the private key (for hospital IT) and the public key (for the box); return the key fingerprint."""
    sk = X25519PrivateKey.generate()
    raw = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pk = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    fp = fingerprint(pk)
    for p in (private_out, public_out):
        if p.exists():
            raise BackupError(f"{p} exists: a backup key is never overwritten")
        p.parent.mkdir(parents=True, exist_ok=True)
    words = base64.b32encode(raw).decode().rstrip("=")
    paper = " ".join(words[i : i + 4] for i in range(0, len(words), 4))
    private_out.write_text(
        f"-----BEGIN {KEY_HEADER}-----\n{paper}\nfingerprint {fp}\n-----END {KEY_HEADER}-----\n", encoding="utf-8"
    )
    os.chmod(private_out, 0o600)
    public_out.write_text(base64.b64encode(pk).decode() + "\n", encoding="utf-8")
    return fp


def fingerprint(pub: bytes) -> str:
    h = hashlib.sha256(pub).hexdigest()[:20]
    return "-".join(h[i : i + 4] for i in range(0, 20, 4))


def load_public(path: Path) -> X25519PublicKey:
    return X25519PublicKey.from_public_bytes(base64.b64decode(path.read_text(encoding="utf-8").strip()))


def load_private(path: Path) -> X25519PrivateKey:
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith(("-----", "fingerprint"))]
    b32 = "".join("".join(lines).split()).upper()
    b32 += "=" * (-len(b32) % 8)
    try:
        return X25519PrivateKey.from_private_bytes(base64.b32decode(b32))
    except Exception as e:  # binascii.Error, ValueError
        raise BackupError(f"{path} is not a TrialBox backup private key") from e


def _derive(shared: bytes, eph: bytes, recipient: bytes) -> bytes:
    return HKDF(hashes.SHA256(), 32, salt=eph + recipient, info=b"trialbox-backup-v1").derive(shared)


# ------------------------------------------------------------------------------------------------ encrypted stream
class _Encryptor(io.RawIOBase):
    """A write-only file: plaintext in, ``MAGIC | header | chunks`` out."""

    def __init__(self, out: Any, recipient: X25519PublicKey, meta: Mapping[str, Any]) -> None:
        eph = X25519PrivateKey.generate()
        eph_pub = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        rec_pub = recipient.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self._aead = AESGCM(_derive(eph.exchange(recipient), eph_pub, rec_pub))
        self._prefix = os.urandom(8)
        header = dict(meta)
        header.update(
            {"format": 1, "chunk": CHUNK, "eph": base64.b64encode(eph_pub).decode(),
             "recipient": fingerprint(rec_pub), "nonce_prefix": base64.b64encode(self._prefix).decode()}
        )  # fmt: skip
        self._hdr = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
        self._out = out
        out.write(MAGIC + struct.pack(">I", len(self._hdr)) + self._hdr)
        self._buf = bytearray()
        self._n = 0
        self.plain_sha = hashlib.sha256()

    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int:
        data = bytes(b)
        self.plain_sha.update(data)
        self._buf += data
        while len(self._buf) > CHUNK:  # keep one chunk back: the final one must carry the last flag
            self._seal(bytes(self._buf[:CHUNK]), last=False)
            del self._buf[:CHUNK]
        return len(data)

    def _seal(self, block: bytes, last: bool) -> None:
        nonce = self._prefix + struct.pack(">I", self._n)
        aad = self._hdr + struct.pack(">I?", self._n, last)
        ct = self._aead.encrypt(nonce, block, aad)
        self._out.write(struct.pack(">I?", len(ct), last) + ct)
        self._n += 1
        if self._n >= 2**32 - 1:
            raise BackupError("backup too large")

    def finish(self) -> None:
        self._seal(bytes(self._buf), last=True)
        self._buf.clear()


def read_header(f: Any) -> tuple[dict[str, Any], bytes]:
    if f.read(len(MAGIC)) != MAGIC:
        raise BackupError("not a TrialBox backup (bad magic)")
    (n,) = struct.unpack(">I", f.read(4))
    if n > 1 << 20:
        raise BackupError("header too large")
    raw = f.read(n)
    return json.loads(raw), raw


def decrypt_stream(f: Any, key: X25519PrivateKey) -> Iterator[bytes]:
    header, raw = read_header(f)
    eph = base64.b64decode(header["eph"])
    my_pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if fingerprint(my_pub) != header["recipient"]:
        raise BackupError(f"this backup was made for key {header['recipient']}, not {fingerprint(my_pub)}")
    aead = AESGCM(_derive(key.exchange(X25519PublicKey.from_public_bytes(eph)), eph, my_pub))
    prefix = base64.b64decode(header["nonce_prefix"])
    n, seen_last = 0, False
    while True:
        head = f.read(5)
        if not head:
            break
        if len(head) < 5 or seen_last:
            raise BackupError("backup is damaged (data after the last chunk or a cut chunk header)")
        size, last = struct.unpack(">I?", head)
        ct = f.read(size)
        if len(ct) != size:
            raise BackupError("backup is cut short")
        try:
            yield aead.decrypt(prefix + struct.pack(">I", n), ct, raw + struct.pack(">I?", n, last))
        except Exception as e:  # cryptography.exceptions.InvalidTag
            raise BackupError(f"backup is damaged or was changed (chunk {n} fails its check)") from e
        n += 1
        seen_last = last
    if not seen_last:
        raise BackupError("backup is cut short (no final chunk)")


class _ChunkReader(io.RawIOBase):
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._it, self._buf = chunks, b""

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        while not self._buf:
            try:
                self._buf = next(self._it)
            except StopIteration:
                return 0
        n = min(len(b), len(self._buf))
        b[:n] = self._buf[:n]
        self._buf = self._buf[n:]
        return n


# ------------------------------------------------------------------------------------------------ databases
@dataclass(frozen=True)
class DbSource:
    name: str  # trialbox_wf | hapi
    dsn: str
    schemas: tuple[str, ...]  # empty: the whole database; else only these schema patterns (a tb_prefix run)
    prefix: str = ""  # the tb_prefix of the schemas ("" on a box)

    def exclude_data(self) -> tuple[str, ...]:
        """The schemas whose rows a dump leaves out (D-187): ``refdata`` of the trial database; nothing of HAPI."""
        return tuple(f"{self.prefix}{s}" for s in EXCLUDE_DATA_SCHEMAS) if self.name == "trialbox_wf" else ()


def db_sources(env: Mapping[str, str]) -> list[DbSource]:
    from tb_common.db import split_url

    out = []
    if env.get("TB_DB_URL"):
        dsn, prefix = split_url(env["TB_DB_URL"])
        out.append(DbSource("trialbox_wf", dsn, (f"{prefix}*",) if prefix else (), prefix or ""))
    if env.get("TB_HAPI_DB_URL"):
        out.append(DbSource("hapi", env["TB_HAPI_DB_URL"], ()))
    if not out:
        raise BackupError("TB_DB_URL is not set: nothing to back up from the database")
    return out


def _cmd(env: Mapping[str, str], var: str, default: str) -> list[str]:
    return shlex.split(env.get(var) or default)


def _libpq(dsn: str) -> tuple[list[str], dict[str, str]]:
    """pg_dump/pg_restore take the database as ``--dbname``; a ``host=`` socket in the query is passed through."""
    return ["--dbname", dsn], {}


def dump(src: DbSource, out: Path, env: Mapping[str, str]) -> tuple[str, ...]:
    """Dump ``src`` to ``out``; return the schemas whose rows the dump left out."""
    pre = env.get("TB_PG_DUMP_DIR")
    if pre:  # D-138: dumps taken by the db container (update.py ComposeBox, backup_schedule's nightly run)
        f = Path(pre) / f"{src.name}.dump"
        if not f.is_file():
            raise BackupError(f"no {f} (TB_PG_DUMP_DIR)")
        shutil.copyfile(f, out)
        # the taker says what it left out (backup_schedule writes <name>.dump.json); without it, a full dump
        side = Path(pre) / f"{src.name}.dump.json"
        if side.is_file():
            return tuple(json.loads(side.read_text(encoding="utf-8")).get("exclude_table_data_schemas", []))
        return ()
    args, extra = _libpq(src.dsn)
    # -Z0: the dump is compressed once, by the backup's zstd stream (D-187), not twice
    cmd = [*_cmd(env, "TB_PG_DUMP_CMD", "pg_dump"), "--format=custom", "-Z0", "--no-owner", "--no-privileges", *args]
    for s in src.schemas:
        cmd += ["--schema", s]
    excluded = src.exclude_data()
    cmd += [f"--exclude-table-data={s}.*" for s in excluded]
    with out.open("wb") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, env={**os.environ, **extra}, check=False)
    if r.returncode != 0:
        raise BackupError(f"pg_dump of {src.name} failed: {r.stderr.decode(errors='replace').strip()[-400:]}")
    return excluded


def restore_db(src: DbSource, dump_file: Path, env: Mapping[str, str]) -> None:
    args, extra = _libpq(src.dsn)
    cmd = [*_cmd(env, "TB_PG_RESTORE_CMD", "pg_restore"), "--clean", "--if-exists", "--no-owner",
           "--no-privileges", "--single-transaction", "--exit-on-error", *args]  # fmt: skip
    if src.schemas:
        _drop_schemas(src)  # a tb_prefix run: drop its schemas first so the restore leaves nothing extra behind
    with dump_file.open("rb") as fh:
        r = subprocess.run(cmd, stdin=fh, stderr=subprocess.PIPE, env={**os.environ, **extra}, check=False)
    if r.returncode != 0:
        raise BackupError(f"pg_restore of {src.name} failed: {r.stderr.decode(errors='replace').strip()[-400:]}")


def _drop_schemas(src: DbSource) -> None:
    import psycopg

    with psycopg.connect(src.dsn, autocommit=True) as con:
        for pat in src.schemas:
            like = pat.replace("*", "%")
            for (n,) in con.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE %s", (like,)).fetchall():
                con.execute(f'DROP SCHEMA "{n}" CASCADE')


def row_counts(src: DbSource, skip_schemas: Sequence[str] = ()) -> dict[str, list[Any]]:
    """``schema.table -> [rows, md5 of the sorted rows as text]`` for every table of the source, except the tables of
    ``skip_schemas`` (whose rows the dump left out).

    The manifest keeps it; a restore must give the same pair for every table (content, not only counts).
    """
    import psycopg

    likes = [p.replace("*", "%") for p in src.schemas] or ["%"]
    skip = set(skip_schemas)
    out: dict[str, list[Any]] = {}
    with psycopg.connect(src.dsn, autocommit=True) as con:
        rows = con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' "
            "AND table_schema NOT IN ('pg_catalog', 'information_schema') AND table_schema LIKE ANY(%s) "
            "ORDER BY 1, 2",
            (likes,),
        ).fetchall()
        for schema, table in rows:
            if schema in skip:
                continue
            agg = "md5(COALESCE(string_agg(t::text, chr(10) ORDER BY t::text), ''))"
            q = f'SELECT count(*), {agg} FROM "{schema}"."{table}" t'
            n = con.execute(q).fetchone()
            out[f"{schema}.{table}"] = [int(n[0]), str(n[1])] if n else [0, ""]
    return out


def refdata_packs(src: DbSource) -> list[dict[str, str]]:
    """The reference packs loaded in the trial database (ids and dates only): what to load again after a restore."""
    import psycopg

    schema = f"{src.prefix}refdata"
    with psycopg.connect(src.dsn, autocommit=True) as con:
        there = con.execute("SELECT to_regclass(%s)", (f'"{schema}".pack',)).fetchone()
        if not there or there[0] is None:
            return []
        rows = con.execute(f'SELECT pack_id, data_as_of, origin FROM "{schema}".pack ORDER BY pack_id').fetchall()
    return [{"pack_id": str(a), "data_as_of": str(b), "origin": str(c)} for a, b, c in rows]


# ------------------------------------------------------------------------------------------------ directories
def layout(env: Mapping[str, str], given: Sequence[str] = ()) -> dict[str, Path]:
    """``name=path`` pairs from ``--dir`` or ``TB_BACKUP_DIRS`` (comma-separated); else the compose volumes."""
    pairs = list(given) or [p for p in (env.get("TB_BACKUP_DIRS") or "").split(",") if p.strip()]
    if pairs:
        out = {}
        for p in pairs:
            name, _, path = p.strip().partition("=")
            if not name or not path:
                raise BackupError(f"bad directory {p!r}: use name=path")
            out[name] = Path(path)
        return out
    return {k: Path(VOLUME_ROOT.format(v)) for k, v in DEFAULT_DIRS.items()}


def _sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk(root: Path) -> list[str]:
    if not root.exists():
        return []
    return [
        str(p.relative_to(root))
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.is_symlink() and "pre-restore-" not in str(p)
    ]


def tree_hashes(root: Path) -> dict[str, str]:
    """Every file under ``root`` and its sha256 (the drill's before-and-after comparison)."""
    return {rel: _sha_file(root / rel) for rel in _walk(root)}


def select_files(name: str, root: Path) -> tuple[list[str], dict[str, int]]:
    """The files of directory ``name`` that a backup takes (layout 2, D-187), and the count left out per reason.

    Only the lake has rules; every other directory is taken whole. The lake: no ``tmp/`` (DuckDB spill), no
    ``.building`` file (a snapshot being built), and the NDJSON only of ``CURRENT`` and of the two newest snapshots:
    the next delta night merges over the newest one older than itself (a held night's NDJSON is newer than
    ``CURRENT``; a night run again on the same date merges over the one before). Every Parquet and DuckDB file, the
    vector store (``embed_cache.duckdb``) and the site inputs are kept. A lake without ``CURRENT`` keeps all NDJSON.
    """
    keep: list[str] = []
    left: dict[str, int] = {}
    ndjson_keep: set[str] | None = None
    if name == "lake":
        cur, nd = root / "CURRENT", root / "ndjson"
        snaps = sorted(p.name for p in nd.iterdir() if p.is_dir()) if nd.is_dir() else []
        if cur.is_file() and snaps:
            ndjson_keep = {cur.read_text(encoding="utf-8").strip(), *snaps[-2:]}
    for rel in _walk(root):
        parts = Path(rel).parts
        why = ""
        if name == "lake" and parts[0] in LAKE_SKIP_TOP:
            why = "lake tmp/ (spill)"
        elif name == "lake" and rel.endswith(".building"):
            why = "lake snapshot being built"
        elif name == "lake" and ndjson_keep is not None and parts[0] == "ndjson" and len(parts) > 2 \
                and parts[1] not in ndjson_keep:  # fmt: skip
            why = "lake NDJSON of older snapshots (their Parquet and DuckDB are kept)"
        if why:
            left[why] = left.get(why, 0) + 1
        else:
            keep.append(rel)
    return keep, left


def _add(tar: tarfile.TarFile, path: Path, arcname: str) -> tuple[str, int]:
    """Add one file; return the sha256 and size of exactly the bytes that went into the tar (one read)."""
    with path.open("rb") as fh:
        info = tar.gettarinfo(arcname=arcname, fileobj=fh)
        hr = _HashReader(fh)
        try:
            tar.addfile(info, hr)
        except OSError as e:  # the file shrank while it was read
            raise BackupError(f"{arcname} changed while it was backed up; run the backup again") from e
    return hr.sha.hexdigest(), hr.n


def _write_sidecar(file: Path, sha: str) -> None:
    side = sidecar(file)
    tmp = side.with_name(side.name + ".part")
    tmp.write_text(f"{sha}  {file.name}\n", encoding="utf-8")
    tmp.rename(side)


def _copy_hashed(src: Path, dst: Path) -> str:
    """Copy ``src`` to ``dst`` (fsync) and return the sha256 of the bytes written."""
    h = hashlib.sha256()
    with src.open("rb") as fi, dst.open("wb") as fo:
        for chunk in iter(lambda: fi.read(CHUNK), b""):
            h.update(chunk)
            fo.write(chunk)
        fo.flush()
        os.fsync(fo.fileno())
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ compression
@contextlib.contextmanager
def _tar_writer(enc: Any, compression: str) -> Iterator[tarfile.TarFile]:
    """A streaming tar into ``enc``: zstd -3 on every core (D-149), or gzip (the format before D-149, kept only so
    the restore of an old backup stays tested). The compressor's last frame is written before the caller seals the
    final encrypted chunk."""
    if compression == "zstd":
        cctx = zstandard.ZstdCompressor(level=ZSTD_LEVEL, threads=-1)
        with cctx.stream_writer(enc, closefd=False) as zw, tarfile.open(fileobj=zw, mode="w|") as tar:
            yield tar
    elif compression == "gzip":
        with tarfile.open(fileobj=enc, mode="w|gz") as tar:
            yield tar
    else:
        raise BackupError(f"unknown compression {compression!r}")


def _tar_reader(plain: IO[bytes], header: Mapping[str, Any]) -> tarfile.TarFile:
    """The tar stream of a decrypted backup: zstd when the (authenticated) header says so, else gzip, which every
    backup made before D-149 used."""
    compression = header.get("compression", "gzip")
    if compression == "zstd":
        return tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(plain), mode="r|")
    if compression == "gzip":
        return tarfile.open(fileobj=plain, mode="r|gz")
    raise BackupError(f"this backup uses compression {compression!r}, which this TrialBox cannot read")


# ------------------------------------------------------------------------------------------------ backup
def backup(
    targets: Sequence[Path],
    public_key: Path,
    env: Mapping[str, str] | None = None,
    dirs: Mapping[str, Path] | None = None,
    keep: int = 14,
    site: str = "",
    now: datetime | None = None,
    compression: str = "zstd",
) -> list[Path]:
    """Write one encrypted backup to every target directory; return the files written."""
    env = dict(os.environ if env is None else env)
    if not targets:
        raise BackupError("no --to target")
    if compression not in ("zstd", "gzip"):
        raise BackupError(f"unknown compression {compression!r}")
    dirs = dict(dirs if dirs is not None else layout(env))
    when = now or datetime.now(UTC)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    site = site or env.get("TB_SITE_ID") or socket.gethostname()
    name = f"trialbox-{_safe(site)}-{stamp}{SUFFIX}"
    recipient = load_public(public_key)
    srcs = db_sources(env)
    manifest: dict[str, Any] = {"layout": LAYOUT, "hashing": "stream", "created_at": when.isoformat(timespec="seconds"),
                                "site": site, "compression": f"{compression}-{ZSTD_LEVEL}" if compression == "zstd"
                                else compression, "databases": {}, "dirs": {}, "files": {}, "sizes": {},
                                "excluded": {}, "refdata_packs": []}  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="tb-backup-") as tmp:
        work = Path(tmp)
        for src in srcs:
            excl = dump(src, work / f"{src.name}.dump", env)
            manifest["databases"][src.name] = {"schemas": list(src.schemas), "excluded_data_schemas": list(excl),
                                               "rows": row_counts(src, excl)}  # fmt: skip
            if excl and src.name == "trialbox_wf":
                manifest["refdata_packs"] = refdata_packs(src)
        first = Path(targets[0])
        first.mkdir(parents=True, exist_ok=True)
        part = first / (name + ".part")
        meta = {"site": site, "created_at": manifest["created_at"], "layout": LAYOUT, "compression": compression}
        with part.open("wb") as raw:
            hw = _HashWriter(raw)
            enc = _Encryptor(hw, recipient, meta)
            with _tar_writer(enc, compression) as tar:
                for src in srcs:
                    arc = f"db/{src.name}.dump"
                    manifest["files"][arc], manifest["sizes"][arc] = _add(tar, work / f"{src.name}.dump", arc)
                for dname, root in sorted(dirs.items()):
                    rels, left = select_files(dname, root)
                    n = 0
                    for rel in rels:
                        arc = f"dirs/{dname}/{rel}"
                        try:
                            manifest["files"][arc], manifest["sizes"][arc] = _add(tar, root / rel, arc)
                        except FileNotFoundError:  # removed since the listing (a retention prune): not in the backup
                            left["removed while the backup ran"] = left.get("removed while the backup ran", 0) + 1
                            continue
                        n += 1
                    manifest["dirs"][dname] = {"path": str(root), "files": n}
                    if left:
                        manifest["excluded"][dname] = left
                data = json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False).encode()
                info = tarfile.TarInfo("manifest.json")
                info.size = len(data)
                info.mtime = int(when.timestamp())
                tar.addfile(info, io.BytesIO(data))
            enc.finish()
            raw.flush()
            os.fsync(raw.fileno())
        sha = hw.sha.hexdigest()
        final = first / name
        part.rename(final)
        _write_sidecar(final, sha)
        written = [final]
        for t in targets[1:]:
            t = Path(t)
            t.mkdir(parents=True, exist_ok=True)
            tpart = t / (name + ".part")
            if _copy_hashed(final, tpart) != sha or _sha_file(tpart) != sha:  # written, then read back from t
                tpart.unlink(missing_ok=True)
                raise BackupError(f"copy to {t} does not match")
            tpart.rename(t / name)
            _write_sidecar(t / name, sha)
            written.append(t / name)
    for t in targets:
        prune(Path(t), keep)
    return written


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s)[:40] or "box"


# ------------------------------------------------------------------------------------------------ verify / restore
def unpack(file: Path, key: Path, into: Path) -> dict[str, Any]:
    """Decrypt and extract ``file`` into ``into``; check every hash against the manifest; return the manifest.

    The whole file is read and authenticated to its final chunk, and its sha256, taken on the way, must equal the
    ``.sha256`` sidecar when there is one."""
    sk = load_private(key)
    with file.open("rb") as fh:
        header, _ = read_header(fh)
        layout_ = header.get("layout", 1)
        if layout_ not in (1, 2):
            raise BackupError(f"this backup has layout {layout_!r}, made by a newer TrialBox: update this one first")
        fh.seek(0)
        hr = _HashReader(fh)
        reader = io.BufferedReader(_ChunkReader(decrypt_stream(hr, sk)), buffer_size=CHUNK)
        try:
            with _tar_reader(reader, header) as tar:
                tar.extractall(into, filter="data")
        except (tarfile.TarError, zstandard.ZstdError, EOFError) as e:
            raise BackupError(f"backup is damaged: its content cannot be read ({type(e).__name__})") from e
        while reader.read(CHUNK):  # the rest after the tar's end: authenticated to the final chunk all the same
            pass
    want = read_sidecar(file)
    if want is not None and want != hr.sha.hexdigest():
        raise BackupError(f"{file.name} does not match its .sha256 sidecar")
    manifest: dict[str, Any] = json.loads((into / "manifest.json").read_text(encoding="utf-8"))
    bad = [rel for rel, sha in manifest["files"].items() if not (into / rel).is_file() or _sha_file(into / rel) != sha]
    extra = {str(p.relative_to(into)) for p in into.rglob("*") if p.is_file() and p.name != "manifest.json"} - set(
        manifest["files"]
    )
    if bad or extra:
        raise BackupError(f"backup content does not match its manifest: {len(bad)} changed, {len(extra)} unlisted")
    manifest["_sha256"] = hr.sha.hexdigest()
    return manifest


def verify(file: Path, key: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="tb-verify-") as tmp:
        m = unpack(file, key, Path(tmp))
    return {"ok": True, "site": m["site"], "created_at": m["created_at"], "layout": m.get("layout", 1),
            "files": len(m["files"]), "sha256": m["_sha256"], "excluded": m.get("excluded", {}),
            "refdata_packs": m.get("refdata_packs", []),
            "databases": {k: sum(r[0] for r in v["rows"].values()) for k, v in m["databases"].items()}}  # fmt: skip


def restore(
    file: Path,
    key: Path,
    env: Mapping[str, str] | None = None,
    dirs: Mapping[str, Path] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Restore the databases and directories of ``file``; return what was restored, with row counts checked, and
    the reference packs to load again (their rows are not in a layout-2 backup)."""
    env = dict(os.environ if env is None else env)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory(prefix="tb-restore-") as tmp:
        work = Path(tmp)
        manifest = unpack(file, key, work)
        targets = dict(dirs if dirs is not None else layout(env))
        missing = set(manifest["dirs"]) - set(targets)
        if missing:
            raise BackupError(f"no place to restore directories {sorted(missing)}: pass --dir name=path")
        srcs = {s.name: s for s in db_sources(env)}
        for name in manifest["databases"]:
            if name not in srcs:
                raise BackupError(f"the backup holds database {name} but its URL is not set")
        for name in manifest["databases"]:
            restore_db(srcs[name], work / "db" / f"{name}.dump", env)
        for dname in manifest["dirs"]:
            dest = targets[dname]
            if dest.exists() and any(dest.iterdir()):
                aside = dest.with_name(f"{dest.name}.pre-restore-{stamp}")
                dest.rename(aside)
            dest.mkdir(parents=True, exist_ok=True)
            src = work / "dirs" / dname
            if src.exists():
                shutil.copytree(src, dest, dirs_exist_ok=True)
        checked = {}
        for name, want in manifest["databases"].items():
            got = row_counts(srcs[name], want.get("excluded_data_schemas", []))
            diff = sorted(k for k in set(got) | set(want["rows"]) if got.get(k) != want["rows"].get(k))
            if diff:
                raise BackupError(f"restored {name} differs from the backup in {len(diff)} tables: {diff[:5]}")
            checked[name] = sum(r[0] for r in got.values())
    return {"ok": True, "site": manifest["site"], "created_at": manifest["created_at"],
            "layout": manifest.get("layout", 1), "rows": checked, "dirs": sorted(manifest["dirs"]),
            "reload_refdata": manifest.get("refdata_packs", [])}  # fmt: skip
