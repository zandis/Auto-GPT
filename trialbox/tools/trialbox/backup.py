"""``trialbox backup`` / ``trialbox restore`` (TB-PLAN-04 step 2, D-126): the whole box in one encrypted file.

    trialbox backup-keygen --private /media/usb/trialbox-backup.key --public deploy/secrets/backup.pub
    trialbox backup  --to /mnt/nas/trialbox --to /media/usb/trialbox [--keep 14]
    trialbox backup-verify <file> --key /media/usb/trialbox-backup.key
    trialbox restore <file> --key /media/usb/trialbox-backup.key --yes

What is in a backup (``*.tbbak``, layout 2, D-187): a ``pg_dump`` (custom format, compressed only by the backup's
zstd stream) of ``trialbox_wf`` (``TB_DB_URL``) and, when ``TB_HAPI_DB_URL`` is set, of ``hapi``, each taken in one
database snapshot together with the row count and content hash of every table (``backup_schedule.snapshot_script``):
the box keeps running, and the manifest still matches the dump exactly. The vendor reference pack's rows
(``refdata.ctgov_study``, ``trial``, ``term``) are left out; the ``pack``, ``source`` and ``_schema_version`` rows and
the hospital's own (``site-fetch``) reference rows are in it, and a restore loads the packs again from
``deploy/refdata/loaded`` (or fails until it can). Then every directory of the layout (lake, objects, audit, rulesets,
orchestrator files, mail, secrets, console), where the lake keeps every Parquet and DuckDB file, the vector store,
the site inputs and the snapshot reports, but the ``*.ndjson`` only of ``CURRENT`` and of the two newest snapshots (a
delta night merges over the newest older one), and never ``tmp/`` (spill) or a ``.building`` file. A file is read
once, and its sha256 and size in the manifest are those of the bytes that went into the tar; a file that changed
while it was read (size or modification time) is read again, up to three times, else the backup fails.

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

**Restore** checks every hash before touching anything, refuses a backup of another site or older than 14 days
unless told, keeps the box as it is as one more encrypted backup (``--keep-to``) when it holds data, empties each
database, restores it with ``pg_restore`` and checks its rows before it moves each directory aside
(``<dir>.pre-restore-<time>``) and writes it, and audits the result (``backup.restored``; D-274). The nightly
run's ``host`` part (``deploy/.env``, settings, ``deploy/site``, the pgBackRest cipher, the identity and proxy
volumes) is written only to a folder named with ``--dir host=<folder>``. Every older format restores: layout 1
with gzip (before D-149) and layout 1 with zstd (D-149); a table's content hash is ``rs1`` since D-274, ``md5``
before.

The database tools are ``pg_dump`` / ``pg_restore`` on the path, or the command in ``TB_PG_DUMP_CMD`` /
``TB_PG_RESTORE_CMD`` (on a box: ``docker compose --project-directory deploy exec -T db pg_dump``). Nothing here logs
or prints a row or a file's content: only names, counts, sizes and hashes.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import io
import json
import os
import shlex
import shutil
import socket
import stat
import struct
import subprocess
import tarfile
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import zstandard
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from tb_common import kek as _K
from tb_common.crypto import KeyMissingError

# shared with the host-side schedule, which has only the standard library (re-exported: bk.prune, bk.read_sidecar ...)
from tools.trialbox import backup_schedule as _sched
from tools.trialbox import box_restore as _box_restore
from tools.trialbox import restic_repo as _rr

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
    "terminology": "tb-terminology",  # D-991: a restored box reads the code systems it had loaded
}
LAKE_SKIP_TOP = ("tmp",)  # DuckDB spill (lake.store temp_dir default)
# D-455 (H1): the lake's served files; listed and read under the lake's own lock (lake.store.lake_lock, D-462), so a
# rebuild's swap never falls between the listing and the reads, and checked against their sidecars after the read
LAKE_LOCKED = ("db", "parquet")
LAKE_LOCK = ".rebuild.lock"
# D-971 (lane B2's answer on #639, 2026-11-16): the vector store is the one lake file written in place (a build adds
# embeddings to it), by a build that holds its snapshot's build lock (locks/<snapshot>.build.lock) for the whole build,
# not the lake lock. It is read only while the lake is quiet: under the lake lock (no build can start) with every build
# lock taken (none runs), held for that read only; a running build is waited for, up to LAKE_QUIET_WAIT_S. With
# restic (D-968) the store goes to restic with the served files, under the same quiet lake (_add_lake_restic)
LAKE_STORE = ("embed_cache.duckdb", "embed_cache.duckdb.wal")
LAKE_QUIET_WAIT_S = 3 * 3600
LAKE_QUIET_POLL_S = 15
FD_SPARE = 256  # PERF-011: files the backup keeps free for its own work while it holds the lake's files open


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

    @property
    def refdata(self) -> str | None:
        """The reference data schema of the trial database (D-187: its vendor rows are left out); HAPI has none."""
        return f"{self.prefix}{_sched.REFDATA}" if self.name == "trialbox_wf" else None


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


def _client(env: Mapping[str, str], var: str, default: str) -> list[str]:
    """A PostgreSQL client tool's command (``var``, else ``default``), refused with its name and its setting when it
    cannot be run here. H-139: a host whose PostgreSQL is not on PATH met a bare FileNotFoundError, after a restore had
    already emptied the database's schemas."""
    cmd = _cmd(env, var, default)
    if not cmd or shutil.which(cmd[0]) is None:
        raise BackupError(f"the PostgreSQL client tool {default} cannot be run here ({cmd[0] if cmd else var!r} is not "
                          f"found): install the PostgreSQL client tools, or set {var} to its command")  # fmt: skip
    return cmd


def _libpq(dsn: str) -> tuple[list[str], dict[str, str]]:
    """pg_dump/pg_restore take the database as ``--dbname``; a ``host=`` socket in the query is passed through."""
    return ["--dbname", dsn], {}


def dump(src: DbSource, out: Path, env: Mapping[str, str], keep_owners: bool = False) -> None:
    """A full dump of ``src`` to ``out`` (the update path's rollback point; a backup uses :func:`take_snapshot`)."""
    pre = env.get("TB_PG_DUMP_DIR")
    if pre:  # D-138: dumps taken by the db container on a quiet box (tools/trialbox/update.py ComposeBox)
        f = Path(pre) / f"{src.name}.dump"
        if not f.is_file():
            raise BackupError(f"no {f} (TB_PG_DUMP_DIR)")
        shutil.copyfile(f, out)
        return
    args, extra = _libpq(src.dsn)
    # H-100: a restore's own copy of the box keeps the owners and grants (the service roles' own schemas)
    plain = [] if keep_owners else ["--no-owner", "--no-privileges"]
    cmd = [*_client(env, "TB_PG_DUMP_CMD", "pg_dump"), "--format=custom", *plain, *args]
    for s in src.schemas:
        cmd += ["--schema", s]
    with out.open("wb") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, env={**os.environ, **extra}, check=False)
    if r.returncode != 0:
        raise BackupError(f"pg_dump of {src.name} failed: {r.stderr.decode(errors='replace').strip()[-400:]}")


def take_snapshot(src: DbSource, work: Path, env: Mapping[str, str]) -> dict[str, Any]:
    """The dump of ``src`` in ``work/<name>.dump`` and, from the same database snapshot, its row counts and content
    hashes, the reference packs and the hospital's own reference rows (``backup_schedule.snapshot_script``, D-187).

    ``TB_PG_DUMP_DIR``: the files the nightly run's db container wrote, or, without a ``<name>.rows`` beside the
    dump, a full dump the update path took on a quiet box; its rows are then counted now (``rows_from: live``)."""
    pre = env.get("TB_PG_DUMP_DIR")
    if pre:
        d = Path(pre)
        if not (d / f"{src.name}.dump").is_file():
            raise BackupError(f"no {d / f'{src.name}.dump'} (TB_PG_DUMP_DIR)")
        if not (d / f"{src.name}.rows").is_file():
            shutil.copyfile(d / f"{src.name}.dump", work / f"{src.name}.dump")
            return {"rows_from": "live", "rows": row_counts(src), "excluded_tables": [], "refdata_schema": None,
                    "site_rows": {}, "packs": [], "site_files": {}, "row_hash": _sched.ROW_HASH,
                    "snapshot_at": datetime.now(UTC).isoformat(timespec="milliseconds")}  # fmt: skip
        for f in d.glob(f"{src.name}.*"):
            if f.is_file():
                shutil.copyfile(f, work / f.name)
    else:
        at = datetime.now(UTC).isoformat(timespec="milliseconds")  # D-455 (M3): the snapshot is taken right after this
        script = work / f"{src.name}.sql"
        pg_dump = " ".join(shlex.quote(a) for a in _client(env, "TB_PG_DUMP_CMD", "pg_dump"))
        script.write_text(_sched.snapshot_script(str(work), src.name, pg_dump, f'--dbname "{src.dsn}"', src.schemas,
                                                 src.refdata), encoding="utf-8")  # fmt: skip
        psql = [*_client(env, "TB_PSQL_CMD", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1", "--dbname", src.dsn]
        old = os.umask(0o077)
        try:
            r = subprocess.run([*psql, "-f", str(script)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               check=False)  # fmt: skip
        finally:
            os.umask(old)
        if r.returncode != 0:
            raise BackupError(f"the snapshot of {src.name} failed: {r.stderr.decode(errors='replace').strip()[-400:]}")
        (work / f"{src.name}.dump.json").write_text(json.dumps({**_sched.snapshot_meta(src.name, src.refdata),
                                                                "snapshot_at": at}))  # fmt: skip
    try:
        return _sched.parse_snapshot(work, src.name)
    except (OSError, RuntimeError, ValueError) as e:
        raise BackupError(str(e)) from e


def restore_db(src: DbSource, dump_file: Path, env: Mapping[str, str], keep_owners: bool = False) -> None:
    args, extra = _libpq(src.dsn)
    plain = [] if keep_owners else ["--no-owner", "--no-privileges"]  # H-100: a put-back keeps them
    cmd = [*_client(env, "TB_PG_RESTORE_CMD", "pg_restore"), "--clean", "--if-exists", *plain,
           "--single-transaction", "--exit-on-error", *args]  # fmt: skip
    # D-274 (CR-056): the database is emptied first, so a box that holds tables the backup does not (a later
    # migration, a newer schema) is not left with them, and the row check after the restore compares like with like
    _drop_schemas(src)
    with dump_file.open("rb") as fh:
        r = subprocess.run(cmd, stdin=fh, stderr=subprocess.PIPE, env={**os.environ, **extra}, check=False)
    if r.returncode != 0:
        raise BackupError(f"pg_restore of {src.name} failed: {r.stderr.decode(errors='replace').strip()[-400:]}")


ROLES_CMD = "TB_DB_ROLES_CMD"
ROLES_NOT_NEEDED = "not-needed"  # the value of TB_DB_ROLES_CMD where every service signs in as trialbox
ROLES_ON_A_BOX = "docker compose --project-directory deploy exec -T db /docker-entrypoint-initdb.d/30-service-roles.sh"


def reapply_service_roles(env: Mapping[str, str]) -> dict[str, str]:
    """D-573: after ``pg_restore --no-owner`` every restored schema, table and function is the restoring role's
    (``trialbox``); a service works as its schema's group, which then owns nothing. The service-roles script
    (D-378) gives them back; the restore runs it through ``TB_DB_ROLES_CMD``. ``{"state": "applied"}``, or
    ``not_configured`` with the line to run; a command that fails is a :class:`BackupError` with its output."""
    if (env.get(ROLES_CMD) or "").strip() == ROLES_NOT_NEEDED:  # the platform: its services sign in as trialbox
        return {"state": "not_needed"}
    cmd = _cmd(env, ROLES_CMD, "")
    if not cmd:
        return {"state": "not_configured", "run": ROLES_ON_A_BOX}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **dict(env)}, check=False)
    except OSError as e:
        raise BackupError(f"the service roles were not put back after the restore: {' '.join(cmd)}: {e}") from e
    if r.returncode != 0:
        raise BackupError(
            "the service roles were not put back after the restore (exit "
            f"{r.returncode}): {(r.stderr or r.stdout).strip()[-400:]}; the databases are restored and the services "
            "cannot work in them: do not start the services; fix what the output names and run this restore again"
        )
    return {"state": "applied"}


def roles_ok(roles: Mapping[str, str], env: Mapping[str, str]) -> bool:
    """Is the restore complete as far as the service roles go? Not when the command was not set on a box that
    runs for real (PRODUCTION, VALIDATION; an unset TB_ENV is PRODUCTION)."""
    if roles.get("state") != "not_configured":
        return True
    from tb_common.config import environment_name

    return environment_name(env) not in ("PRODUCTION", "VALIDATION")


def _drop_schemas(src: DbSource) -> None:
    """Drop the source's schemas in one transaction: those of its ``tb_prefix``, or, for a whole database, every
    schema but the system ones (``public`` is made again, empty, for the dump's objects)."""
    import psycopg

    with psycopg.connect(src.dsn) as con:
        names: list[str] = []
        for pat in src.schemas or ("*",):
            like = pat.replace("*", "%")
            names += [n for (n,) in con.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE %s AND nspname NOT LIKE 'pg\\_%%' "
                "AND nspname <> 'information_schema'", (like,)).fetchall()]  # fmt: skip
        for n in sorted(set(names)):
            con.execute(f'DROP SCHEMA "{n}" CASCADE')
        if not src.schemas:
            con.execute("CREATE SCHEMA IF NOT EXISTS public")
        con.commit()


