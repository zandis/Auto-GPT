"""``trialbox backup`` / ``trialbox restore`` (TB-PLAN-04 step 2, D-126): the whole box in one encrypted file.

    trialbox backup-keygen --private /media/usb/trialbox-backup.key --public deploy/secrets/backup.pub
    trialbox backup  --to /mnt/nas/trialbox --to /media/usb/trialbox [--keep 14]
    trialbox backup-verify <file> --key /media/usb/trialbox-backup.key
    trialbox restore <file> --key /media/usb/trialbox-backup.key --yes

What is in a backup (``*.tbbak``): a ``pg_dump`` (custom format) of ``trialbox_wf`` (``TB_DB_URL``) and, when
``TB_HAPI_DB_URL`` is set, of ``hapi``; every directory of the layout (lake, objects, audit, rulesets, orchestrator
files, secrets); a manifest with the sha256 of every member and the row count of every table.

**Encryption to the hospital's key.** The box holds only the public key (X25519). Each backup takes a fresh key pair,
derives an AES-256-GCM key with HKDF-SHA256 from the shared secret, and encrypts the tar stream in 1 MiB chunks. The
header is authenticated with every chunk, and the last chunk is marked, so truncation, reordering and edits are all
refused. Only the private key, kept by hospital IT in a sealed envelope (D-126), opens a backup. The box cannot read
its own backups, and Aimedics never holds the key.

**Targets.** Each ``--to`` is a directory: a mounted hospital NAS share, a USB disk, a second disk, or an off-site
mount. The same file is written to each (write to ``.part``, fsync, rename), and the newest ``--keep`` are kept.

**Restore** checks every hash before touching anything, moves each directory aside (``<dir>.pre-restore-<time>``)
before writing it, and restores the databases with ``pg_restore --clean --if-exists``.

The database tools are ``pg_dump`` / ``pg_restore`` on the path, or the command in ``TB_PG_DUMP_CMD`` /
``TB_PG_RESTORE_CMD`` (on a box: ``docker compose --project-directory deploy exec -T db pg_dump``).
"""

from __future__ import annotations

import base64
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

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"TBBAK1\n"
CHUNK = 1 << 20
SUFFIX = ".tbbak"
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
}


class BackupError(RuntimeError):
    pass


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

    def __init__(self, out: IO[bytes], recipient: X25519PublicKey, meta: Mapping[str, Any]) -> None:
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


def read_header(f: IO[bytes]) -> tuple[dict[str, Any], bytes]:
    if f.read(len(MAGIC)) != MAGIC:
        raise BackupError("not a TrialBox backup (bad magic)")
    (n,) = struct.unpack(">I", f.read(4))
    if n > 1 << 20:
        raise BackupError("header too large")
    raw = f.read(n)
    return json.loads(raw), raw


def decrypt_stream(f: IO[bytes], key: X25519PrivateKey) -> Iterator[bytes]:
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


def db_sources(env: Mapping[str, str]) -> list[DbSource]:
    from tb_common.db import split_url

    out = []
    if env.get("TB_DB_URL"):
        dsn, prefix = split_url(env["TB_DB_URL"])
        out.append(DbSource("trialbox_wf", dsn, (f"{prefix}*",) if prefix else ()))
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
    args, extra = _libpq(src.dsn)
    cmd = [*_cmd(env, "TB_PG_DUMP_CMD", "pg_dump"), "--format=custom", "--no-owner", "--no-privileges", *args]
    for s in src.schemas:
        cmd += ["--schema", s]
    with out.open("wb") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, env={**os.environ, **extra}, check=False)
    if r.returncode != 0:
        raise BackupError(f"pg_dump of {src.name} failed: {r.stderr.decode(errors='replace').strip()[-400:]}")


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


def row_counts(src: DbSource) -> dict[str, int]:
    """``schema.table -> rows`` for every table of the source (the manifest's database check)."""
    import psycopg

    likes = [p.replace("*", "%") for p in src.schemas] or ["%"]
    out: dict[str, int] = {}
    with psycopg.connect(src.dsn, autocommit=True) as con:
        rows = con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE' "
            "AND table_schema NOT IN ('pg_catalog', 'information_schema') AND table_schema LIKE ANY(%s) "
            "ORDER BY 1, 2",
            (likes,),
        ).fetchall()
        for schema, table in rows:
            n = con.execute(f'SELECT count(*) FROM "{schema}"."{table}"').fetchone()
            out[f"{schema}.{table}"] = int(n[0]) if n else 0
    return out


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


def tree_hashes(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): _sha_file(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.is_symlink() and "pre-restore-" not in str(p)
    }


