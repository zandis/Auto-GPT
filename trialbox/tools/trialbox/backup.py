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
LAKE_SKIP_TOP = ("tmp",)  # DuckDB spill (lake.store temp_dir default)
# D-455 (H1): the lake's served files; listed and read under the lake's own lock (lake.store.lake_lock, D-462), so a
# rebuild's swap never falls between the listing and the reads, and checked against their sidecars after the read
LAKE_LOCKED = ("db", "parquet")
LAKE_LOCK = ".rebuild.lock"


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


def _libpq(dsn: str) -> tuple[list[str], dict[str, str]]:
    """pg_dump/pg_restore take the database as ``--dbname``; a ``host=`` socket in the query is passed through."""
    return ["--dbname", dsn], {}


def dump(src: DbSource, out: Path, env: Mapping[str, str]) -> None:
    """A full dump of ``src`` to ``out`` (the update path's rollback point; a backup uses :func:`take_snapshot`)."""
    pre = env.get("TB_PG_DUMP_DIR")
    if pre:  # D-138: dumps taken by the db container on a quiet box (tools/trialbox/update.py ComposeBox)
        f = Path(pre) / f"{src.name}.dump"
        if not f.is_file():
            raise BackupError(f"no {f} (TB_PG_DUMP_DIR)")
        shutil.copyfile(f, out)
        return
    args, extra = _libpq(src.dsn)
    cmd = [*_cmd(env, "TB_PG_DUMP_CMD", "pg_dump"), "--format=custom", "--no-owner", "--no-privileges", *args]
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
        pg_dump = " ".join(shlex.quote(a) for a in _cmd(env, "TB_PG_DUMP_CMD", "pg_dump"))
        script.write_text(_sched.snapshot_script(str(work), src.name, pg_dump, f'--dbname "{src.dsn}"', src.schemas,
                                                 src.refdata), encoding="utf-8")  # fmt: skip
        psql = [*_cmd(env, "TB_PSQL_CMD", "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1", "--dbname", src.dsn]
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


def restore_db(src: DbSource, dump_file: Path, env: Mapping[str, str]) -> None:
    args, extra = _libpq(src.dsn)
    cmd = [*_cmd(env, "TB_PG_RESTORE_CMD", "pg_restore"), "--clean", "--if-exists", "--no-owner",
           "--no-privileges", "--single-transaction", "--exit-on-error", *args]  # fmt: skip
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


def reload_refdata(src: DbSource, packs: Sequence[Mapping[str, str]], folder: Path | None) -> dict[str, list[str]]:
    """Load again each vendor pack ``packs`` names, from the pack files in ``folder`` (``deploy/refdata/loaded``);
    the hospital's own packs (``origin: site``) came back with the dump. Returns what was loaded and what is missing."""
    want = {p["pack_id"] for p in packs if p.get("origin") != "site"}
    done: list[str] = []
    if want and folder is not None and folder.is_dir():
        from tb_common.refdata import RefStore, opened
        from tb_common.refdata import verify as verify_pack

        with RefStore(_url_for(src)) as st:
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
        if why:
            left[why] = left.get(why, 0) + 1
        else:
            keep.append(rel)
    return keep, left


READ_TRIES = 3


def _append_only(arcname: str) -> bool:
    """The audit chain's day files (``audit/<day>.jsonl``): only ever appended to, one whole line per write
    (``tb_common.audit``); a repair that cuts one back is the one exception, and is seen as a file that shrank."""
    return arcname.startswith("dirs/audit/") and arcname.endswith(".jsonl")


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


def _add(tar: tarfile.TarFile, path: Path, arcname: str) -> tuple[str, int]:
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
    backup (``events_to_reapply``)."""
    grows = _append_only(arcname)
    for _ in range(READ_TRIES):
        with path.open("rb") as fh:
            before = os.fstat(fh.fileno())
            info = tar.gettarinfo(arcname=arcname, fileobj=fh)
            if grows:  # never a line that is being written
                info.size = _line_end(fh, before.st_size)
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


def _add_lake(tar: tarfile.TarFile, root: Path, manifest: dict[str, Any]) -> tuple[int, dict[str, int]]:
    """The lake (D-455, H1). Its served files (``db/``, ``parquet/``) are listed and read under the lake's lock, so a
    rebuild's swap waits for them: never half the old snapshot and half the new. A listing that is not one state
    is listed again, up to ``READ_TRIES``; after the read every file taken with its sidecar must hash to it and the
    files must still be the ones listed, or the backup fails (nothing vanished, nothing new). The rest of the lake
    (NDJSON, the vector store, the site inputs) is read after, without the lock. Returns the files taken and the
    count left out per reason."""
    left: dict[str, int] = {}
    n = 0
    for attempt in range(1, READ_TRIES + 1):
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
                n += 1
            bad = [r for r, want in sides.items() if manifest["files"].get(f"dirs/lake/{r}") != want]
            again = [r for r in select_files("lake", root)[0] if Path(r).parts[0] in LAKE_LOCKED]
            if bad or again != locked:
                raise BackupError(f"the lake changed while it was read: {len(bad)} file(s) differ from their sidecar "
                                  f"{bad[:3]}, listing {'changed' if again != locked else 'unchanged'}; run the "
                                  "backup again")  # fmt: skip
            break
    for rel in [r for r in rels if Path(r).parts[0] not in LAKE_LOCKED]:
        arc = f"dirs/lake/{rel}"
        try:
            manifest["files"][arc], manifest["sizes"][arc] = _add(tar, root / rel, arc)
        except FileNotFoundError:  # removed since the listing (a retention prune): not in the backup
            left["removed while the backup ran"] = left.get("removed while the backup ran", 0) + 1
            continue
        n += 1
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
    manifest: dict[str, Any] = {"layout": LAYOUT, "hashing": "stream", "created_at": when.isoformat(timespec="seconds"),
                                "site": site, "compression": f"{compression}-{ZSTD_LEVEL}" if compression == "zstd"
                                else compression, "databases": {}, "dirs": {}, "files": {}, "sizes": {},
                                "excluded": {}, "refdata_packs": []}  # fmt: skip
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
        with part.open("wb") as raw:
            hw = _HashWriter(raw)
            enc = _Encryptor(hw, recipient, meta)
            with _tar_writer(enc, compression) as tar:
                for src in srcs:
                    arc = f"db/{src.name}.dump"
                    manifest["files"][arc], manifest["sizes"][arc] = _add(tar, work / f"{src.name}.dump", arc)
                    if snaps[src.name]["refdata_schema"]:
                        for t, f in sorted(snaps[src.name]["site_files"].items()):
                            arc = f"db/{src.name}.site.{t}.copy"
                            manifest["files"][arc], manifest["sizes"][arc] = _add(tar, f, arc)
                for dname, root in sorted(dirs.items()):
                    if dname == "lake":
                        n, left = _add_lake(tar, root, manifest)
                        manifest["dirs"][dname] = {"path": str(root), "files": n}
                        if left:
                            manifest["excluded"][dname] = left
                        continue
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
        if _sha_file(final) != sha:  # read back from the first target too, as from every other one
            raise BackupError(f"{final} does not read back as written")
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
        prune(Path(t), keep, prefix)
    return written


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


def _audit(dirs: Mapping[str, Path], env: Mapping[str, str], event: str, sha: str, detail: dict[str, Any]) -> str:
    """Append ``event`` to the box's audit log (the ``audit`` directory, else ``TB_AUDIT_DIR``); returns where, or
    why not."""
    where = dirs.get("audit") or (Path(env["TB_AUDIT_DIR"]) if env.get("TB_AUDIT_DIR") else None)
    if where is None:
        return "not written: no audit directory in the layout (or TB_AUDIT_DIR)"
    from tb_common.audit import AuditLog

    log = AuditLog(Path(where), tz=env["TB_TZ"]) if env.get("TB_TZ") else AuditLog(Path(where))
    log.append(event, actor=env.get("TB_RESTORE_ACTOR") or "trialbox restore", input_sha=sha, detail=detail)
    return str(where)


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
    refdata: dict[str, list[str]] = {"reloaded": [], "missing": []}
    with tempfile.TemporaryDirectory(prefix="tb-restore-") as tmp:
        work = Path(tmp)
        manifest = unpack(file, key, work)
        sha = manifest["_sha256"]
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

        wf_restored = False
        roles: dict[str, str] = {"state": "not_restored"}  # D-573: no trial database in this backup, nothing to move
        jobs_failed: list[dict[str, str]] = []
        checked = {}
        try:
            for name, want in manifest["databases"].items():
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
        except BackupError as e:
            if wf_restored:  # the live register is gone: a second run could not read them any more (review H2)
                with contextlib.suppress(Exception):
                    keep()
            with contextlib.suppress(Exception):
                _audit(targets, env, "backup.restore_failed", sha, {**base, "error": str(e)[-300:]})
            back = f"; the box before it is kept in {copy}: trialbox restore {copy} puts it back" if copy else ""
            said = ""
            if lost.get("events"):
                said = (f"; {lost['events']} opt-out event(s) were recorded on this box after the backup's snapshot"
                        + (f", {lost['kept']} opt-out(s) of them were put back" if kept_done else ""))  # fmt: skip
            raise BackupError(f"{e}{said}{back}") from e
        lake: dict[str, Any] = {"snapshots": 0, "problems": [], "unsigned": 0, "checked": False}
        if (work / "dirs" / "lake").is_dir():  # D-455 (H1): the lake's own check, before any folder moves
            lake = {**lake_check(work / "dirs" / "lake"), "checked": True}
            if lake["problems"]:
                msg = f"the restored lake fails its own check: {lake['problems'][:3]}; no folder was replaced"
                with contextlib.suppress(Exception):
                    _audit(targets, env, "backup.restore_failed", sha, {**base, "error": msg[-300:]})
                back = f"; the box before it is kept in {copy}: trialbox restore {copy} puts it back" if copy else ""
                raise BackupError(f"{msg} (the databases are restored already){back}")
        asides: dict[str, Path] = {}
        for dname in manifest["dirs"]:
            if dname == HOST and HOST not in targets:
                continue
            dest = targets[dname]
            if dest.exists() and any(dest.iterdir()):
                aside, n = dest.with_name(f"{dest.name}.pre-restore-{stamp}"), 1
                while aside.exists():  # a second restore within the same second: never over the first one's data
                    aside, n = dest.with_name(f"{dest.name}.pre-restore-{stamp}-{n}"), n + 1
                dest.rename(aside)
                asides[dname] = aside
            dest.mkdir(parents=True, exist_ok=True)
            src = work / "dirs" / dname
            if src.exists():
                shutil.copytree(src, dest, dirs_exist_ok=True)
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
            else ("in the backup; not restored (--dir host=<folder> writes it)" if HOST in manifest["dirs"] else "none")
        )
        audited = _audit(targets, env, "backup.restored", sha, {
            **base, "rows": checked, "dirs": sorted(manifest["dirs"]), "refdata_missing": refdata["missing"],
            "warnings": len(warnings), "optouts_after_backup": lost, "jobs_failed": len(jobs_failed),
            "service_roles": roles["state"]})  # fmt: skip
    return {"ok": not refdata["missing"], "site": manifest["site"], "created_at": manifest["created_at"],
            "layout": manifest.get("layout", 1), "rows": checked, "dirs": sorted(manifest["dirs"]),
            "refdata": refdata, "warnings": warnings, "kept_copy": str(copy) if copy else None, "copy": copy_note,
            "host": host, "lake_check": lake,
            "to_reapply": reapply, "reapply_since": since.isoformat(timespec="milliseconds"),
            "optouts_after_backup": lost, "jobs_failed": jobs_failed, "service_roles": roles,
            "complete": not reapply and optouts_ok(lost) and roles_ok(roles, env), "audit": audited}  # fmt: skip


_safe = _sched.safe