def row_counts(src: DbSource, skip: Sequence[str] = (), scheme: str = _sched.ROW_HASH) -> dict[str, list[Any]]:
    """``schema.table -> [rows, content hash]`` for every table of the source, except the tables (``schema.table``)
    or whole schemas named in ``skip`` (whose rows the dump left out).

    The manifest keeps it; a restore must give the same pair for every table (content, not only counts). The same
    expression runs in the backup's snapshot (``backup_schedule.snapshot_script``). ``scheme`` is the hash the backup
    used (``backup_schedule.row_agg``: ``rs1`` since D-274, ``md5`` before).
    """
    import psycopg

    likes = [p.replace("*", "%") for p in src.schemas] or ["%"]
    skipped = set(skip)
    out: dict[str, list[Any]] = {}
    with psycopg.connect(src.dsn, autocommit=True) as con:
        rows = con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' "
            "AND table_schema NOT IN ('pg_catalog', 'information_schema') AND table_schema LIKE ANY(%s) "
            "ORDER BY 1, 2",
            (likes,),
        ).fetchall()
        for schema, table in rows:
            if schema in skipped or f"{schema}.{table}" in skipped:
                continue
            q = f'SELECT count(*), {_sched.row_agg(scheme)} FROM "{schema}"."{table}" t'
            n = con.execute(q).fetchone()
            out[f"{schema}.{table}"] = [int(n[0]), str(n[1])] if n else [0, ""]
    return out


_SITE_ROWS = "WHERE source_id IN (SELECT source_id FROM \"{s}\".source WHERE distribution = 'site-fetch')"


def site_row_counts(src: DbSource, refdata: str, scheme: str = _sched.ROW_HASH) -> dict[str, list[Any]]:
    """Rows and content hash of the hospital's own (``site-fetch``) rows in each vendor-pack table of ``refdata``."""
    import psycopg

    out: dict[str, list[Any]] = {}
    with psycopg.connect(src.dsn, autocommit=True) as con:
        if con.execute("SELECT to_regclass(%s)", (f'"{refdata}".source',)).fetchone() in (None, (None,)):
            return out
        for t in _sched.BULK_REFDATA:
            if con.execute("SELECT to_regclass(%s)", (f'"{refdata}"."{t}"',)).fetchone() in (None, (None,)):
                continue
            agg = _sched.row_agg(scheme)
            n = con.execute(f'SELECT count(*), {agg} FROM "{refdata}"."{t}" t ' + _SITE_ROWS.format(s=refdata))
            row = n.fetchone()
            out[f"{refdata}.{t}"] = [int(row[0]), str(row[1])] if row else [0, ""]
    return out


def _copy_in(src: DbSource, table: str, data: Path) -> None:
    import psycopg

    schema, _, name = table.partition(".")
    with psycopg.connect(src.dsn) as con, con.cursor() as cur:
        with cur.copy(f'COPY "{schema}"."{name}" FROM STDIN') as cp, data.open("rb") as fh:
            while chunk := fh.read(CHUNK):
                cp.write(chunk)
        con.commit()


def refdata_unpack_dir(folder: Path) -> Path | None:
    """Where a restore unpacks a reference pack (several GB): beside the kept packs (``folder``'s parent, on the disk
    that holds them), else None (the temporary folder, ``TMPDIR``). 10G-1 (D-1323): never a tmpfs /tmp that counts
    against a container's memory limit; the installer and the update unpack on the objects volume
    (``TMPDIR=/data/objects``) for the same reason."""
    return folder.parent if os.access(folder.parent, os.W_OK | os.X_OK) else None


@contextlib.contextmanager
def _tempdir(where: Path | None) -> Iterator[None]:
    """``tempfile``'s folder is ``where`` for the block (``tb_common.refdata.opened`` unpacks with ``mkdtemp``)."""
    if where is None:
        yield
        return
    where.mkdir(mode=0o700, parents=True, exist_ok=True)
    before = tempfile.tempdir
    tempfile.tempdir = str(where)
    try:
        yield
    finally:
        tempfile.tempdir = before


def reload_refdata(
    src: DbSource, packs: Sequence[Mapping[str, str]], folder: Path | None, unpack_in: Path | None = None
) -> dict[str, list[str]]:
    """Load again each vendor pack ``packs`` names, from the pack files in ``folder`` (``deploy/refdata/loaded``);
    the hospital's own packs (``origin: site``) came back with the dump. Returns what was loaded and what is missing.
    A pack unpacks in ``unpack_in`` (default :func:`refdata_unpack_dir`), never in a tmpfs /tmp (10G-1)."""
    want = {p["pack_id"] for p in packs if p.get("origin") != "site"}
    done: list[str] = []
    if want and folder is not None and folder.is_dir():
        from tb_common.refdata import RefStore, opened
        from tb_common.refdata import verify as verify_pack

        where = unpack_in or refdata_unpack_dir(folder)
        with RefStore(_url_for(src)) as st, _tempdir(where):
            for tar in sorted(folder.glob("*.tar")):
                try:
                    with opened(tar) as pack:
                        pid = verify_pack(pack)["pack_id"]
                        if pid in want and pid not in done:
                            st.load(pack, by="trialbox restore")
                            done.append(pid)
                except Exception:  # a damaged or foreign file: the pack stays missing, and the restore says so
                    continue
    return {"reloaded": sorted(done), "missing": sorted(want - set(done))}