# ------------------------------------------------------------------------------------------------ backup
def backup(
    targets: Sequence[Path],
    public_key: Path,
    env: Mapping[str, str] | None = None,
    dirs: Mapping[str, Path] | None = None,
    keep: int = 14,
    site: str = "",
    now: datetime | None = None,
) -> list[Path]:
    """Write one encrypted backup to every target directory; return the files written."""
    env = dict(os.environ if env is None else env)
    if not targets:
        raise BackupError("no --to target")
    dirs = dict(dirs if dirs is not None else layout(env))
    when = now or datetime.now(UTC)
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    site = site or env.get("TB_SITE_ID") or socket.gethostname()
    name = f"trialbox-{_safe(site)}-{stamp}{SUFFIX}"
    recipient = load_public(public_key)
    srcs = db_sources(env)
    manifest: dict[str, Any] = {"created_at": when.isoformat(timespec="seconds"), "site": site, "databases": {},
                                "dirs": {}, "files": {}}  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="tb-backup-") as tmp:
        work = Path(tmp)
        for src in srcs:
            dump(src, work / f"{src.name}.dump", env)
            manifest["databases"][src.name] = {"schemas": list(src.schemas), "rows": row_counts(src)}
        first = Path(targets[0])
        first.mkdir(parents=True, exist_ok=True)
        part = first / (name + ".part")
        with part.open("wb") as raw:
            enc = _Encryptor(raw, recipient, {"site": site, "created_at": manifest["created_at"]})
            with tarfile.open(fileobj=enc, mode="w|gz") as tar:
                for src in srcs:
                    f = work / f"{src.name}.dump"
                    manifest["files"][f"db/{src.name}.dump"] = _sha_file(f)
                    tar.add(f, arcname=f"db/{src.name}.dump")
                for dname, root in sorted(dirs.items()):
                    hashes_ = tree_hashes(root)
                    manifest["dirs"][dname] = {"path": str(root), "files": len(hashes_)}
                    for rel, sha in hashes_.items():
                        manifest["files"][f"dirs/{dname}/{rel}"] = sha
                        tar.add(root / rel, arcname=f"dirs/{dname}/{rel}", recursive=False)
                data = json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False).encode()
                info = tarfile.TarInfo("manifest.json")
                info.size = len(data)
                info.mtime = int(when.timestamp())
                tar.addfile(info, io.BytesIO(data))
            enc.finish()
            raw.flush()
            os.fsync(raw.fileno())
        final = first / name
        part.rename(final)
        written = [final]
        for t in targets[1:]:
            t = Path(t)
            t.mkdir(parents=True, exist_ok=True)
            tpart = t / (name + ".part")
            shutil.copyfile(final, tpart)
            with tpart.open("rb") as fh:
                os.fsync(fh.fileno())
            if _sha_file(tpart) != _sha_file(final):
                raise BackupError(f"copy to {t} does not match")
            tpart.rename(t / name)
            written.append(t / name)
    for t in targets:
        prune(Path(t), keep)
    return written


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s)[:40] or "box"


def prune(target: Path, keep: int) -> list[Path]:
    """Keep the newest ``keep`` backups in a target; remove older ones and stale ``.part`` files."""
    files = sorted(target.glob(f"trialbox-*{SUFFIX}"), key=lambda p: p.name.rsplit("-", 1)[-1])
    gone = files[:-keep] if keep > 0 else []
    gone += list(target.glob(f"trialbox-*{SUFFIX}.part"))
    for p in gone:
        p.unlink(missing_ok=True)
    return gone


# ------------------------------------------------------------------------------------------------ verify / restore
def unpack(file: Path, key: Path, into: Path) -> dict[str, Any]:
    """Decrypt and extract ``file`` into ``into``; check every hash against the manifest; return the manifest."""
    sk = load_private(key)
    with file.open("rb") as fh:
        reader = io.BufferedReader(_ChunkReader(decrypt_stream(fh, sk)), buffer_size=CHUNK)
        with tarfile.open(fileobj=reader, mode="r|gz") as tar:
            tar.extractall(into, filter="data")
    manifest: dict[str, Any] = json.loads((into / "manifest.json").read_text(encoding="utf-8"))
    bad = [rel for rel, sha in manifest["files"].items() if not (into / rel).is_file() or _sha_file(into / rel) != sha]
    extra = {str(p.relative_to(into)) for p in into.rglob("*") if p.is_file() and p.name != "manifest.json"} - set(
        manifest["files"]
    )
    if bad or extra:
        raise BackupError(f"backup content does not match its manifest: {len(bad)} changed, {len(extra)} unlisted")
    return manifest


def verify(file: Path, key: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="tb-verify-") as tmp:
        m = unpack(file, key, Path(tmp))
    return {"ok": True, "site": m["site"], "created_at": m["created_at"], "files": len(m["files"]),
            "databases": {k: sum(v["rows"].values()) for k, v in m["databases"].items()}}  # fmt: skip


def restore(
    file: Path,
    key: Path,
    env: Mapping[str, str] | None = None,
    dirs: Mapping[str, Path] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Restore the databases and directories of ``file``; return what was restored, with row counts checked."""
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
            got = row_counts(srcs[name])
            if _strip_prefix(got) != _strip_prefix(want["rows"]):
                raise BackupError(f"restored {name} row counts differ from the backup's manifest")
            checked[name] = sum(got.values())
    return {"ok": True, "site": manifest["site"], "created_at": manifest["created_at"], "rows": checked,
            "dirs": sorted(manifest["dirs"])}  # fmt: skip


def _strip_prefix(rows: Mapping[str, int]) -> dict[str, int]:
    return dict(rows)