def _url_for(src: DbSource) -> str:
    if not src.prefix:
        return src.dsn
    return f"{src.dsn}{'&' if '?' in src.dsn else '?'}tb_prefix={src.prefix}"


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
    the next delta night merges over the newest older one that passed (``CURRENT`` or newer; never a held night's
    NDJSON, D-271; a held night's folder is kept for the steward to look at); an older snapshot keeps its reports
    (``reader.json``, ``tombstones.json``). Every Parquet and DuckDB file, the vector store (``embed_cache.duckdb``)
    and the site inputs are kept. A lake without ``CURRENT`` keeps all NDJSON.
    """
    keep: list[str] = []
    left: dict[str, int] = {}
    ndjson_keep: set[str] | None = None
    licensed = licensed_tables(root) if name == "terminology" else set()
    if name == "lake":
        cur, nd = root / "CURRENT", root / "ndjson"
        snaps = sorted(p.name for p in nd.iterdir() if p.is_dir()) if nd.is_dir() else []
        if cur.is_file() and snaps:
            ndjson_keep = {cur.read_text(encoding="utf-8").strip(), *snaps[-2:]}
    for rel in _walk(root):
        parts = Path(rel).parts
        if name == "lake" and rel == LAKE_LOCK:  # the lake's lock file (empty; the backup takes it, D-455)
            continue
        why = ""
        if name == "lake" and parts[0] in LAKE_SKIP_TOP:
            why = "lake tmp/ (spill)"
        elif name == "lake" and any(x.endswith((".building", ".old")) for x in parts):
            why = "lake snapshot being built"  # D-462: the build file and the Parquet stage, swapped in when done
        elif name == "lake" and parts[:2] == ("db", ".open"):
            why = "lake reader links (the same files as db/)"  # D-462: hard links, taken once as db/<snapshot>.duckdb
        elif name == "lake" and parts[:2] == ("db", "gen") and not rel.endswith(".json"):
            # T-724 (D-490): each date's newest generation is its own file db/<snapshot>.duckdb, taken once; an older
            # generation is only a running job's. The generations' records (names, numbers and hashes; no patient
            # data) are kept: a restored date gets the name its bytes had, and a number is never given twice
            why = "lake generations (the newest is db/<snapshot>.duckdb)"
        elif name == "lake" and ndjson_keep is not None and parts[0] == "ndjson" and len(parts) > 2 \
                and parts[1] not in ndjson_keep and rel.endswith(".ndjson"):  # fmt: skip
            why = "lake NDJSON of older snapshots (their Parquet and DuckDB are kept)"
        elif name == "terminology" and rel in licensed:
            # V-18 (D-1182; the integrator's ruling on #639): a table built from the hospital's licensed copy never
            # leaves the box. Its manifest.json line (name, version, sha256) is kept: a restore reloads it from the
            # hospital's folder (deploy/terminology-update.sh), and the doctor names it until then
            why = "terminology tables built from a licensed copy (reloaded from the hospital's folder)"
        if why:
            left[why] = left.get(why, 0) + 1
        else:
            keep.append(rel)
    return keep, left


def licensed_tables(root: Path) -> set[str]:
    """V-18: the terminology volume's tables built from a licensed copy: each table whose manifest.json line names
    who accepted its licence (D-1114). Read from the volume itself: the backup image has no loader. A manifest that
    cannot be read leaves out every table (never a licensed one by mistake): only manifest.json is then kept."""
    try:
        lines = json.loads((root / "manifest.json").read_text("utf-8")).get("tables") or {}
    except (OSError, ValueError):
        return {rel for rel in _walk(root) if rel.endswith(".parquet")}
    return {f"{n}.parquet" for n, line in lines.items() if str((line or {}).get("licence_accepted_by") or "").strip()}


READ_TRIES = 3


#: ENG-011 (D-755): the other files only ever appended to, one whole line per write: the lake's record of each
#: rebuild's source (``lake.source.record_source``)
APPEND_ONLY_FILES = ("dirs/lake/source.jsonl",)


def _append_only(arcname: str) -> bool:
    """The audit chain's day files (``audit/<day>.jsonl``): only ever appended to, one whole line per write
    (``tb_common.audit``); a repair that cuts one back is the one exception, and is seen as a file that shrank.
    And :data:`APPEND_ONLY_FILES` (ENG-011, D-755)."""
    return (arcname.startswith("dirs/audit/") and arcname.endswith(".jsonl")) or arcname in APPEND_ONLY_FILES


def _line_end(fh: IO[bytes], size: int) -> int:
    """The length of the longest prefix of the first ``size`` bytes of ``fh`` that ends with a line end (0: none)."""
    pos = size
    while pos > 0:
        start = max(0, pos - 65536)
        fh.seek(start)
        at = fh.read(pos - start).rfind(b"\n")
        if at >= 0:
            return start + at + 1
        pos = start
    return 0


def _starts_with(path: Path, n: int, sha: Any) -> bool:
    """Whether the first ``n`` bytes of ``path`` now are the bytes that hashed to ``sha`` (read again: only for an
    append-only file that changed while it was read)."""
    h, left = hashlib.sha256(), n
    try:
        with path.open("rb") as fh:
            while left > 0:
                b = fh.read(min(left, 1 << 20))
                if not b:
                    return False
                h.update(b)
                left -= len(b)
    except OSError:
        return False
    return bool(h.digest() == sha.digest())


# D-724: the length up to which each audit day file is copied (``_audit_moment``), by its name in the backup, for
# the audit folder's copy; ``_add`` keeps its three arguments, so every caller and replacement of it stays as it was
_UPTO: ContextVar[Mapping[str, int] | None] = ContextVar("tb_backup_upto", default=None)


def _add(tar: tarfile.TarFile, path: Path, arcname: str, limit: int | None = None) -> tuple[str, int]:
    """Add one file; return the sha256 and size of exactly the bytes that went into the tar (one read per try).

    The box is running: a file whose size or modification time changed while it was read (a DuckDB file rewritten
    in place at the same size, a list rewritten) is added again, and the later copy is the one a restore extracts
    and the manifest names; after ``READ_TRIES`` the backup fails. A file that shrank under the read cannot be taken
    back out of the stream: the backup fails at once.

    **An append-only file** (:func:`_append_only`: the audit chain, which every model call of a night's jobs
    appends to) is taken as it stood when the read began, up to its last whole line: if it only grew meanwhile (the
    same file, and what was read is still its beginning, checked by reading that much again), the bytes read are a
    whole earlier state and the copy is kept. Without this a busy
    night made every backup fail ("kept changing"), which is the product being too strict, not the box being
    unsafe. The lines appended later are in the next backup, and a restore lists what the box wrote after the
    backup (``events_to_reapply``). ``limit`` (or, when not given, the audit moment's length of this file): the copy
    ends there (D-724)."""
    if limit is None:
        limit = (_UPTO.get() or {}).get(arcname)
    grows = _append_only(arcname)
    for _ in range(READ_TRIES):
        with path.open("rb") as fh:
            before = os.fstat(fh.fileno())
            info = tar.gettarinfo(arcname=arcname, fileobj=fh)
            if info.islnk():
                # NEW-B-17 (D-537): a second name of a file this tar already holds (a hard link: a work lake's
                # db/<date>.duckdb, its generation, a reader's link). The tar writer would store a link with no
                # bytes, and the manifest would name the hash of nothing for a file a restore writes whole. Every
                # name is stored with its own bytes: no member of a backup needs another one to be read
                info.type, info.linkname, info.size = tarfile.REGTYPE, "", before.st_size
            if grows:  # never a line that is being written; D-724: never past the length the head anchor was read with
                info.size = _line_end(fh, before.st_size if limit is None else min(limit, before.st_size))
                fh.seek(0)
            hr = _HashReader(fh)
            try:
                tar.addfile(info, hr)
            except OSError as e:  # the file shrank while it was read
                raise BackupError(f"{arcname} changed while it was backed up; run the backup again") from e
        try:
            after = path.stat()
        except FileNotFoundError:  # replaced by a rename, gone for now: the copy read is a whole, older file
            return hr.sha.hexdigest(), hr.n
        if (after.st_size, after.st_mtime_ns, after.st_ino) == (before.st_size, before.st_mtime_ns, before.st_ino):
            return hr.sha.hexdigest(), hr.n
        if grows and after.st_ino == before.st_ino and after.st_size >= hr.n and _starts_with(path, hr.n, hr.sha):
            return hr.sha.hexdigest(), hr.n  # appended to while it was read: what was read is still its beginning
    raise BackupError(f"{arcname} kept changing while it was backed up ({READ_TRIES} reads); run the backup again")


def _audit_moment(root: Path) -> tuple[bytes | None, dict[str, int]]:
    """D-724 (DATA-009): the audit chain at one moment: ``HEAD.json``'s bytes, and every day file there is with its
    length up to its last whole line, all read together under the writer's own lock (``audit/.lock``, the ``flock``
    every ``tb_common.audit`` write takes), so no event is written between the reads. The folder is listed under the
    lock too: a day file the writer started after an earlier listing (the day changed, or the first event ever) is in
    it. The copy takes each day file up to that length, so the backup's chain ends where its head anchor says, even
    when the writer cuts a torn last line and writes on before the copy. The lock is held for those reads, not for
    the copy. A box whose chain was never written has no lock file, and none is made: the backup runs as root, and a
    lock file it made would be root's, which the writer could not open."""
    lock = root / ".lock"

    def read() -> tuple[bytes | None, dict[str, int]]:
        head = root / "HEAD.json"
        data = head.read_bytes() if head.is_file() else None
        lengths: dict[str, int] = {}
        for rel in _walk(root):
            if _append_only(f"dirs/audit/{rel}"):
                with (root / rel).open("rb") as fh:
                    lengths[rel] = _line_end(fh, os.fstat(fh.fileno()).st_size)
        return data, lengths

    if not lock.is_file():
        return read()
    with lock.open("rb") as fh:  # read-only: flock needs no write access
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
        try:
            return read()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _add_read(tar: tarfile.TarFile, path: Path, arcname: str, data: bytes) -> tuple[str, int]:
    """One member from bytes already read (the head anchor of :func:`_audit_moment`), with the file's own owner,
    mode and time."""
    info = tar.gettarinfo(str(path), arcname=arcname)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(data).hexdigest(), len(data)


@contextlib.contextmanager
def _lake_lock(root: Path) -> Iterator[bool]:
    """The lake's lock (``lake/.rebuild.lock``, an exclusive ``flock``, the same file ``lake.store.lake_lock`` takes):
    a rebuild's swap, a hold and a release wait while it is held. ``flock`` needs no write access, so a read-only
    mount (the backup container) takes it too. False when there is no lock file to take (a lake never rebuilt)."""
    import fcntl

    path = root / LAKE_LOCK
    try:
        fh = path.open("a")
    except OSError:
        try:
            fh = path.open("r")
        except OSError:
            yield False
            return
    with fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield True
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _sidecar_sha(text: bytes) -> str:
    """The hash a ``sha256sum``-format sidecar names (``<sha>  <name>``), or "" when it names none."""
    first = text.decode("utf-8", errors="replace").split()
    return first[0] if first and len(first[0]) == 64 else ""


def _lake_listing_problems(root: Path, locked: Sequence[str]) -> list[str]:
    """What makes a listing of the lake's served files not one state (D-455, H1): a sidecar whose file is not
    listed, a ``db/<snapshot>.duckdb`` whose Parquet folder is missing or empty."""
    have = set(locked)
    out = [
        f"{r}: sidecar without its file" for r in locked if r.endswith(".sha256") and r[: -len(".sha256")] not in have
    ]
    for r in locked:
        p = Path(r)
        if p.parts[0] == "db" and len(p.parts) == 2 and p.suffix == ".duckdb":
            folder = f"parquet/snapshot={p.stem}/"
            if not any(x.startswith(folder) and x.endswith(".parquet") for x in have):
                out.append(f"{r}: its Parquet folder parquet/snapshot={p.stem} is missing or empty")
    return out


def _add_bytes(tar: tarfile.TarFile, data: bytes, arcname: str, mtime: float) -> tuple[str, int]:
    info = tarfile.TarInfo(arcname)
    info.size, info.mtime, info.mode = len(data), int(mtime), 0o600
    tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(data).hexdigest(), len(data)


def _fds_for(n: int) -> bool:
    """Whether this process may hold ``n`` more files open (PERF-011): the soft limit raised to the hard one first,
    and :data:`FD_SPARE` kept for everything else the backup opens."""
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if hard != resource.RLIM_INFINITY and soft < hard:
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
            soft = hard
    return soft == resource.RLIM_INFINITY or n + FD_SPARE <= soft


def _open_lake_files(root: Path, locked: Sequence[str]) -> dict[str, Any]:
    """Under the lake's lock (PERF-011): each served file open, each sidecar's bytes read. A file gone between the
    listing and here, under the lock, is a lake that moved under its own lock: the backup fails."""
    held: dict[str, Any] = {}
    try:
        for rel in locked:
            path = root / rel
            if rel.endswith(".sha256"):
                held[rel] = (path.read_bytes(), path.stat().st_mtime)
            else:
                fh = path.open("rb")
                held[rel] = (fh, os.fstat(fh.fileno()))
    except FileNotFoundError as e:
        for v in held.values():
            if hasattr(v[0], "close"):
                v[0].close()
        raise BackupError(f"lake file {e.filename} vanished under the lake's lock; run the backup again") from e
    return held


def _read_held(tar: tarfile.TarFile, held: dict[str, Any], manifest: dict[str, Any]) -> tuple[dict[str, str], int]:
    """The files :func:`_open_lake_files` opened, read through their handles after the lock (PERF-011). A served
    file is never written in place: one that changed while it was read fails the backup (its sidecar would too)."""
    sides: dict[str, str] = {}
    try:
        for rel, (obj, meta) in held.items():
            arc = f"dirs/lake/{rel}"
            if rel.endswith(".sha256"):
                manifest["files"][arc], manifest["sizes"][arc] = _add_bytes(tar, obj, arc, meta)
                sides[rel[: -len(".sha256")]] = _sidecar_sha(obj)
                continue
            info = tar.gettarinfo(arcname=arc, fileobj=obj)
            info.type, info.linkname, info.size = tarfile.REGTYPE, "", meta.st_size  # NEW-B-17: never a link
            hr = _HashReader(obj)
            try:
                tar.addfile(info, hr)
            except OSError as e:
                raise BackupError(f"{arc} shrank while it was backed up; run the backup again") from e
            now = os.fstat(obj.fileno())
            if (now.st_size, now.st_mtime_ns) != (meta.st_size, meta.st_mtime_ns):
                raise BackupError(f"{arc} was written while it was backed up; run the backup again")
            manifest["files"][arc], manifest["sizes"][arc] = hr.sha.hexdigest(), hr.n
    finally:
        for obj, _ in held.values():
            if hasattr(obj, "close"):
                obj.close()
    return sides, len(held)


def _read_lake_files(
    tar: tarfile.TarFile, root: Path, locked: Sequence[str], manifest: dict[str, Any], locked_ok: bool
) -> tuple[dict[str, str], int]:
    """The served files read by path, under the lake's lock when there is one (D-455, as before PERF-011)."""
    sides: dict[str, str] = {}
    for rel in locked:
        arc = f"dirs/lake/{rel}"
        try:
            if rel.endswith(".sha256"):
                data = (root / rel).read_bytes()
                manifest["files"][arc], manifest["sizes"][arc] = _add_bytes(
                    tar, data, arc, (root / rel).stat().st_mtime
                )
                sides[rel[: -len(".sha256")]] = _sidecar_sha(data)
            else:
                manifest["files"][arc], manifest["sizes"][arc] = _add(tar, root / rel, arc)
        except FileNotFoundError as e:
            raise BackupError(f"lake file {rel} vanished while the lake was read "
                              f"{'under its lock' if locked_ok else '(no lake lock)'}; run the backup "
                              "again") from e  # fmt: skip
    return sides, len(locked)


def _add_lake_restic(
    tar: tarfile.TarFile,
    root: Path,
    manifest: dict[str, Any],
    repo: _rr.Repo,
) -> tuple[int, dict[str, int]]:
    """PERF-010 (D-968): the lake's served files (``db/``, ``parquet/``) go to restic, the rest into the sealed
    file. Under the lake's lock, held until restic has read them (a rebuild's swap waits for the whole read; the
    vector store needs it, lane B2's answer on #639): the listing, each sidecar read into the sealed file, each served
    file's sha256 (its sidecar's, else read once) and size recorded in ``manifest["restic"]``, and exactly those
    files given to restic. A restore checks restic's files against that sealed record. The vector store
    (``LAKE_STORE``, written in place by a build) goes to restic with them, so the lock is taken only while no build
    runs (:func:`_quiet_lake`, lane B2's answer on #639). The rest of the lake is read after the lock, as before."""
    with _quiet_lake(root, LAKE_QUIET_WAIT_S, LAKE_QUIET_POLL_S) as locked_ok:
        rels, left = select_files("lake", root)
        locked = [r for r in rels if Path(r).parts[0] in LAKE_LOCKED]
        store = [r for r in rels if r in LAKE_STORE]  # lane B2: under the quiet lake, with the served files
        problems = _lake_listing_problems(root, locked)
        if problems:
            raise BackupError(f"the lake fails its own check ({problems[:3]}): a person looks at it "
                              "(trialbox doctor; the lake's /verify) before it can be backed up")  # fmt: skip
        sides: dict[str, str] = {}
        for rel in [r for r in locked if r.endswith(".sha256")]:
            data = (root / rel).read_bytes()
            arc = f"dirs/lake/{rel}"
            manifest["files"][arc], manifest["sizes"][arc] = _add_bytes(tar, data, arc, (root / rel).stat().st_mtime)
            sides[rel[: -len(".sha256")]] = _sidecar_sha(data)
        served = [r for r in locked if not r.endswith(".sha256")] + store
        # review of D-968: every served file is read and hashed here, under the lock, and must match its sidecar,
        # as the path without restic requires: a rotted file or a wrong sidecar fails the backup tonight, not every
        # restore later. The (size, mtime) seen here must still hold once restic has read the file.
        files: dict[str, list[Any]] = {}
        seen: dict[str, tuple[int, int]] = {}
        for rel in served:
            st = (root / rel).stat()
            files[rel] = [_sha_file(root / rel), st.st_size]
            seen[rel] = (st.st_size, st.st_mtime_ns)
        bad = [f"dirs/lake/{r}" for r, (sha, _) in files.items() if r in sides and sides[r] != sha]
        if bad:
            raise BackupError(f"the lake fails its own check: {len(bad)} file(s) differ from their sidecar"
                              + _named("changed", bad) + "; a person looks at it (trialbox doctor)")  # fmt: skip
        try:
            snapshot = repo.backup(root, served, tag=_rr.LAKE_TAG) if served else ""
        except _rr.ResticError as e:
            raise BackupError(str(e)) from e
        after = [r for r in select_files("lake", root)[0] if Path(r).parts[0] in LAKE_LOCKED]
        moved = [r for r in served if _stat_key(root / r) != seen[r]]
    if after != locked or moved:
        _forget_quietly(repo, snapshot)
        raise BackupError("the lake changed while restic read it "
                          f"({'under its lock' if locked_ok else 'no lake lock'}){_named('changed', moved)}; run the "
                          "backup again")  # fmt: skip
    manifest["restic"] = {"repository": repo.path.name, "snapshot": snapshot, "root": str(root.resolve()),
                          "files": files}  # fmt: skip
    n = len(locked) + len(store)
    for rel in [r for r in rels if Path(r).parts[0] not in LAKE_LOCKED and r not in store]:
        arc = f"dirs/lake/{rel}"
        try:
            manifest["files"][arc], manifest["sizes"][arc] = _add(tar, root / rel, arc)
        except FileNotFoundError:  # removed since the listing (a retention prune): not in the backup
            left["removed while the backup ran"] = left.get("removed while the backup ran", 0) + 1
            continue
        n += 1
    return n, left


@contextlib.contextmanager
def _build_locks(root: Path) -> Iterator[list[str]]:
    """Every ``locks/*.build.lock`` of the lake taken without waiting (``lake.store.BuildLock``'s lock), held for the
    block; yields the snapshots whose build holds its lock now (an empty list: no build runs). Taken under the lake
    lock, so a build cannot start meanwhile (it waits for the lake lock after its build lock, and a new one is told
    the snapshot is building)."""
    held: list[Any] = []
    busy: list[str] = []
    try:
        for f in sorted((root / "locks").glob("*.build.lock")) if (root / "locks").is_dir() else []:
            try:
                fh = f.open("r")
            except OSError:
                continue
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fh.close()
                busy.append(f.name[: -len(".build.lock")])
                continue
            held.append(fh)
        yield busy
    finally:
        for fh in held:
            with contextlib.suppress(OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()


@contextlib.contextmanager
def _quiet_lake(root: Path, wait_s: float, poll_s: float) -> Iterator[bool]:
    """The lake lock with no build running (:func:`_build_locks`), waited for up to ``wait_s``: a running build is
    let finish, the lake lock let go between looks. Yields whether the lake lock was taken (as :func:`_lake_lock`).
    A build still running after ``wait_s`` fails the backup by name."""
    deadline = time.monotonic() + wait_s
    while True:
        with _lake_lock(root) as locked_ok, _build_locks(root) as busy:
            if not busy:
                yield locked_ok
                return
        if time.monotonic() >= deadline:
            raise BackupError(
                f"a lake rebuild ran for the whole wait ({', '.join(busy)}; {int(wait_s)} s): the vector store is "
                "written in place while a build runs, so it is not backed up then; run the backup after the rebuild"
            )
        time.sleep(poll_s)


def _stat_key(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return st.st_size, st.st_mtime_ns


def _forget_quietly(repo: _rr.Repo, snapshot: str) -> None:
    """A snapshot no sealed file will name (the run failed after restic made it): forgotten now, so it is never
    counted as a night's (review of D-968). A failure here is left to the next night's forget."""
    if snapshot:
        with contextlib.suppress(_rr.ResticError):
            repo.forget_ids([snapshot])


SNAPSHOT_SUFFIX = ".restic"  # beside a .tbbak: the id of the restic snapshot it needs (no secret); D-968


def _same_file(path: Path, sha: str, size: int) -> bool:
    """A regular file (never a link), of this size and sha256."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_size == size and _sha_file(path) == sha


def _manifest_rel_ok(rel: str) -> bool:
    """A lake file's path as a restic record may name it: relative, plain, under ``db/`` or ``parquet/``, or exactly
    the vector store (``LAKE_STORE``)."""
    from pathlib import PurePosixPath

    if rel in LAKE_STORE:
        return True
    p = PurePosixPath(rel)
    return (not p.is_absolute() and bool(p.parts) and p.parts[0] in LAKE_LOCKED and "\\" not in rel
            and all(x not in ("", ".", "..") for x in rel.split("/")))  # fmt: skip


def _restore_lake_from_restic(file: Path, into: Path, manifest: dict[str, Any], pw: str | None) -> None:
    """The lake's served files of a restic backup (PERF-010, D-968), from the repository beside ``file``, each
    checked against the sealed manifest (sha256 and size) before it is put where the tar would have put it."""
    rec = manifest["restic"]
    if not rec.get("files"):
        return
    repo_name = str(rec.get("repository") or "")
    bad_names = [r for r in rec["files"] if not _manifest_rel_ok(r)]
    if "/" in repo_name or repo_name in ("", ".", "..") or bad_names:
        raise BackupError("this backup's restic record names paths outside the lake's served files: refused, nothing "
                          "written" + _named("refused", bad_names))  # fmt: skip
    where = file.parent / repo_name
    if pw is None:
        raise BackupError(
            f"this backup's lake is in the restic repository beside it ({where}): open it with the box's KEK "
            "(--restic-from-box) or with the custodians' shares (--restic-share FILE, one per share)"
        )
    stage = into / ".restic-restore"
    try:
        _rr.Repo(where, pw).restore(rec["snapshot"], stage)
        src = _rr.restored_root(stage, str(rec["root"]))
        bad = [f"dirs/lake/{rel}" for rel, (sha, size) in sorted(rec["files"].items())
               if not _same_file(src / rel, sha, size)]  # fmt: skip
        got = {p.relative_to(src).as_posix() for p in src.rglob("*")
               if p.is_symlink() or not p.is_dir()} if src.is_dir() else set()  # fmt: skip
        extra = [f"dirs/lake/{rel}" for rel in got - set(rec["files"])]
        if bad or extra:
            raise BackupError(
                f"the lake restored from restic does not match the backup's sealed manifest: {len(bad)} changed, "
                f"{len(extra)} unlisted" + _named("changed", bad) + _named("unlisted", extra)
            )
        for rel, (sha, size) in rec["files"].items():
            dst = into / "dirs" / "lake" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src / rel, dst)
            manifest["files"][f"dirs/lake/{rel}"], manifest["sizes"][f"dirs/lake/{rel}"] = sha, size
    except _rr.ResticError as e:
        raise BackupError(str(e)) from e
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _add_lake_store(tar: tarfile.TarFile, root: Path, rels: list[str], manifest: dict[str, Any]) -> int:
    """D-971: the vector store (``LAKE_STORE``), read while the lake is quiet (:func:`_quiet_lake`), the locks held
    for this read only. ``manifest["lake_store"]`` records the files, how long the backup waited for a running build
    and how long it held the locks."""
    store = [r for r in rels if r in LAKE_STORE]
    if not store:
        return 0
    t0 = time.monotonic()
    taken: list[str] = []
    with _quiet_lake(root, LAKE_QUIET_WAIT_S, LAKE_QUIET_POLL_S) as locked_ok:
        t1 = time.monotonic()
        for rel in store:
            arc = f"dirs/lake/{rel}"
            try:
                manifest["files"][arc], manifest["sizes"][arc] = _add(tar, root / rel, arc)
            except FileNotFoundError:  # a .wal that DuckDB checkpointed away between the listing and the lock
                continue
            taken.append(rel)
        t2 = time.monotonic()
    manifest["lake_store"] = {"files": taken, "locked": locked_ok, "waited_s": round(t1 - t0, 3),
                              "held_s": round(t2 - t1, 3)}  # fmt: skip
    n = len(taken)
    return n


def _add_lake(
    tar: tarfile.TarFile, root: Path, manifest: dict[str, Any], repo: _rr.Repo | None = None
) -> tuple[int, dict[str, int]]:
    """The lake (D-455, H1). Its served files (``db/``, ``parquet/``) are listed and opened under the lake's lock and
    read through the open files after it (PERF-011, D-755), so a rebuild's swap waits for the listing only: never
    half the old snapshot and half the new. A listing that is not one state
    is listed again, up to ``READ_TRIES``; after the read every file taken with its sidecar must hash to it and the
    files must still be the ones listed, or the backup fails (nothing vanished, nothing new). The rest of the lake
    (NDJSON, the site inputs) is read after, without the lock; the vector store last, while no build runs
    (D-971). Returns the files taken and the count left out per reason. With ``repo``, the served files and the
    vector store go to restic instead (:func:`_add_lake_restic`, D-968)."""
    if repo is not None:
        return _add_lake_restic(tar, root, manifest, repo)
    left: dict[str, int] = {}
    n = 0
    for attempt in range(1, READ_TRIES + 1):
        held: dict[str, Any] | None = None
        with _lake_lock(root) as locked_ok:
            rels, left = select_files("lake", root)
            locked = [r for r in rels if Path(r).parts[0] in LAKE_LOCKED]
            problems = _lake_listing_problems(root, locked)
            if problems:
                if locked_ok:  # under the lock nothing moves: this is the lake as it is on disk, damaged
                    raise BackupError(f"the lake fails its own check ({problems[:3]}): a person looks at it "
                                      "(trialbox doctor; the lake's /verify) before it can be backed up")  # fmt: skip
                if attempt == READ_TRIES:
                    raise BackupError(f"the lake's files are not one state ({problems[:3]}) after {READ_TRIES} "
                                      "listings without a lake lock; run the backup again")  # fmt: skip
                continue
            # PERF-011 (D-755): under the lock each served file is only opened, each sidecar read; the bytes are
            # read after the lock is let go, through the open files. A rebuild's swap waits for the listing only,
            # and a file it removes meanwhile is still read whole through its handle. Without a lock to let go, or
            # with more files than this process may hold open, they are read under it, as before.
            if locked_ok and _fds_for(len(locked)):
                held = _open_lake_files(root, locked)
            else:
                sides, got = _read_lake_files(tar, root, locked, manifest, locked_ok)
                again = [r for r in select_files("lake", root)[0] if Path(r).parts[0] in LAKE_LOCKED]
        if held is not None:
            sides, got = _read_held(tar, held, manifest)
            again = locked  # the files read are the ones listed under the lock, whatever a swap did since
        n += got
        bad = [r for r, want in sides.items() if manifest["files"].get(f"dirs/lake/{r}") != want]
        if bad or again != locked:
            raise BackupError(f"the lake changed while it was read: {len(bad)} file(s) differ from their sidecar "
                              f"{bad[:3]}, listing {'changed' if again != locked else 'unchanged'}; run the "
                              "backup again")  # fmt: skip
        break
    for rel in [r for r in rels if Path(r).parts[0] not in LAKE_LOCKED and r not in LAKE_STORE]:
        arc = f"dirs/lake/{rel}"
        try:
            manifest["files"][arc], manifest["sizes"][arc] = _add(tar, root / rel, arc)
        except FileNotFoundError:  # removed since the listing (a retention prune): not in the backup
            left["removed while the backup ran"] = left.get("removed while the backup ran", 0) + 1
            continue
        n += 1
    n += _add_lake_store(tar, root, rels, manifest)  # D-971: while no build writes it
    return n, left


def lake_check(root: Path) -> dict[str, Any]:
    """The lake's own check (``lake.store.Lake.verify``, D-462) of every snapshot under ``root``: each
    ``db/<snapshot>.duckdb`` and each Parquet file of its folder against its ``.sha256`` sidecar, and the folder not
    empty. Run by the restore on the restored lake before it is put in place (D-455, H1). A file with no sidecar at
    all (a lake from before sidecars) is listed in ``unsigned``, not a problem: nothing contradicts it."""
    problems: list[str] = []
    unsigned: list[str] = []
    snaps = sorted(p for p in (root / "db").glob("*.duckdb")) if (root / "db").is_dir() else []

    def check(f: Path) -> None:
        side = f.with_name(f.name + ".sha256")
        if not side.is_file():
            unsigned.append(str(f.relative_to(root)))
        elif _sidecar_sha(side.read_bytes()) != _sha_file(f):
            problems.append(f"{f.relative_to(root)}: content does not match its .sha256 sidecar")

    for db in snaps:
        check(db)
        folder = root / "parquet" / f"snapshot={db.stem}"
        files = sorted(folder.glob("*.parquet"))
        if not files:
            problems.append(f"parquet/snapshot={db.stem}: missing or empty")
        for f in files:
            check(f)
    return {"snapshots": len(snaps), "problems": problems, "unsigned": len(unsigned)}


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


# ------------------------------------------------------------------------------------------------ the stream check
#: what the last backup's check read (members and bytes): for a test and for a measurement, not a record
LAST_CHECK: dict[str, int] = {}


class _StreamCheck:
    """NEW-B-21 (D-662): the plain tar stream, read as a restore reads it, while it is written.

    Every byte the tar writer gives the compressor also goes down a pipe to a thread that reads it as a tar: a file
    member is hashed, a link member takes what it links to (a restore makes it that file), a later member of a name
    replaces an earlier one (a restore extracts the later). :meth:`problems` then compares what a restore would
    get with the manifest. No key is needed: this is before encryption. The pipe is the only buffer, so the writer
    waits for the reader and memory does not grow with the backup."""

    def __init__(self, out: Any) -> None:
        self._out = out
        r, self._w = os.pipe()
        with contextlib.suppress(OSError, AttributeError):  # a pipe as wide as one chunk: fewer hand-overs (Linux)
            import fcntl

            fcntl.fcntl(self._w, fcntl.F_SETPIPE_SZ, CHUNK)
        self.seen: dict[str, tuple[str, int]] = {}
        self.other: dict[str, str] = {}
        self.error: BaseException | None = None
        self.bytes = 0
        self._thread = threading.Thread(target=self._read, args=(r,), name="backup-check", daemon=True)
        self._thread.start()

    def write(self, data: bytes) -> int:
        self._out.write(data)
        view = memoryview(data)
        while view:
            view = view[os.write(self._w, view) :]
        return len(data)

    def _read(self, r: int) -> None:
        with os.fdopen(r, "rb") as fh:
            try:
                with tarfile.open(fileobj=fh, mode="r|") as tar:
                    for m in tar:
                        if m.isreg():
                            h, n = hashlib.sha256(), 0
                            src = tar.extractfile(m)
                            while src is not None and (b := src.read(CHUNK)):
                                h.update(b)
                                n += len(b)
                            self.seen[m.name] = (h.hexdigest(), n)
                            self.bytes += n
                        elif m.islnk():
                            self.seen[m.name] = self.seen.get(m.linkname, ("a link to a member that is not there", -1))
                        else:
                            self.other[m.name] = "not a file"
            except BaseException as e:  # reported by problems(); the writer must never be left waiting
                self.error = e
            while fh.read(CHUNK):
                pass

    def close(self) -> None:
        if self._w >= 0:
            os.close(self._w)
            self._w = -1
            self._thread.join()

    def problems(self, manifest: Mapping[str, Any]) -> tuple[list[str], list[str]]:
        """(changed, unlisted): the manifest's files a restore would not get as listed, and members it does not
        list. Call after the tar is closed."""
        self.close()
        if self.error is not None:
            raise BackupError(f"the backup's own stream could not be read back ({type(self.error).__name__})")
        files, sizes = manifest["files"], manifest["sizes"]
        bad = sorted(rel for rel, sha in files.items() if self.seen.get(rel) != (sha, sizes.get(rel)))
        extra = sorted((set(self.seen) | set(self.other)) - set(files) - {"manifest.json"})
        LAST_CHECK.clear()
        LAST_CHECK.update(files=len(files), bytes=self.bytes)
        return bad, extra


# ------------------------------------------------------------------------------------------------ compression
@contextlib.contextmanager
def _tar_writer(enc: Any, compression: str, checks: list[_StreamCheck] | None = None) -> Iterator[tarfile.TarFile]:
    """A streaming tar into ``enc``: zstd -3 on every core (D-149), or gzip (the format before D-149, kept only so
    the restore of an old backup stays tested). The compressor's last frame is written before the caller seals the
    final encrypted chunk. ``checks`` (D-662): the plain stream's check is put in it (zstd only: gzip is compressed
    inside the tar writer, and no backup is made with it but a test's)."""
    if compression == "zstd":
        cctx = zstandard.ZstdCompressor(level=ZSTD_LEVEL, threads=-1)
        with cctx.stream_writer(enc, closefd=False) as zw:
            out: Any = zw
            if checks is not None:
                out = _StreamCheck(zw)
                checks.append(out)
            try:
                with tarfile.open(fileobj=out, mode="w|") as tar:
                    yield tar
            finally:
                if out is not zw:
                    out.close()
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
    restic_secrets: Path | None = None,
) -> list[Path]:
    """Write one encrypted backup to every target directory; return the files written. With ``restic_secrets`` (the
    secrets folder holding ``restic.key`` under the unsealed KEK; PERF-010, D-968), the lake's served files go to a
    restic repository on each target (``trialbox-restic``, with the escrow file beside it) and the sealed file keeps
    their manifest; the other targets' repositories are filled by ``restic copy``, and ``keep`` applies to the
    snapshots as to the files."""
    env = dict(os.environ if env is None else env)
    if not targets:
        raise BackupError("no --to target")
    if compression not in ("zstd", "gzip"):
        raise BackupError(f"unknown compression {compression!r}")
    dirs = dict(dirs if dirs is not None else layout(env))
    host = Path(env["TB_PG_DUMP_DIR"]) / HOST if env.get("TB_PG_DUMP_DIR") else None
    if host is not None and host.is_dir() and HOST not in dirs:  # D-274 (DI-12): the nightly run's host files
        dirs[HOST] = host
    when = now or datetime.now(UTC)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    site = site or env.get("TB_SITE_ID") or socket.gethostname()
    prefix = f"trialbox-{_sched.safe(site)}-"
    name = f"{prefix}{stamp}{SUFFIX}"
    recipient = load_public(public_key)
    srcs = db_sources(env)
    repos: list[_rr.Repo] = []
    if restic_secrets is not None:
        try:  # before anything is written: a KEK the custodians' shares do not cover writes nothing (D-968)
            pw = _rr.password(restic_secrets, env)
            for t in targets:
                Path(t).mkdir(parents=True, exist_ok=True)
                _rr.escrow_copy(restic_secrets, Path(t), _rr.escrow_name(site))
            repos = [_rr.Repo(Path(t) / _rr.repo_dir(site), pw, env) for t in targets]
            repos[0].ensure()
            for r in repos[1:]:
                r.ensure(like=repos[0])
        except (_rr.ResticError, _K.KekError, KeyMissingError, OSError) as e:  # named, never with a key in it
            raise BackupError(f"incremental backup: {e}") from e
    manifest: dict[str, Any] = {"layout": LAYOUT, "hashing": "stream", "created_at": when.isoformat(timespec="seconds"),
                                "site": site, "compression": f"{compression}-{ZSTD_LEVEL}" if compression == "zstd"
                                else compression, "databases": {}, "dirs": {}, "files": {}, "sizes": {},
                                "excluded": {}, "refdata_packs": []}  # fmt: skip
    first_done = False
    try:
        with tempfile.TemporaryDirectory(prefix="tb-backup-") as tmp:
            work = Path(tmp)
            os.chmod(work, 0o700)
            snaps = {}
            for src in srcs:
                snap = take_snapshot(src, work, env)
                snaps[src.name] = snap
                manifest["databases"][src.name] = {
                    "schemas": list(src.schemas), "rows_from": snap["rows_from"], "rows": snap["rows"],
                    "excluded_tables": snap["excluded_tables"], "refdata_schema": snap["refdata_schema"],
                    "site_rows": snap["site_rows"], "row_hash": snap.get("row_hash", _sched.ROW_HASH),
                    "snapshot_at": snap.get("snapshot_at"),
                }  # fmt: skip
                if snap["refdata_schema"]:
                    manifest["refdata_packs"] = snap["packs"]
            first = Path(targets[0])
            first.mkdir(parents=True, exist_ok=True)
            part = first / (name + ".part")
            meta = {"site": site, "created_at": manifest["created_at"], "layout": LAYOUT, "compression": compression}
            checks: list[_StreamCheck] = []
            with part.open("wb") as raw:
                hw = _HashWriter(raw)
                enc = _Encryptor(hw, recipient, meta)
                with _tar_writer(enc, compression, checks) as tar:
                    for src in srcs:
                        arc = f"db/{src.name}.dump"
                        manifest["files"][arc], manifest["sizes"][arc] = _add(tar, work / f"{src.name}.dump", arc)
                        if snaps[src.name]["refdata_schema"]:
                            for t, f in sorted(snaps[src.name]["site_files"].items()):
                                arc = f"db/{src.name}.site.{t}.copy"
                                manifest["files"][arc], manifest["sizes"][arc] = _add(tar, f, arc)
                    for dname, root in sorted(dirs.items()):
                        if dname == "lake":
                            n, left = _add_lake(tar, root, manifest, repos[0] if repos else None)
                            manifest["dirs"][dname] = {"path": str(root), "files": n}
                            if left:
                                manifest["excluded"][dname] = left
                            continue
                        rels, left = select_files(dname, root)
                        head, lengths = _audit_moment(root) if dname == "audit" else (None, {})
                        if dname == "audit":  # what the moment saw, even what the listing before it did not
                            rels = sorted({*rels, *lengths, *(["HEAD.json"] if head is not None else [])})
                        n = 0
                        upto = _UPTO.set({f"dirs/{dname}/{rel}": end for rel, end in lengths.items()})
                        for rel in rels:
                            arc = f"dirs/{dname}/{rel}"
                            try:
                                if dname == "audit" and rel == "HEAD.json" and head is not None:
                                    got = _add_read(tar, root / rel, arc, head)
                                else:
                                    got = _add(tar, root / rel, arc)
                                manifest["files"][arc], manifest["sizes"][arc] = got
                            except (
                                FileNotFoundError
                            ):  # removed since the listing (a retention prune): not in the backup
                                left["removed while the backup ran"] = left.get("removed while the backup ran", 0) + 1
                                continue
                            n += 1
                        _UPTO.reset(upto)
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
            for check in checks:
                # NEW-B-21 (D-662): what a restore would get, against the manifest, before the file gets its name. The
                # nightly has no private key and never opened what it wrote: a wrong manifest was recorded as good
                try:
                    bad, extra = check.problems(manifest)
                except BackupError:
                    part.unlink(missing_ok=True)
                    raise
                if bad or extra:
                    part.unlink(missing_ok=True)
                    # the names first, the verdict and the counts last: what records an error keeps its end (the nightly
                    # its last 400 characters), and the verdict must never be the part that is cut off
                    names = (_named("changed", bad) + _named("unlisted", extra)).removeprefix("; ")
                    raise BackupError(
                        f"{names}; the backup was not written: its content does not match its manifest "
                        f"({len(bad)} changed, {len(extra)} unlisted)"
                    )
            snapshot = str((manifest.get("restic") or {}).get("snapshot") or "")
            sha = hw.sha.hexdigest()
            final = first / name
            part.rename(final)
            if _sha_file(final) != sha:  # read back from the first target too, as from every other one
                raise BackupError(f"{final} does not read back as written")
            if snapshot:  # D-968: which snapshot this file needs, written before the sidecar marks it complete
                (first / (name + SNAPSHOT_SUFFIX)).write_text(snapshot + "\n", encoding="utf-8")
            _write_sidecar(final, sha)
            first_done = True
            written = [final]
            for i, t in enumerate(targets[1:], start=1):
                t = Path(t)
                t.mkdir(parents=True, exist_ok=True)
                if snapshot:  # review of D-968: the target's repository holds the snapshot before its file is complete
                    try:
                        repos[i].copy_from(repos[0], snapshot)
                    except _rr.ResticError as e:
                        raise BackupError(f"incremental backup: {e}; {t} got no copy tonight (the first target's "
                                          f"{final.name} is whole)") from e  # fmt: skip
                    (t / (name + SNAPSHOT_SUFFIX)).write_text(snapshot + "\n", encoding="utf-8")
                tpart = t / (name + ".part")
                if _copy_hashed(final, tpart) != sha or _sha_file(tpart) != sha:  # written, then read back from t
                    tpart.unlink(missing_ok=True)
                    raise BackupError(f"copy to {t} does not match")
                tpart.rename(t / name)
                _write_sidecar(t / name, sha)
                written.append(t / name)
    except BaseException:
        if repos and not first_done:  # review of D-968: no sealed file names tonight's snapshot: forget it now
            _forget_quietly(repos[0], str((manifest.get("restic") or {}).get("snapshot") or ""))
        raise
    for t in targets:
        prune(Path(t), keep, prefix)
    problems = []
    for t, r in zip(targets, repos, strict=False):  # D-968: keep exactly the snapshots the kept files name
        keep_ids = set()
        for f in Path(t).glob(f"{prefix}*{SUFFIX}{SNAPSHOT_SUFFIX}"):
            if (f.parent / f.name[: -len(SNAPSHOT_SUFFIX)]).is_file():
                keep_ids.add(f.read_text(encoding="utf-8").strip())
            else:
                f.unlink(missing_ok=True)  # its file was pruned
        try:
            r.forget_except(keep_ids, tag=_rr.LAKE_TAG)
        except _rr.ResticError as e:
            problems.append(f"{t}: {e}")
    if problems:
        raise BackupError("incremental backup: the sealed files were written, but old snapshots were not forgotten: "
                          + "; ".join(problems))  # fmt: skip
    return written


# ------------------------------------------------------------------------------------------------ verify / restore
NAMED = 10  # how many file names a refusal lists before "and N more": a line a person reads, not a limit of work


def _named(what: str, names: Iterable[str]) -> str:
    listed = sorted(names)
    if not listed:
        return ""
    more = f" and {len(listed) - NAMED} more" if len(listed) > NAMED else ""
    return f"; {what}: {', '.join(listed[:NAMED])}{more}"


_NOTHING = hashlib.sha256(b"").hexdigest()


def _second_names(into: Path, manifest: dict[str, Any], bad: list[str]) -> list[str]:
    """``bad`` without the entries that are the fault of backups written before NEW-B-17 (D-537), which are put right
    in ``manifest``.

    Such a backup stored the second name of one file (a hard link) as a link with no bytes and listed it with the
    hash of nothing and size 0; the nightly, which has no private key, recorded it as good. Its bytes are whole: the
    extraction made the name a link to the first one. An entry is read so only when it is exactly that: the hash of
    nothing, size 0, and the extracted file is the same file as a listed one whose own hash holds. It then takes that
    one's hash and size. Anything else stays a mismatch."""
    wrong = set(bad)
    maybe = [
        rel
        for rel in bad
        if manifest["files"][rel] == _NOTHING
        and manifest.get("sizes", {}).get(rel) == 0
        and (into / rel).is_file()
        and (into / rel).stat().st_nlink > 1
    ]
    if not maybe:
        return bad
    whole: dict[tuple[int, int], str] = {}
    for rel in manifest["files"]:
        if rel not in wrong and (into / rel).is_file():
            st = (into / rel).stat()
            whole[(st.st_dev, st.st_ino)] = rel
    for rel in maybe:
        st = (into / rel).stat()
        first = whole.get((st.st_dev, st.st_ino))
        if first is not None:
            manifest["files"][rel], manifest["sizes"][rel] = manifest["files"][first], manifest["sizes"][first]
            wrong.discard(rel)
    return [rel for rel in bad if rel in wrong]


def unpack(
    file: Path, key: Path, into: Path, *, restic_pw: str | None = None, lake_from_restic: bool = True
) -> dict[str, Any]:
    """Decrypt and extract ``file`` into ``into``; check every hash against the manifest; return the manifest. A
    restic backup's lake comes from the repository beside ``file`` with ``restic_pw`` (D-968), checked against the
    sealed manifest; ``lake_from_restic=False`` gives the sealed file's content only.

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
        owners: dict[str, list[int]] = {}
        try:
            with _tar_reader(reader, header) as tar:
                tar.extractall(into, filter="data")
                # D-724 (DATA-010): the ``data`` filter does not write each member's owner; the members read keep it
                owners = {m.name: [m.uid, m.gid, m.mode] for m in tar.getmembers()}
        except (tarfile.TarError, zstandard.ZstdError, EOFError) as e:
            raise BackupError(f"backup is damaged: its content cannot be read ({type(e).__name__})") from e
        while reader.read(CHUNK):  # the rest after the tar's end: authenticated to the final chunk all the same
            pass
    want = read_sidecar(file)
    if want is not None and want != hr.sha.hexdigest():
        raise BackupError(f"{file.name} does not match its .sha256 sidecar")
    manifest: dict[str, Any] = json.loads((into / "manifest.json").read_text(encoding="utf-8"))
    bad = [rel for rel, sha in manifest["files"].items() if not (into / rel).is_file() or _sha_file(into / rel) != sha]
    bad = _second_names(into, manifest, bad)
    extra = {str(p.relative_to(into)) for p in into.rglob("*") if p.is_file() and p.name != "manifest.json"} - set(
        manifest["files"]
    )
    if bad or extra:
        # NEW-B-14: which files, by their path inside the backup (a name, never content): "1 changed" alone left
        # a failed drill with nothing to look at
        raise BackupError(
            f"backup content does not match its manifest: {len(bad)} changed, {len(extra)} unlisted"
            + _named("changed", bad)
            + _named("unlisted", extra)
        )
    if "restic" in manifest and lake_from_restic:
        _restore_lake_from_restic(file, into, manifest, restic_pw)
    manifest["_sha256"] = hr.sha.hexdigest()
    manifest["_owners"] = owners  # not in the signed manifest: read from the tar members, as the files are
    return manifest


def verify(file: Path, key: Path, *, restic_pw: str | None = None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="tb-verify-") as tmp:
        m = unpack(file, key, Path(tmp), restic_pw=restic_pw)
    return {"ok": True, "site": m["site"], "created_at": m["created_at"], "layout": m.get("layout", 1),
            "files": len(m["files"]), "sha256": m["_sha256"], "excluded": m.get("excluded", {}),
            "refdata_packs": m.get("refdata_packs", []),
            "databases": {k: sum(r[0] for r in v["rows"].values()) for k, v in m["databases"].items()},
            "restic": _restic_said(m)}  # fmt: skip


def _restic_said(m: dict[str, Any]) -> dict[str, Any] | None:
    """D-978: a restic backup's lake as the verify restored and checked it (the snapshot, how many served files),
    so a reader sees the lake came back from restic and was not empty; None for a single ``.tbbak``."""
    rec = m.get("restic")
    if not rec:
        return None
    return {"snapshot": str(rec.get("snapshot") or ""), "files": len(rec.get("files") or {})}


def check(file: Path) -> dict[str, Any]:
    """Check a backup without the private key (D-178, the console's "Check"): the header reads, every chunk is whole,
    the last chunk is marked and nothing follows it. It finds a cut, truncated or half-written file; only the key
    (``backup-verify``) proves the content. Returns the header's facts, the chunk count, the size and the sha256."""
    n, last = 0, False
    with file.open("rb") as fh:
        header, _ = read_header(fh)
        while True:
            head = fh.read(5)
            if not head:
                break
            if len(head) < 5 or last:
                raise BackupError("backup is damaged (data after the last chunk or a cut chunk header)")
            size, last = struct.unpack(">I?", head)
            if size > CHUNK + 64 or len(fh.read(size)) != size:
                raise BackupError("backup is cut short")
            n += 1
    if not last:
        raise BackupError("backup is cut short (no final chunk)")
    return {"ok": True, "site": header.get("site", ""), "created_at": header.get("created_at", ""),
            "recipient": header.get("recipient", ""), "compression": header.get("compression", "gzip"),
            "chunks": n, "bytes": file.stat().st_size, "sha256": _sha_file(file)}  # fmt: skip


RESTORE_MAX_AGE_DAYS = 14.0  # D-274: an older backup restores only with --older-ok (the default keep is 14 nights)
HOST = "host"  # D-274 (DI-12): deploy/.env, settings, deploy/site and the pgBackRest cipher; restored only on request


def _box_holds_data(srcs: Sequence[DbSource], targets: Mapping[str, Path]) -> bool:
    """True when any database has a table or any data directory has a file: a restore would replace something."""
    if any(_walk(p) for n, p in targets.items() if n != HOST):
        return True
    import psycopg

    for src in srcs:
        likes = [p.replace("*", "%") for p in src.schemas] or ["%"]
        with psycopg.connect(src.dsn, autocommit=True) as con:
            row = con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', "
                "'information_schema') AND table_schema LIKE ANY(%s)",
                (likes,),
            ).fetchone()
            if row and row[0]:
                return True
    return False


def keep_copy(env: Mapping[str, str], dirs: Mapping[str, Path], public_key: Path, keep_to: Path, now: datetime) -> Path:
    """An encrypted backup of the box as it is now, before a restore replaces it (D-274, CR-056): every database dumped
    whole (``pg_dump``, or ``TB_PG_DUMP_CMD``) with its rows counted, and every data directory. It is written to
    ``keep_to`` and never pruned; ``trialbox restore <it>`` puts the box back."""
    srcs = db_sources(env)
    with tempfile.TemporaryDirectory(prefix="tb-keep-") as tmp:
        work = Path(tmp)
        os.chmod(work, 0o700)
        for src in srcs:
            dump(src, work / f"{src.name}.dump", env)
        out = backup([keep_to], public_key, env={**env, "TB_PG_DUMP_DIR": str(work)},
                     dirs={k: v for k, v in dirs.items() if k != HOST}, keep=0, now=now)  # fmt: skip
    return out[0]


# D-455 (M3): events whose effect a restore loses when they came after the database snapshot, and whose loss is
# unsafe: an opt-out (the patient comes back into screening), an erasure, a break-glass grant, an EDC signature or
# submission, a consent change. The audit chain is copied after the snapshots, so it still holds them.
REAPPLY_EVENTS = frozenset({
    "console.opt_out", "optout.worker", "screen.opt_out_removed", "screen.opt_out_at_publish", "edc.erase_hidden",
    "console.breakglass_open", "console.breakglass_use", "console.breakglass_review", "console.breakglass_end",
    "edc.sign", "edc.sent", "consent.release", "console.consent_version_override",
})  # fmt: skip


def _parse_ts(v: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(v))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def snapshot_time(manifest: Mapping[str, Any]) -> tuple[datetime, str]:
    """The earliest database snapshot of a backup, and where it comes from (``snapshot_at``; a backup made before
    D-455 has only ``created_at``, the backup's start, which is before its snapshots)."""
    ats = [t for d in manifest.get("databases", {}).values() if (t := _parse_ts(d.get("snapshot_at"))) is not None]
    if ats:
        return min(ats), "snapshot_at"
    made = _parse_ts(manifest.get("created_at")) or datetime.now(UTC)
    return made, "created_at"


def events_to_reapply(audit_dir: Path | None, since: datetime) -> list[dict[str, Any]]:
    """The audit chain's events after ``since`` whose effect the restored databases do not hold (``REAPPLY_EVENTS``):
    time, event and where in the chain (file and line), never the detail (it may name a patient)."""
    out: list[dict[str, Any]] = []
    if audit_dir is None or not Path(audit_dir).is_dir():
        return out
    for f in sorted(Path(audit_dir).rglob("*.jsonl")):
        with contextlib.suppress(OSError):
            for i, ln in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if '"event"' not in ln:
                    continue
                try:
                    rec = json.loads(ln)
                except ValueError:
                    continue
                if not isinstance(rec, dict) or rec.get("event") not in REAPPLY_EVENTS:
                    continue
                ts = _parse_ts(rec.get("ts"))
                if ts is not None and ts > since:
                    out.append({"ts": str(rec["ts"]), "event": rec["event"],
                                "where": f"{f.relative_to(audit_dir)}:{i}"})  # fmt: skip
    return sorted(out, key=lambda e: str(e["ts"]))


NO_REGISTER = "the box holds no register"
RESTORE_STEP_MESSAGE = (
    "This job was running when the backup of {made} was taken, and the box was restored from that backup: it was "
    "interrupted by a restore and is not run again. If it had finished before the restore its results were sent "
    "then; otherwise send the request again."
)


KEPT_BY_RESTORE = frozenset({"console.opt_out", "optout.worker"})  # audit events whose effect the restore keeps
OptOutRow = tuple[str, str, str | None, str | None, str, str]  # pid, action, source, note, by, at


def read_register(src: DbSource) -> tuple[str, list[OptOutRow]]:
    """Every event of the box's opt-out register: ``("", rows)``, or ``(why, [])`` when there is none
    (:data:`NO_REGISTER`) or it cannot be read. The rows stay in this process: never printed, never audited."""
    import psycopg
    from psycopg import sql
    from tb_common.optout import SCHEMA as OPTOUT

    table = sql.Identifier(f"{src.prefix}{OPTOUT}", "optout_events")
    try:
        with psycopg.connect(src.dsn, autocommit=True) as con:
            there = con.execute("SELECT to_regclass(%s)", (table.as_string(con),)).fetchone()
            if there is None or there[0] is None:
                return NO_REGISTER, []
            rows = con.execute(
                sql.SQL("SELECT pid, action, source, note, by, at FROM {} ORDER BY at, id").format(table)
            ).fetchall()
    except psycopg.Error as exc:
        return f"the register could not be read ({type(exc).__name__})", []
    return "", [(str(p), str(a), s, n, str(by), str(at)) for p, a, s, n, by, at in rows]


def count_optouts(rows: Sequence[OptOutRow], since: datetime) -> dict[str, Any]:
    """Counts only of ``rows``: the events, by action, the opt-outs by source, how many the registry's worker
    wrote and how many a person typed, the first and the last time. Never a pseudonym, a note or who typed it."""
    from tb_common.optout import REGISTRY_ACTOR

    later = sorted(
        (at, action, str(source or "other"), by) for _, action, source, _, by, raw in rows
        if (at := _parse_ts(raw)) is not None
    )  # fmt: skip
    by_action: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for _, action, source, _by in later:
        by_action[action] = by_action.get(action, 0) + 1
        if action == "opt_out":
            by_source[source] = by_source.get(source, 0) + 1
    registry = sum(1 for _, _, _, by in later if by == REGISTRY_ACTOR)
    return {
        "readable": True,
        "events": len(later),
        "since": since.isoformat(timespec="milliseconds"),
        "by_action": by_action,
        "by_source": by_source,
        "from_registry": registry,
        "typed": len(later) - registry,
        "first_at": later[0][0].isoformat(timespec="seconds") if later else None,
        "last_at": later[-1][0].isoformat(timespec="seconds") if later else None,
    }


def optouts_after(src: DbSource, since: datetime) -> dict[str, Any]:
    """T-728 (D-493; lifecycle review F-8): what the box's opt-out register holds after ``since``, read before a
    restore replaces it, as :func:`count_optouts` counts it. A register that cannot be read is ``readable: False``
    with the reason, never a count of zero."""
    why, rows = read_register(src)
    if why:
        return {"readable": False, "events": None, "why": why}
    return count_optouts([r for r in rows if (at := _parse_ts(r[5])) is not None and at > since], since)


def keep_optouts(src: DbSource, live: Sequence[OptOutRow]) -> tuple[list[OptOutRow], int]:
    """T-728 review (M1): put back what the restore took out of the register. ``live``: the register's events as
    they were before the restore. Returns the events the restored register did not hold (so: recorded after the
    backup, whatever their clock time: no time is compared) and how many of them were put back.

    Every such **opt-out** is written into the restored register as it was (pseudonym, source, note, who, when).
    A lift is not: a patient whose opt-out was lifted after the backup stays withheld until a person lifts it
    again (the restore fails closed). Run again, it finds them there and adds nothing. One transaction."""
    import psycopg
    from psycopg import sql
    from tb_common.optout import SCHEMA as OPTOUT

    table = sql.Identifier(f"{src.prefix}{OPTOUT}", "optout_events")
    with psycopg.connect(src.dsn) as con:
        there = con.execute("SELECT to_regclass(%s)", (table.as_string(con),)).fetchone()
        if there is None or there[0] is None:
            return list(live), 0  # the backup holds no register: nothing can be put back
        con.execute(sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(table))
        held = {
            (str(p), str(a), str(by), str(at))
            for p, a, by, at in con.execute(sql.SQL("SELECT pid, action, by, at FROM {}").format(table)).fetchall()
        }
        gone = [r for r in live if (r[0], r[1], r[4], r[5]) not in held]
        back = [r for r in gone if r[1] == "opt_out"]
        insert = sql.SQL("INSERT INTO {} (pid, action, source, note, by, at) VALUES (%s,%s,%s,%s,%s,%s)").format(table)
        for row in back:
            con.execute(insert, row)
        con.commit()
    return gone, len(back)


def optouts_ok(lost: Mapping[str, Any]) -> bool:
    """Whether the restore left the opt-outs whole: the register was not replaced, or every event it held after the
    backup was read, every opt-out among them put back, and no lift a person typed was reverted."""
    state = lost.get("state")
    if state == "not_replaced":
        return True
    return state == "counted" and not lost.get("not_kept") and not lost.get("lifts_reverted")


def fail_running_jobs(src: DbSource, when: datetime, made: str) -> list[dict[str, str]]:
    """T-728 (D-493; lifecycle review F-11): the restored queue holds the jobs that were running at the backup as
    running, and the orchestrator's restart recovery would run them again. Each is set to ``failed`` with the step it
    was in and a message; a job that was queued and had not started, or waits for an approval, is left alone.
    Returns the jobs failed (id, type, step). One statement: all of them or none."""
    import psycopg
    from orchestrator.db import SCHEMA_NAME as ORCH
    from psycopg import sql

    table = sql.Identifier(f"{src.prefix}{ORCH}", "jobs")
    ts = when.isoformat(timespec="seconds")
    fail = sql.SQL(
        "WITH was AS (SELECT job_id, state FROM {t} WHERE queued = 0 AND state NOT IN "
        "('done','failed','awaiting_approval') FOR UPDATE) UPDATE {t} j SET state = 'failed', "
        "updated_at = %s::text, data = (j.data::jsonb || jsonb_build_object('state', 'failed', "
        "'updated_at', %s::text, 'error', jsonb_build_object('step', was.state, 'message', %s::text)))::text "
        "FROM was WHERE j.job_id = was.job_id RETURNING j.job_id, j.type, was.state"
    ).format(t=table)
    with psycopg.connect(src.dsn) as con:
        there = con.execute("SELECT to_regclass(%s)", (table.as_string(con),)).fetchone()
        if there is None or there[0] is None:
            return []
        rows = con.execute(fail, (ts, ts, RESTORE_STEP_MESSAGE.format(made=made))).fetchall()
        answers = sql.Identifier(f"{src.prefix}{ORCH}", "judge_answers")
        kept = con.execute("SELECT to_regclass(%s)", (answers.as_string(con),)).fetchone()
        if kept is not None and kept[0] is not None:
            # T-689 (D-456) keeps a running job's model answers (note quotes) to replay them: a failed job has no
            # use for them, and they must not wait in a restored box for the orchestrator's next start
            con.execute(sql.SQL(
                "DELETE FROM {a} a WHERE NOT EXISTS (SELECT 1 FROM {t} j WHERE j.job_id = a.job_id AND "
                "j.state NOT IN ('done','failed'))").format(a=answers, t=table))  # fmt: skip
        con.commit()
    return sorted(({"job_id": str(j), "type": str(t), "step": str(st)} for j, t, st in rows), key=lambda r: r["job_id"])


HOLD_FLAG = "screening.after_restore"  # tb_common.flags: the hold a restore that is not complete leaves (D-522)


def _hold_flags(env: Mapping[str, str], audit_dir: Path | None) -> Any:
    from tb_common.audit import AuditLog
    from tb_common.flags import Flags

    log = None
    if audit_dir is not None:
        log = AuditLog(Path(audit_dir), tz=env["TB_TZ"]) if env.get("TB_TZ") else AuditLog(Path(audit_dir))
    return Flags(url=env.get("TB_DB_URL"), audit=log)


def hold_standing(env: Mapping[str, str]) -> bool:
    """Whether the box is held now (read before the trial database is replaced). A hold that cannot be read is
    taken as standing: the restore then leaves the box held, and a person releases it."""
    try:
        return bool(_hold_flags(env, None).row(HOLD_FLAG) == "held")
    except LookupError:  # no trial database configured: nothing was held
        return False
    except Exception:
        return True


def hold_screening(env: Mapping[str, str], audit_dir: Path | None, reason: str) -> str:
    """NEW-B-3 (D-522): hold the box's list jobs (the audited flag ``screening.after_restore``, set to ``held``)
    until the restore ends complete or a person releases the hold with a reason. Returns ``held``, or ``NOT set:
    <why>`` when the flag could not be written (no audit directory: a flag change must be audited; a database
    error). Never raises: the restore's own report says what happened. ``reason`` holds counts and times only."""
    if audit_dir is None:
        return "NOT set: no audit directory in the layout (or TB_AUDIT_DIR); a hold must be audited"
    try:
        flags = _hold_flags(env, audit_dir)
        if flags.row(HOLD_FLAG) != "held":  # held already (the backup was taken under a hold): it stays
            try:
                flags.set(HOLD_FLAG, "held", actor=env.get("TB_RESTORE_ACTOR") or "trialbox restore", reason=reason)
            except ValueError:
                if flags.row(HOLD_FLAG) != "held":  # not "already held" (set by another writer meanwhile)
                    raise
        return "held"
    except Exception as exc:
        return f"NOT set: {type(exc).__name__}"
    finally:
        with contextlib.suppress(OSError):
            _own_writes(audit_dir)  # D-724: the flag's audit event was written as root


def release_own_hold(env: Mapping[str, str], audit_dir: Path | None, reason: str) -> str:
    """The restore ended complete and the hold is its own (none stood before it, no earlier restore's set-aside
    copy is on the box): the restore takes it off again. Returns ``released``, or ``held`` when it could not (the
    box then stays held, which is the safe side)."""
    try:
        _hold_flags(env, audit_dir).set(
            HOLD_FLAG, "released", actor=env.get("TB_RESTORE_ACTOR") or "trialbox restore", reason=reason
        )
        return "released"
    except Exception:
        return "held"
    finally:
        with contextlib.suppress(OSError):
            _own_writes(audit_dir)  # D-724: the flag's audit event was written as root


def _audit(dirs: Mapping[str, Path], env: Mapping[str, str], event: str, sha: str, detail: dict[str, Any]) -> str:
    """Append ``event`` to the box's audit log (the ``audit`` directory, else ``TB_AUDIT_DIR``); returns where, or
    why not."""
    where = dirs.get("audit") or (Path(env["TB_AUDIT_DIR"]) if env.get("TB_AUDIT_DIR") else None)
    if where is None:
        return "not written: no audit directory in the layout (or TB_AUDIT_DIR)"
    from tb_common.audit import AuditLog

    log = AuditLog(Path(where), tz=env["TB_TZ"]) if env.get("TB_TZ") else AuditLog(Path(where))
    log.append(event, actor=env.get("TB_RESTORE_ACTOR") or "trialbox restore", input_sha=sha, detail=detail)
    _own_writes(Path(where))  # D-724: also on a failed restore's way out
    return str(where)


#: D-724 (DATA-011): the services a restore leaves running, and its refusal while any other runs. They live in
#: box_restore.py (H-100): the host's own restore step asks compose before it starts, with the standard library only
RESTORE_MAY_RUN = _box_restore.RESTORE_MAY_RUN
_only_the_database_runs = _box_restore.only_the_database_runs


def _is_root() -> bool:
    return os.geteuid() == 0


def _chown(path: Path, uid: int, gid: int) -> None:
    os.chown(path, uid, gid, follow_symlinks=False)


def _uid_gid(path: Path) -> tuple[int, int]:
    st = os.lstat(path)
    return st.st_uid, st.st_gid


def _own_writes(folder: Path | None) -> None:
    """D-724: what this process wrote as root in the box's audit folder (an audit event, the writer's lock file, a
    new day file) is given to the folder's owner: the audit writer, another user, could not write the day's chain
    after it. Files that belong to someone else are left as they are."""
    if folder is None or not _is_root() or not Path(folder).is_dir():
        return
    owner = _uid_gid(Path(folder))
    me = os.geteuid()
    if owner[0] == me:
        return
    for p in Path(folder).rglob("*"):
        if not p.is_symlink() and _uid_gid(p)[0] == me:
            _chown(p, owner[0], owner[1])


def _give_back_owners(
    dest: Path, dname: str, owners: Mapping[str, list[int]], top: tuple[int, int, int] | None, aside: Path | None
) -> None:
    """D-724 (DATA-010): a restore run as root made every file and folder root's, folders 0755 and files without
    group write; the services, which run as their own user, could not write their volumes after it. Each file gets
    the owner and mode of its backup member (never a set-id bit); each folder the owner and mode of the same folder
    it replaced (else of the folder at the volume's top); a file the restore wrote itself (its audit event, the
    writer's lock file) the top folder's owner. Owners only as root (a user who is not root cannot give a file away)."""
    root = _is_root()
    for p in [dest, *sorted(dest.rglob("*"))]:
        if p.is_symlink():
            continue
        rel = p.relative_to(dest)
        if p.is_dir():
            was = aside / rel if aside is not None and str(rel) != "." else None
            if was is not None and was.is_dir():
                st = was.stat()
                like: tuple[int, int, int] | None = (st.st_uid, st.st_gid, st.st_mode)
            else:
                like = top
            if like is not None:
                p.chmod(like[2] & 0o777)
                if root:
                    _chown(p, like[0], like[1])
            continue
        own = owners.get(f"dirs/{dname}/{rel}")
        if own is not None:
            if len(own) > 2:
                p.chmod(int(own[2]) & 0o777)
            if root:
                _chown(p, int(own[0]), int(own[1]))
        elif root and top is not None:
            _chown(p, top[0], top[1])


class RestoreInterrupted(BaseException):
    """H-100 (F3): a signal (SIGTERM, SIGHUP) stopped the restore; it is undone like any failure."""


def _signals_raise() -> Callable[[], None]:
    """While a restore changes the box, SIGTERM and SIGHUP (``docker run`` forwards them; a closed session sends
    the second) raise :class:`RestoreInterrupted`, so the restore is put back, held and audited like any failure.
    Returns the function that puts the old handlers back. Only in the main thread (signals are delivered there)."""
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        return lambda: None

    def stop(signum: int, _frame: Any) -> None:
        raise RestoreInterrupted(f"the restore was stopped by signal {signal.Signals(signum).name}")

    old = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGHUP)}

    def back() -> None:
        for sig, h in old.items():
            signal.signal(sig, h)

    return back


@contextlib.contextmanager
def _signals_ignored() -> Iterator[None]:
    """H-100 (review R1): while a failed restore puts the box back, SIGINT, SIGTERM and SIGHUP are ignored: one
    Ctrl-C under ``docker run`` can arrive twice (the engine passes SIGINT on, then the host's step sends SIGTERM), and
    a second signal must never abandon the put-back half way. The old handlers come back after it."""
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        yield
        return
    old = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        yield
    finally:
        for sig, h in old.items():
            signal.signal(sig, h)


def _db_bytes(src: DbSource) -> int:
    import psycopg

    with psycopg.connect(src.dsn, autocommit=True) as con:
        row = con.execute("SELECT pg_database_size(current_database())").fetchone()
    return int(row[0]) if row else 0


def _pre_restore_dumps(srcs: Sequence[DbSource], into: Path, env: Mapping[str, str]) -> dict[str, Path]:
    """H-100 (F2): each database a restore replaces, dumped as it is now (``pg_dump``, as :func:`dump`; never the
    update path's ``TB_PG_DUMP_DIR``), before anything changes. Refused, nothing changed, when the folder cannot hold
    them: a dump is at most about the database's own size (``pg_database_size``), which is what is asked for."""
    into.mkdir(mode=0o700, parents=True, exist_ok=True)
    need = sum(_db_bytes(s) for s in srcs)
    free = shutil.disk_usage(into).free
    if free < need:
        raise BackupError(
            f"the databases are first copied aside, to be put back if the restore fails: that needs up to "
            f"{need / 1e9:.1f} GB in {into.parent}, {free / 1e9:.1f} GB is free. Nothing was changed"
        )
    own = {k: v for k, v in env.items() if k != "TB_PG_DUMP_DIR"}
    out = {}
    for src in srcs:
        out[src.name] = into / f"{src.name}.dump"
        dump(src, out[src.name], own, keep_owners=True)
    return out


def _put_back(
    srcs: Mapping[str, DbSource],
    replaced: Sequence[str],
    pre: Mapping[str, Path],
    moved: Sequence[tuple[Path, Path | None, bool, tuple[int, int, int] | None]],
    env: Mapping[str, str],
) -> tuple[bool, str]:
    """H-100 (F2): the folders and the databases a failed restore changed, put back as they were. Returns whether
    all of it went back, and the box's state in words (what went back, what did not)."""
    bad: list[str] = []
    for dest, aside, existed, top in reversed(list(moved)):
        try:  # each step on its own: whatever stops one (BaseException included), the others still go back
            if dest.exists():
                shutil.rmtree(dest)
            if aside is not None and aside.exists():
                aside.rename(dest)
            elif existed:  # review R4: an empty folder back with its own owner and mode
                dest.mkdir(parents=True, exist_ok=True)
                if top is not None:
                    dest.chmod(top[2] & 0o777)  # never a set-id bit
                    if _is_root():
                        _chown(dest, top[0], top[1])
        except BaseException as e:
            bad.append(f"folder {dest.name} ({getattr(e, 'strerror', None) or type(e).__name__})")
    for name in reversed(list(replaced)):
        try:
            restore_db(srcs[name], pre[name], env, keep_owners=True)
        except BaseException as e:  # named, never a URL
            bad.append(f"database {name} ({type(e).__name__})")
    if bad:
        return False, ("NOT put back as it was: " + ", ".join(bad) + " may be half restored or empty; do not start "
                       "the services")  # fmt: skip
    what = ", ".join([*(f"database {n}" for n in replaced), *(f"folder {d.name}" for d, _a, _e, _t in moved)])
    return True, f"put back as it was before the restore ({what or 'nothing had changed'})"


def _keep_dumps(pre: Mapping[str, Path], keep_to: Path | None, stamp: str) -> Path | None:
    """Review R3: the copy of the databases a put-back could not finish from is the one exact copy of the box as it
    was: kept (``--keep-to``, else beside the temporary folder), readable by its owner alone, and named."""
    where = (Path(keep_to) if keep_to is not None else Path(tempfile.gettempdir())) / f"pre-restore-dumps-{stamp}"
    try:
        where.mkdir(mode=0o700, parents=True, exist_ok=True)
        for f in pre.values():
            if f.is_file():
                shutil.move(str(f), where / f.name)
    except BaseException:
        return None
    return where


def _undo_restore(e: BaseException, srcs: Mapping[str, DbSource], replaced: Sequence[str], pre: Mapping[str, Path],
                  moved: Sequence[tuple[Path, Path | None, bool, tuple[int, int, int] | None]],
                  env: Mapping[str, str], targets: Mapping[str, Path], sha: str, base: Mapping[str, Any],
                  copy: Path | None, hold: str, hold_dir: Path | None, hold_reason: str, wf_restored: bool,
                  keep: Callable[[], None], keep_to: Path | None = None, stamp: str = "") -> BackupError:  # fmt: skip
    """H-100 (F2, F3): a restore that failed or was stopped after its first change: put back, held, audited, and the
    error the command says (with ``state``: ``rolled_back`` or ``not_rolled_back``)."""
    ok, words = _put_back(srcs, replaced, pre, moved, env)
    if not ok and wf_restored:  # the live register is gone: a second run could not read them any more (review H2)
        with contextlib.suppress(Exception):
            keep()
    if ok:  # NEW-B-3 (D-522): the box is held, on the databases it has again
        hold = hold_screening(env, hold_dir, f"{hold_reason}; it failed: {words}")
    else:  # review R5: the hold is a row of a database that is not whole
        hold = "unknown (the trial database is not whole)"
        kept = _keep_dumps(pre, keep_to, stamp)
        words += (
            (f"; the copy of the databases taken before the restore is kept in {kept}: pg_restore it to put them back")
            if kept
            else "; the copy of the databases taken before the restore could not be kept"
        )
    why = str(e) or type(e).__name__
    with contextlib.suppress(Exception):
        _audit(targets, env, "backup.restore_failed", sha,
               {**base, "error": why[-300:], "state": "rolled_back" if ok else "not_rolled_back", "put_back": words,
                "hold": hold})  # fmt: skip
    lost = base.get("optouts_after_backup") or {}
    said = (f"; {lost['events']} opt-out event(s) were recorded on this box after the backup's snapshot"
            if lost.get("events") else "")  # fmt: skip
    back = f"; the box before it is kept in {copy}: trialbox restore {copy} puts it back" if copy else ""
    err = BackupError(f"{why}; the box is {words}; list jobs: {hold}{said}{back}")
    err.dumps_kept = None if ok else words  # type: ignore[attr-defined]
    err.state = "rolled_back" if ok else "not_rolled_back"  # type: ignore[attr-defined]
    return err


def restore(
    file: Path,
    key: Path,
    env: Mapping[str, str] | None = None,
    dirs: Mapping[str, Path] | None = None,
    now: datetime | None = None,
    refdata_dir: Path | None = None,
    *,
    public_key: Path | None = None,
    keep_to: Path | None = None,
    no_copy: bool = False,
    other_site: bool = False,
    max_age_days: float | None = RESTORE_MAX_AGE_DAYS,
    running: Callable[[], list[str] | None] | None = None,
    restic_pw: str | None = None,
    expect_sha256: str | None = None,
) -> dict[str, Any]:
    """Restore the databases and directories of ``file``, the hospital's own reference rows and, from the pack files
    in ``refdata_dir``, the vendor packs a layout-2 backup leaves out; return what was restored, with rows checked.

    D-274 (CR-056, DI-10): before anything changes, the backup must be of this site (``TB_SITE_ID``; else
    ``other_site``) and at most ``max_age_days`` old (None: any age), and a box that holds data is first kept as an
    encrypted copy to ``keep_to`` with ``public_key`` (refused without them, unless ``no_copy``). Each database is
    emptied of what the backup does not hold, restored and its rows checked before any directory is touched; a
    failure names the kept copy. The restore is audited (``backup.restored``, or ``backup.restore_failed``) in the
    restored audit log. The ``host`` part (deploy/.env, settings) is written only where ``dirs`` names it.

    T-728 (D-493): before the trial database is emptied the box's opt-out register is read. After the rows are
    checked, the opt-outs it held that the restored register does not are put back (:func:`keep_optouts`) and the
    jobs that were running at the backup are failed, not left for the orchestrator to run again (``jobs_failed``;
    :func:`fail_running_jobs`). ``optouts_after_backup`` says, in counts only, what was found, kept and not kept;
    a box with no register to read (a new machine) says ``unknown``, and the restore is then not ``complete``
    (:func:`optouts_ok`). ``--no-copy`` is refused while the register holds events a person typed after the backup.

    ``ok`` is False (and ``refdata.missing`` names them) while a pack could not be loaded again. Rows that differ from
    the manifest fail the restore when the backup counted them in its own snapshot; a backup that counted them on a
    live box (layout 1, or the update path's dumps) gives a warning instead."""
    env = dict(os.environ if env is None else env)
    when = now or datetime.now(UTC)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    warnings: list[str] = []
    if running is not None:  # D-724 (DATA-011): a box's restore, before anything is read or changed
        _only_the_database_runs(running())
    refdata: dict[str, list[str]] = {"reloaded": [], "missing": []}
    with tempfile.TemporaryDirectory(prefix="tb-restore-") as tmp:
        work = Path(tmp)
        manifest = unpack(file, key, work, restic_pw=restic_pw)
        sha = manifest["_sha256"]
        if expect_sha256 is not None and sha != expect_sha256.strip().lower():
            # H-100 (F4): the file the host checked and named, byte for byte, before anything is changed
            raise BackupError(f"{file.name} is not the backup that was named: its sha256 differs from the one recorded "
                              "for it. Nothing was changed")  # fmt: skip
        targets = dict(dirs if dirs is not None else layout(env))
        missing = set(manifest["dirs"]) - set(targets) - {HOST}
        if missing:
            raise BackupError(f"no place to restore directories {sorted(missing)}: pass --dir name=path")
        srcs = {s.name: s for s in db_sources(env)}
        for name in manifest["databases"]:
            if name not in srcs:
                raise BackupError(f"the backup holds database {name} but its URL is not set")
        here = env.get("TB_SITE_ID") or ""
        if here and manifest["site"] != here and not other_site:
            raise BackupError(f"this backup is of site {manifest['site']!r}, this box is {here!r}: add --other-site "
                              "only to move a site to new hardware")  # fmt: skip
        made = datetime.fromisoformat(manifest["created_at"])
        made = made if made.tzinfo else made.replace(tzinfo=UTC)
        age_d = (when - made).total_seconds() / 86400
        if age_d < -1 / 24:
            raise BackupError(f"this backup is dated {manifest['created_at']}, in the future: check the box's clock")
        if max_age_days is not None and age_d > max_age_days:
            raise BackupError(f"this backup is {age_d:.0f} days old (limit {max_age_days:.0f}): add --older-ok to "
                              "restore it anyway; every change since then is lost")  # fmt: skip
        # T-728 (D-493, F-8): what the register holds that the backup does not, read before anything is replaced
        # and before the copy is decided (review M3). ``live``: its events, kept in this process only
        holds = _box_holds_data([srcs[n] for n in manifest["databases"]], targets)
        wf_at = snapshot_time(manifest)[0]
        live: list[OptOutRow] = []
        if "trialbox_wf" not in manifest["databases"]:
            lost: dict[str, Any] = {
                "readable": True,
                "events": 0,
                "state": "not_replaced",
                "why": "the backup holds no trial database: the register is not replaced",
            }
        else:
            wf_at = _parse_ts(manifest["databases"]["trialbox_wf"].get("snapshot_at")) or wf_at
            why, live = read_register(srcs["trialbox_wf"])
            if why == NO_REGISTER or not holds or other_site:
                # review H1: a new machine, or a box that never held a register: what the old box recorded after
                # the backup is not here to be read. "Unknown", never "none"
                live = []
                lost = {"readable": False, "events": None, "state": "unknown", "why": NO_REGISTER,
                        "since": wf_at.isoformat(timespec="milliseconds")}  # fmt: skip
            elif why:
                lost = {"readable": False, "events": None, "state": "unreadable", "why": why}
            else:  # by the clock for now; the exact answer once the restored register can be compared
                lost = {**count_optouts([r for r in live if (at := _parse_ts(r[5])) is not None and at > wf_at],
                                        wf_at), "state": "counted"}  # fmt: skip
        copy: Path | None = None
        copy_note = "the box held no data"
        if holds:
            if no_copy and (lost["state"] == "unreadable" or lost.get("typed")):
                # review M3: without a copy the live register is the only electronic record of them
                raise BackupError(
                    "the opt-out register of this box "
                    + (f"holds {lost['typed']} event(s) a person typed after the backup's snapshot"
                       if lost.get("typed") else f"could not be read ({lost.get('why')})")
                    + ": --no-copy is refused, keep the copy (--public, --keep-to)")  # fmt: skip
            if no_copy:
                copy_note = "the box held data and no copy was kept (--no-copy)"
            elif public_key is None or keep_to is None or not Path(public_key).is_file():
                raise BackupError("the box holds data: a copy is kept before a restore, and that needs the box's "
                                  "public key (--public) and a folder (--keep-to); --no-copy skips it")  # fmt: skip
            else:
                copy = keep_copy(env, targets, Path(public_key), Path(keep_to), when)
                copy_note = f"kept in {copy}"
        base: dict[str, Any] = {
            "file": file.name, "site": manifest["site"], "created_at": manifest["created_at"],
            "kept_copy": str(copy) if copy else None, "copy": copy_note,
            "optouts_after_backup": lost}  # review H2: in the failure record too  # fmt: skip
        kept_done = False

        def keep() -> None:
            """Put the later opt-outs back and replace the count by the exact one (review M1). Once."""
            nonlocal lost, kept_done
            if kept_done or lost["state"] != "counted":
                return
            from tb_common.optout import REGISTRY_ACTOR

            gone, back = keep_optouts(srcs["trialbox_wf"], live)
            opt_outs = sum(1 for r in gone if r[1] == "opt_out")
            lost = {**count_optouts(gone, wf_at), "state": "counted", "kept": back, "not_kept": opt_outs - back,
                    "lifts_reverted": sum(1 for r in gone if r[1] == "lift" and r[4] != REGISTRY_ACTOR)}  # fmt: skip
            base["optouts_after_backup"] = lost
            kept_done = True

        # H-100 (F2): all or nothing. Each database the backup replaces is first dumped here as it is now; whatever
        # fails or stops the restore from the first change on (an error, an interrupt, a signal) puts the databases
        # and the folders back as they were, takes the hold and audits it. Its space is checked before any change
        pre = _pre_restore_dumps([srcs[n] for n in manifest["databases"]], work / "pre-restore", env)
        replaced: list[str] = []
        moved: list[tuple[Path, Path | None, bool, tuple[int, int, int] | None]] = []
        wf_restored = False
        roles: dict[str, str] = {"state": "not_restored"}  # D-573: no trial database in this backup, nothing to move
        jobs_failed: list[dict[str, str]] = []
        checked = {}
        # NEW-B-3 (D-522, review H1): what stands before the trial database is replaced. A hold that stands, or an
        # earlier restore's set-aside audit chain on the box (its events may not be re-applied yet, and this run
        # will not see them), is never taken off by this restore: only a person releases it
        hold_dir = targets.get("audit") or (Path(env["TB_AUDIT_DIR"]) if env.get("TB_AUDIT_DIR") else None)
        carried = hold_standing(env) or bool(
            hold_dir is not None and list(Path(hold_dir).parent.glob(f"{Path(hold_dir).name}.pre-restore-*"))
        )
        hold = "not needed"
        hold_reason = (
            f"restore of the backup of {manifest['created_at']}: held until the restore ends complete or a person "
            "releases it (audit: backup.restored, backup.restore_reapply)"
        )
        stop_signals = _signals_raise()
        try:
            for name, want in manifest["databases"].items():
                replaced.append(name)  # before its first change: its schemas are dropped first
                restore_db(srcs[name], work / "db" / f"{name}.dump", env)
                wf_restored = wf_restored or name == "trialbox_wf"
                for t in _sched.BULK_REFDATA:
                    f = work / "db" / f"{name}.site.{t}.copy"
                    if f.is_file() and want.get("refdata_schema") and f.stat().st_size:
                        _copy_in(srcs[name], f"{want['refdata_schema']}.{t}", f)
            for name, want in manifest["databases"].items():  # rows checked before any directory is touched
                scheme = want.get("row_hash", "md5")
                skip = [*want.get("excluded_tables", []), *want.get("excluded_data_schemas", [])]
                got = row_counts(srcs[name], skip, scheme)
                diff = sorted(k for k in set(got) | set(want["rows"]) if got.get(k) != want["rows"].get(k))
                if want.get("refdata_schema"):
                    site = site_row_counts(srcs[name], want["refdata_schema"], scheme)
                    wsite = want.get("site_rows", {})
                    empty = [0, _sched.EMPTY_HASH[scheme]]
                    diff += sorted(f"site:{k}" for k in set(site) | set(wsite)
                                   if site.get(k, empty) != wsite.get(k, empty))  # fmt: skip
                if diff:
                    msg = f"restored {name} differs from the backup in {len(diff)} tables: {diff[:5]}"
                    if want.get("rows_from") == "snapshot":
                        raise BackupError(msg)
                    warnings.append(msg + " (this backup counted its rows on a running box: check those tables)")
                checked[name] = sum(r[0] for r in got.values())
            if "trialbox_wf" in manifest["databases"]:  # T-728 (D-493, F-11): after the rows were checked
                # NEW-B-3 (D-522, review H1, M1): held from here on, before anything else can stop the restore
                # or a folder is set aside (the flag is a row of the restored database, so it is written after
                # the rows were compared with the backup's). Taken off at the end only when the restore is
                # complete and nothing was carried
                hold = hold_screening(env, hold_dir, hold_reason)
                try:
                    jobs_failed = fail_running_jobs(srcs["trialbox_wf"], when, manifest["created_at"])
                except Exception as e:  # the queue could not be changed: the restore says so and stops
                    raise BackupError(
                        f"the jobs that were running at the backup could not be failed ({type(e).__name__}); do not "
                        "start the services: they would run those jobs again"
                    ) from e
                try:  # review M1: after the rows were checked against the manifest, like the jobs
                    keep()
                except Exception as e:
                    raise BackupError(
                        f"the opt-outs recorded after the backup could not be put back ({type(e).__name__}); do "
                        "not start the services: those patients would be listed again"
                    ) from e
                # D-573: the stores go back to their services' roles. After the running jobs were failed and the
                # opt-outs kept (both are rows, written as trialbox): a failure here leaves neither undone. Not
                # set: said in the result and by the command, see roles_ok
                roles = reapply_service_roles(env)
            lake: dict[str, Any] = {"snapshots": 0, "problems": [], "unsigned": 0, "checked": False}
            if (work / "dirs" / "lake").is_dir():  # D-455 (H1): the lake's own check, before any folder moves
                lake = {**lake_check(work / "dirs" / "lake"), "checked": True}
                if lake["problems"]:  # the databases go back with the rest (H-100, F2)
                    raise BackupError(f"the restored lake fails its own check: {lake['problems'][:3]}")
            asides: dict[str, Path] = {}
            placed: dict[str, tuple[Path, tuple[int, int, int] | None]] = {}
            for dname in manifest["dirs"]:
                if dname == HOST and HOST not in targets:
                    continue
                dest = targets[dname]
                top = (dest.stat().st_uid, dest.stat().st_gid, dest.stat().st_mode) if dest.is_dir() else None
                existed = dest.is_dir()
                if dest.exists() and any(dest.iterdir()):
                    aside, n = dest.with_name(f"{dest.name}.pre-restore-{stamp}"), 1
                    while aside.exists():  # a second restore within the same second: never over the first one's data
                        aside, n = dest.with_name(f"{dest.name}.pre-restore-{stamp}-{n}"), n + 1
                    moved.append((dest, aside, existed, top))  # H-100 (F2): what a failure puts back
                    dest.rename(aside)
                    asides[dname] = aside
                else:
                    moved.append((dest, None, existed, top))
                dest.mkdir(parents=True, exist_ok=True)
                src = work / "dirs" / dname
                if src.exists():
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                _give_back_owners(dest, dname, manifest.get("_owners") or {}, top, asides.get(dname))
                placed[dname] = (dest, top)
            since, since_from = snapshot_time(manifest)
            audit_dir = targets.get("audit") or (Path(env["TB_AUDIT_DIR"]) if env.get("TB_AUDIT_DIR") else None)
            reapply = events_to_reapply(audit_dir, since)  # D-455 (M3): read from the restored chain, before our events
            if "audit" in asides:
                # review M2 (a gap of T-691): the chain the box wrote after the backup's copy of it is in the folder set
                # aside, not in the restored one. Its events are listed too (an erasure, a break-glass, a signature)
                seen = {(e["ts"], e["event"]) for e in reapply}
                for ev in events_to_reapply(asides["audit"], since):
                    if (ev["ts"], ev["event"]) not in seen:
                        reapply.append({**ev, "where": f"{asides['audit'].name}/{ev['where']}"})
                reapply.sort(key=lambda r: str(r["ts"]))
            if lost["state"] == "counted" and kept_done and not lost["not_kept"]:
                # the register's own events were compared row by row and every opt-out put back: nothing to re-apply
                # for them (a lift a person typed is counted apart, ``lifts_reverted``)
                reapply = [r for r in reapply if r["event"] not in KEPT_BY_RESTORE]
            if reapply:
                _audit(targets, env, "backup.restore_reapply", sha, {
                    **base, "since": since.isoformat(timespec="milliseconds"), "since_from": since_from,
                    "count": len(reapply), "events": reapply[:200]})  # fmt: skip
            packs = manifest.get("refdata_packs", [])
            twf = manifest["databases"].get("trialbox_wf", {})
            if twf.get("refdata_schema") and packs:
                refdata = reload_refdata(srcs["trialbox_wf"], packs, refdata_dir)
            host = (
                ("restored to " + str(targets[HOST]))
                if HOST in targets and HOST in manifest["dirs"]
                else (
                    "in the backup; not restored (--dir host=<folder> writes it)"
                    if HOST in manifest["dirs"]
                    else "none"
                )
            )
            # D-573 (lane D): a restore whose service roles were not put back is not complete either (the hold stays)
            complete = not reapply and optouts_ok(lost) and roles_ok(roles, env)
            # NEW-B-3 (D-522; D-455's open item): a restore that is not complete leaves the box's list jobs held until
            # a person releases the hold. The restore takes its own hold off only when it is complete and nothing was
            # carried (a hold that stood before, an earlier restore's set-aside chain)
            if hold == "held" and complete and not carried:
                hold = release_own_hold(
                    env,
                    audit_dir,
                    f"the restore of the backup of {manifest['created_at']} is complete: nothing to re-apply",
                )
            audited = _audit(targets, env, "backup.restored", sha, {
                **base, "rows": checked, "dirs": sorted(manifest["dirs"]), "refdata_missing": refdata["missing"],
                "warnings": len(warnings), "optouts_after_backup": lost, "jobs_failed": len(jobs_failed),
                "hold": hold, "to_reapply": len(reapply), "service_roles": roles["state"]})  # fmt: skip
            for dname, (dest, top) in placed.items():  # D-724: the restore's own audit events were written as root
                _give_back_owners(dest, dname, manifest.get("_owners") or {}, top, asides.get(dname))
        except BaseException as e:
            stop_signals()  # the raising handlers off first: none is put back when the put-back ends
            with _signals_ignored():  # review R1: no second signal stops the put-back
                err = _undo_restore(e, srcs, replaced, pre, moved, env, targets, sha, base, copy, hold, hold_dir,
                                    hold_reason, wf_restored, keep, keep_to, stamp)  # fmt: skip
            raise err from e
        finally:
            stop_signals()
    return {"ok": not refdata["missing"], "site": manifest["site"], "created_at": manifest["created_at"],
            "layout": manifest.get("layout", 1), "rows": checked, "dirs": sorted(manifest["dirs"]),
            "refdata": refdata, "warnings": warnings, "kept_copy": str(copy) if copy else None, "copy": copy_note,
            "host": host, "lake_check": lake,
            "to_reapply": reapply, "reapply_since": since.isoformat(timespec="milliseconds"),
            "optouts_after_backup": lost, "jobs_failed": jobs_failed, "service_roles": roles,
            "complete": complete, "hold": hold, "audit": audited}  # fmt: skip


_safe = _sched.safe
