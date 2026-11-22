"""``trialbox restore-drill`` (T-730d, D-892, H-84): the whole proof that a backup restores, typed by hospital IT on
the host with the private key in hand (D-126: the box cannot open its own backups).

    trialbox restore-drill <backup file> --key /media/usb/trialbox-backup.key

1. Free space and memory are checked first: the unpacked backup in the work folder and the throwaway server's data
   (``--db-dir``, default the work folder); short of either, nothing starts and the need is said in GB.
2. H-84: the drill restores into a **throwaway database server** of its own, never into the box's: a one-off
   container of the box's own database image (``POSTGRES_IMAGE``, else ``deploy/images.lock``; never pulled) with
   ``--network none``, no published port, none of the box's volumes or networks, its data in the drill's own folder,
   a random superuser password and memory and process limits. It is reached through a Unix socket folder of the
   drill's own (0700), so ``pg_restore`` (run inside the throwaway, ``docker exec``) and the row comparison (here,
   through libpq) are the very calls ``trialbox restore`` makes. No connection is opened to the live server: no role
   of the throwaway can reach it, and no role or grant of the box is changed. ``TB_DB_URL`` / ``TB_HAPI_DB_URL`` are
   read only for the database names and the ``tb_prefix``.
3. The backup is opened with the key and every file is checked against its signed manifest (``backup.unpack``).
4. Each database of the backup is restored into a scratch database of the throwaway (``tb_drill_<id>_<name>``) and
   its rows and content hashes are compared with the manifest, as ``trialbox restore`` does.
5. The throwaway, its data and the unpacked files are removed at the end, after a failure, Ctrl-C or SIGTERM too.
   What the drill makes is written down (``<state>/<id>.json``) before it is made; a drill that died (power, kill -9)
   is swept by the next one: only containers labelled ``tb.restore-drill`` and folders that carry the drill's mark.
6. The result (pass or fail, the backup's date and what was compared; never the key, its path or the password) is
   the box's key-check record (``deploy/site/backup-verified.json``, which the health check reads: red after
   ``TB_HEALTH_VERIFIED_DAYS``) and an audit event (``backup.restore_drill``). A failed drill is a backup problem in
   ``backup-status``, so it goes through the box's alert route (mail, or the health page, D-735).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

from tools.trialbox import backup_schedule as _sched
from tools.trialbox import launch as _launch

if TYPE_CHECKING:
    from tools.trialbox import backup as bk

# H-88: this module is imported by the host's python3 (standard library only): backup.py (zstandard, cryptography)
# and psycopg are imported where they are used, in this process when it has them, else in the drill's container
LIBS = ("psycopg", "zstandard", "cryptography")
RESTORE_FLAGS = ["--clean", "--if-exists", "--no-owner", "--no-privileges", "--single-transaction", "--exit-on-error"]

SCRATCH_PREFIX = "tb_drill_"
UNPACK_FACTOR = 4.0  # the unpacked backup: a compressed dump and the lake are about this many times the file
SCRATCH_FACTOR = 2.0  # the scratch databases: a restored dump with its indexes, about this many times the file
EVENT = "backup.restore_drill"
GB = 1024**3

LABEL = "tb.restore-drill"  # every container the drill starts carries it, with the drill's id as its value
CONTAINER_PREFIX = "tb-restore-drill-"
MARK = ".tb-restore-drill"  # a folder the drill made holds this file, with the drill's id: the sweep removes no other
PG_UID = 999  # the database image's postgres user (deploy/docker-compose.yml runs db as 999:999)
MEMORY = "1g"
MEMORY_BYTES = GB
PIDS = 256
SHM = "256m"
READY_SECONDS = 120.0
SOCK_MAX = 100  # sun_path holds 108 bytes on Linux; the socket is <sock>/.s.PGSQL.5432


class DrillError(RuntimeError):
    pass


class SigtermError(BaseException):
    """SIGTERM during a drill: raised like KeyboardInterrupt (SIGINT), so the clean-up runs and it propagates."""


def _dbname(dsn: str) -> str:
    from psycopg.conninfo import conninfo_to_dict

    return str(conninfo_to_dict(dsn).get("dbname") or "")


def scratch_source(src: bk.DbSource, admin_dsn: str, name: str) -> bk.DbSource:
    """The scratch twin of ``src``: the same schemas, in database ``name`` on the server of ``admin_dsn`` (the
    throwaway's). Refused unless the name is a drill's own and is neither the live database nor the admin's."""
    from psycopg.conninfo import make_conninfo

    live = {_dbname(src.dsn), _dbname(admin_dsn)}
    if not name.startswith(SCRATCH_PREFIX) or name in live:
        raise DrillError(f"refused: {name!r} is not a drill's scratch database (it would be a live one)")
    return replace(src, dsn=make_conninfo(admin_dsn, dbname=name))


def _create(admin_dsn: str, name: str) -> None:
    import psycopg
    from psycopg import sql

    with psycopg.connect(admin_dsn, autocommit=True) as con:
        con.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def _drop(admin_dsn: str, name: str) -> None:
    import psycopg
    from psycopg import sql

    if not name.startswith(SCRATCH_PREFIX):  # the last guard before a DROP DATABASE
        raise DrillError(f"refused to drop {name!r}: not a drill's scratch database")
    with psycopg.connect(admin_dsn, autocommit=True) as con:
        con.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def space_needed(file: Path) -> dict[str, int]:
    size = file.stat().st_size
    return {"unpack": int(size * UNPACK_FACTOR), "scratch": int(size * SCRATCH_FACTOR)}


def _device(p: Path) -> int | None:
    try:
        return os.stat(p).st_dev
    except OSError:
        return None


def check_space(file: Path, work: Path, db_dir: Path, free: Callable[[Path], int]) -> None:
    """Refuse before anything starts when the work folder or the throwaway server's folder is short; say how much.
    Both on one file system: the two needs are added."""
    need = space_needed(file)
    if work == db_dir or (_device(work) is not None and _device(work) == _device(db_dir)):
        wants = [("the unpacked backup and the throwaway server's data", work, need["unpack"] + need["scratch"])]
    else:
        wants = [("the unpacked backup", work, need["unpack"]), ("the throwaway server's data", db_dir,
                                                                  need["scratch"])]  # fmt: skip
    short = []
    for what, where, n in wants:
        have = free(where)
        if have < n:
            short.append(f"{what} needs {n / GB:.1f} GB free in {where}, {have / GB:.1f} GB is free")
    if short:
        raise DrillError("not enough free space, nothing was started: " + "; ".join(short))


def mem_available() -> int:
    """MemAvailable of /proc/meminfo, in bytes (0 when it cannot be read: the drill then refuses)."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def db_image(env: Mapping[str, str]) -> str:
    """The image the box's ``db`` service runs: ``POSTGRES_IMAGE`` as the compose file reads it, else the lock's."""
    if (env.get("POSTGRES_IMAGE") or "").strip():
        return env["POSTGRES_IMAGE"].strip()
    from tools import images_lock

    return str(images_lock.load()["images"]["db"]["image"])


def compare(src: bk.DbSource, want: Mapping[str, Any]) -> list[str]:
    """The tables whose rows or content hash differ from the manifest, as ``trialbox restore`` compares them."""
    from tools.trialbox import backup as bk

    scheme = want.get("row_hash", "md5")
    skip = [*want.get("excluded_tables", []), *want.get("excluded_data_schemas", [])]
    got = bk.row_counts(src, skip, scheme)
    diff = sorted(k for k in set(got) | set(want["rows"]) if got.get(k) != want["rows"].get(k))
    if want.get("refdata_schema"):
        site = bk.site_row_counts(src, want["refdata_schema"], scheme)
        wsite = want.get("site_rows", {})
        empty = [0, _sched.EMPTY_HASH[scheme]]
        diff += sorted(f"site:{k}" for k in set(site) | set(wsite) if site.get(k, empty) != wsite.get(k, empty))
    return diff


# ------------------------------------------------------------------------------------------ the throwaway server
def _password() -> str:
    return secrets.token_urlsafe(32)


def _short_parent(work: Path) -> Path:
    """Where the socket folder goes: under the work folder when the socket path stays short enough, else where the
    test cluster puts its short sockets (``tools.pglocal``: the scratch root, else the system's temp folder)."""
    if len(str(work.resolve())) + len("/tbd-xxxxxxxx/s/.s.PGSQL.5432") <= SOCK_MAX:
        return work
    from tools import pglocal

    parent = pglocal._short_socket_parent()
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return parent


def _chown(p: Path, uid: int, gid: int) -> None:
    os.chown(p, uid, gid)


def _mark(d: Path, drill_id: str) -> None:
    (d / MARK).write_text(drill_id, encoding="utf-8")


def _marked(d: Path, drill_id: str) -> bool:
    try:
        return d.is_dir() and not d.is_symlink() and (d / MARK).read_text(encoding="utf-8").strip() == drill_id
    except OSError:
        return False


@dataclass
class Throwaway:
    """One drill's database server: its container, its folders and the libpq DSN that reaches it (no password)."""

    drill_id: str
    image: str
    docker: list[str]
    root: Path  # <db_dir>/tb-drill-<id>-server (0700): data/, secret/
    sock_parent: Path  # <short>/tbd-<id> (0700, root's); sock/ in it is the database user's
    chown: Callable[[Path, int, int], None] = _chown
    made: list[str] = field(default_factory=list)  # containers started (names)
    ready_by_exec: bool = False  # H-88: this process has no psycopg: pg_isready in the throwaway says it answers

    @property
    def name(self) -> str:
        return f"{CONTAINER_PREFIX}{self.drill_id}"

    @property
    def init_name(self) -> str:
        return f"{CONTAINER_PREFIX}{self.drill_id}-init"

    @property
    def restore_name(self) -> str:
        """H-88: the container that unpacks, restores and compares when this process lacks the libraries."""
        return f"{CONTAINER_PREFIX}{self.drill_id}-restore"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def secret(self) -> Path:
        return self.root / "secret"

    @property
    def sock(self) -> Path:
        return self.sock_parent / "s"

    @property
    def admin_dsn(self) -> str:
        from psycopg.conninfo import make_conninfo

        return make_conninfo("", host=str(self.sock), port="5432", user="postgres", dbname="postgres")

    def restore_cmd(self) -> str:
        """pg_restore inside the throwaway: the image's own, of the backup's PostgreSQL major; the password goes by
        name (``-e PGPASSWORD``, taken from this process's environment), never on a command line."""
        return shlex.join([*self.docker, "exec", "-i", "-e", "PGPASSWORD", self.name, "pg_restore"])

    def record(self) -> dict[str, Any]:
        return {"drill": self.drill_id, "containers": [self.init_name, self.name, self.restore_name],
                "folders": [str(self.root),
                str(self.sock_parent)], "pid": os.getpid(), "image": self.image}  # fmt: skip

    def _common(self, name: str) -> list[str]:
        return ["--rm", "--name", name, "--label", f"{LABEL}={self.drill_id}", "--network", "none", "--pull", "never",
                "--user", f"{PG_UID}:{PG_UID}", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true", "--memory", MEMORY, "--memory-swap", MEMORY,
                "--pids-limit", str(PIDS), "--shm-size", SHM,
                "-v", f"{self.data}:/var/lib/postgresql/data"]  # fmt: skip

    def start(self, password: str) -> None:
        """Folders, then initdb in a one-off container (the password from a 0400 file, removed when it exits), then
        the server, listening on the socket folder only; returns when it answers."""
        for d in (self.root, self.sock_parent):
            d.mkdir(mode=0o700)
            os.chmod(d, 0o700)
            _mark(d, self.drill_id)
        for d in (self.data, self.secret, self.sock):
            d.mkdir(mode=0o700)
            self.chown(d, PG_UID, PG_UID)
        pw = self.secret / "pw"
        fd = os.open(pw, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(password + "\n")
        self.chown(pw, PG_UID, PG_UID)
        try:
            self.made.append(self.init_name)
            _run([*self.docker, "run", *self._common(self.init_name), "-v", f"{self.secret}:/run/tb-drill:ro",
                  "--entrypoint", "initdb", self.image, "-D", "/var/lib/postgresql/data", "-U", "postgres",
                  "--pwfile=/run/tb-drill/pw", "--auth-local=scram-sha-256", "--auth-host=reject",
                  "--data-checksums"], "the throwaway server's initdb")  # fmt: skip
        finally:
            with contextlib.suppress(OSError):
                pw.unlink()
            shutil.rmtree(self.secret, ignore_errors=True)
        self.made.append(self.name)
        _run([*self.docker, "run", "-d", *self._common(self.name), "-v", f"{self.sock}:/var/run/postgresql",
              "-v", f"{self.sock}:{self.sock}", self.image, "postgres", "-c", "listen_addresses="],
             "the throwaway server")  # fmt: skip
        self._wait()

    def _wait(self) -> None:
        if self.ready_by_exec:
            return self._wait_exec()
        import psycopg

        end = time.monotonic() + READY_SECONDS
        last = ""
        while time.monotonic() < end:
            try:
                with psycopg.connect(self.admin_dsn, connect_timeout=2, autocommit=True) as con:
                    con.execute("SELECT 1")
                return
            except psycopg.Error as e:
                last = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
                time.sleep(0.5)
        raise DrillError(f"the throwaway server did not answer in {READY_SECONDS:.0f} s: {last[-200:]}")

    def _wait_exec(self) -> None:
        end = time.monotonic() + READY_SECONDS
        last = ""
        while time.monotonic() < end:
            argv = [*self.docker, "exec", self.name, "pg_isready", "-q", "-h", str(self.sock), "-p", "5432", "-U",
                    "postgres"]  # fmt: skip
            try:
                r = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
                if r.returncode == 0:
                    return
                last = (r.stderr or r.stdout).strip()[-200:] or f"exit {r.returncode}"
            except (OSError, subprocess.TimeoutExpired) as e:
                last = str(e)[-200:]
            time.sleep(0.5)
        raise DrillError(f"the throwaway server did not answer in {READY_SECONDS:.0f} s: {last}")

    def remove(self) -> list[str]:
        """Remove the containers and folders this drill made; return what could not be removed."""
        left: list[str] = []
        for n in reversed(self.made):
            if not _rm_container(self.docker, n, self.drill_id):
                left.append(f"container {n}")
        for d in (self.root, self.sock_parent):
            if _marked(d, self.drill_id):
                shutil.rmtree(d, ignore_errors=True)
            if d.exists():
                left.append(f"folder {d}")
        return left


def _run(argv: Sequence[str], what: str, timeout: float = 600) -> str:
    try:
        r = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DrillError(f"{what} did not start: {e}") from e
    if r.returncode != 0:
        raise DrillError(f"{what} failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def _label_of(docker: Sequence[str], name: str) -> str | None:
    """The drill label's value on container ``name``; None when there is no such container or label."""
    try:
        out = _run([*docker, "inspect", "--format", f'{{{{index .Config.Labels "{LABEL}"}}}}', name], "inspect", 60)
    except DrillError:
        return None
    v = out.strip()
    return v if v and v != "<no value>" else None


def _rm_container(docker: Sequence[str], name: str, drill_id: str | None) -> bool:
    """Remove a drill's container: only when it carries the drill's label (with ``drill_id`` when given). True when
    it is gone (or never was)."""
    label = _label_of(docker, name)
    if label is None:
        return True  # not there (a --rm container that stopped), or not the drill's: left alone
    if drill_id is not None and label != drill_id:
        return True
    try:
        _run([*docker, "rm", "-f", "-v", name], "docker rm", 120)
    except DrillError:
        return _label_of(docker, name) is None
    return True


def sweep(docker: Sequence[str], state: Path) -> list[str]:
    """Remove what earlier drills left (a drill that died before its clean-up): by their records, then any container
    still labelled as a drill's. Only labelled containers and marked folders; returns what was removed."""
    swept: list[str] = []
    for rec_file in sorted(state.glob("*.json")):
        try:
            rec = json.loads(rec_file.read_text(encoding="utf-8"))
            drill_id = str(rec["drill"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        ok = True
        for n in rec.get("containers", []):
            if str(n).startswith(CONTAINER_PREFIX) and _label_of(docker, str(n)) == drill_id:
                if _rm_container(docker, str(n), drill_id):
                    swept.append(f"container {n}")
                else:
                    ok = False
        for f in rec.get("folders", []):
            d = Path(str(f))
            if _marked(d, drill_id):
                shutil.rmtree(d, ignore_errors=True)
                if d.exists():
                    ok = False
                else:
                    swept.append(f"folder {d}")
        if ok:
            rec_file.unlink(missing_ok=True)
    try:
        out = _run([*docker, "ps", "-a", "--filter", f"label={LABEL}", "--format", "{{.Names}}"], "docker ps", 60)
    except DrillError:
        out = ""
    for n in out.split():
        if n.startswith(CONTAINER_PREFIX) and _label_of(docker, n) is not None and _rm_container(docker, n, None):
            swept.append(f"container {n}")
    return swept


@contextlib.contextmanager
def _lock(state: Path) -> Iterator[IO[str]]:
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    fh = (state / "lock").open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise DrillError("a previous restore drill is still running on this box, nothing was started: let it "
                             "finish (or stop it), then run the drill again") from e  # fmt: skip
        yield fh
    finally:
        fh.close()


@contextlib.contextmanager
def _on_sigterm() -> Iterator[None]:
    """SIGTERM ends the drill as Ctrl-C does: through its clean-up (only in the main thread, where signals land)."""

    def _raise(_sig: int, _frame: Any) -> None:
        raise SigtermError("SIGTERM")

    try:
        old = signal.signal(signal.SIGTERM, _raise)
    except ValueError:  # not the main thread
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, old)


@contextlib.contextmanager
def _pgpassword(password: str) -> Iterator[None]:
    """libpq (here) and ``docker exec -e PGPASSWORD`` (pg_restore) read the password from this process's environment
    for the drill's length: never a command line, a file left behind, a log or the result."""
    old = os.environ.get("PGPASSWORD")
    os.environ["PGPASSWORD"] = password
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("PGPASSWORD", None)
        else:
            os.environ["PGPASSWORD"] = old


def preflight(docker: Sequence[str], image: str, mem_free: Callable[[], int]) -> None:
    """Refuse before anything is made: no Docker, the image not on this box (it is never pulled), too little memory."""
    try:
        _run([*docker, "version", "--format", "{{.Server.Version}}"], "docker", 60)
    except DrillError as e:
        raise DrillError(f"Docker is not available, nothing was started (the drill runs a throwaway database server "
                         f"in Docker): {e}") from e  # fmt: skip
    try:
        _run([*docker, "image", "inspect", "--format", "{{.Id}}", image], "docker image inspect", 60)
    except DrillError as e:
        raise DrillError(f"the database image {image} is not on this box, nothing was started (the drill never "
                         "pulls it: it is the image the box's db runs)") from e  # fmt: skip
    have = mem_free()
    if have < MEMORY_BYTES:
        raise DrillError(f"not enough free memory, nothing was started: the throwaway server needs "
                         f"{MEMORY_BYTES / GB:.1f} GB, {have / GB:.1f} GB is available")  # fmt: skip


def drill(
    file: Path,
    key: Path,
    env: Mapping[str, str],
    *,
    work: Path | None = None,
    db_dir: Path | None = None,
    free: Callable[[Path], int] | None = None,
    now: datetime | None = None,
    name: Callable[[str], str] | None = None,
    state: Path | None = None,
    mem_free: Callable[[], int] | None = None,
    chown: Callable[[Path, int, int], None] | None = None,
    image: str | None = None,
) -> dict[str, Any]:
    """Run the drill on ``file`` with ``key``; return the result (``ok`` true or false). Raises :class:`DrillError`
    only when nothing was started (space, memory, Docker, the image, a drill still running, settings); every later
    failure is a result with ``ok`` false. Ctrl-C and SIGTERM clean up and then propagate.

    H-88: ``image`` (default: the box's Python image when this process lacks psycopg, zstandard or cryptography, as
    the host's python3 does; None when it has them) runs the unpack, the restore and the comparison in a one-off
    container of that image that reaches the throwaway's socket folder and nothing else (:func:`restore_argv`);
    Docker, the throwaway and the records stay here."""
    now = now or datetime.now(UTC)
    work = work or Path(tempfile.gettempdir())
    db_dir = db_dir or work
    state = state or work / ".tb-restore-drill"
    if image is None and not _launch.has_libs(LIBS):
        image = env.get("TB_IMAGE") or _launch.DEFAULT_IMAGE
    check_space(file, work, db_dir, free or (lambda p: shutil.disk_usage(p).free))
    srcs: dict[str, Any] = {}
    if image is None:
        from tools.trialbox import backup as bk

        srcs = {s.name: s for s in bk.db_sources(env)}  # the names and tb_prefix only: never connected to
    elif not (env.get("TB_DB_URL") or env.get("TB_HAPI_DB_URL")):  # the same refusal, before anything starts
        raise DrillError("TB_DB_URL is not set: nothing to back up from the database (the box's deploy/.env)")
    docker = shlex.split(env.get("TB_DOCKER") or "docker")
    db_img = db_image(env)
    with _lock(state):
        preflight(docker, db_img, mem_free or mem_available)
        if image is not None:
            try:
                _run([*docker, "image", "inspect", "--format", "{{.Id}}", image], "docker image inspect", 60)
            except DrillError as e:
                raise DrillError(f"the box's Python image {image} is not on this box, nothing was started (the "
                                 "drill's restore runs in it; it is never pulled)") from e  # fmt: skip
        swept = sweep(docker, state)
        drill_id = secrets.token_hex(4)
        srv = Throwaway(drill_id, db_img, docker, db_dir / f"tb-drill-{drill_id}-server",
                        _short_parent(work) / f"tbd-{drill_id}", chown or _chown)  # fmt: skip
        if image is not None:
            srv.ready_by_exec = True
            return _drill_in_image(file, key, env, srv, state, work, now, swept, image)
        return _drill(file, key, env, srcs, srv, state, work, now, name, swept)


def _begin(srv: Throwaway, state: Path, work: Path, file: Path, now: datetime,
           swept: list[str]) -> tuple[dict[str, Any], Path, Path]:  # fmt: skip
    """The result, the drill's record (written before anything is made: a lost answer is swept) and the 0700 folder
    the backup is unpacked into (swept too after a crash)."""
    res: dict[str, Any] = {"ok": False, "at": now.isoformat(timespec="seconds"), "file": file.name,
                           "drill": srv.drill_id, "databases": {}}  # fmt: skip
    if swept:
        res["swept"] = swept
    rec_file = state / f"{srv.drill_id}.json"
    holder = work / f"tb-drill-{srv.drill_id}-unpacked"  # the decrypted backup: swept too after a crash
    rec = srv.record()
    rec["folders"].append(str(holder))
    rec_file.write_text(json.dumps(rec), encoding="utf-8")
    holder.mkdir(mode=0o700)
    _mark(holder, srv.drill_id)
    (holder / "u").mkdir(mode=0o700)
    return res, rec_file, holder


def _restore_all(manifest: Mapping[str, Any], srcs: Mapping[str, Any], admin_dsn: str,
                 scratch_name: Callable[[str], str], unpacked: Path, denv: Mapping[str, str],
                 res: dict[str, Any], made: list[str]) -> None:  # fmt: skip
    """Each database of the backup into a scratch database of the throwaway, then its rows and hashes compared with
    the manifest, as ``trialbox restore`` does (here, or in the drill's container)."""
    from tools.trialbox import backup as bk

    res.update(created_at=manifest["created_at"], site=manifest.get("site", ""),
               sha256=manifest["_sha256"], files=len(manifest["files"]))  # fmt: skip
    for db in manifest["databases"]:
        if db not in srcs:
            raise DrillError(f"the backup holds database {db} but its URL is not set on this box")
    for db, want in manifest["databases"].items():
        scratch = scratch_source(srcs[db], admin_dsn, scratch_name(db))
        _create(admin_dsn, _dbname(scratch.dsn))
        made.append(_dbname(scratch.dsn))
        bk.restore_db(scratch, unpacked / "db" / f"{db}.dump", denv)
        for t in _sched.BULK_REFDATA:  # the hospital's own reference rows, as the restore copies them in
            f = unpacked / "db" / f"{db}.site.{t}.copy"
            if f.is_file() and want.get("refdata_schema") and f.stat().st_size:
                bk._copy_in(scratch, f"{want['refdata_schema']}.{t}", f)
        diff = compare(scratch, want)
        res["databases"][db] = {"tables": len(want["rows"]),
                                "rows": sum(r[0] for r in want["rows"].values()),
                                "differ": diff[:10], "differ_count": len(diff)}  # fmt: skip
    bad = {db: r["differ_count"] for db, r in res["databases"].items() if r["differ_count"]}
    res["ok"] = not bad
    if bad:
        res["error"] = "restored rows differ from the backup's manifest: " + ", ".join(
            f"{db} in {n} table(s)" for db, n in sorted(bad.items())
        )


def _drill(
    file: Path,
    key: Path,
    env: Mapping[str, str],
    srcs: Mapping[str, Any],
    srv: Throwaway,
    state: Path,
    work: Path,
    now: datetime,
    name: Callable[[str], str] | None,
    swept: list[str],
) -> dict[str, Any]:
    from tools.trialbox import backup as bk

    scratch_name = name or (lambda db: f"{SCRATCH_PREFIX}{srv.drill_id}_{db}")
    made: list[str] = []
    res, rec_file, holder = _begin(srv, state, work, file, now, swept)
    unpacked = holder / "u"
    # the restore runs in the throwaway, whatever TB_PG_RESTORE_CMD says (on a box: an exec into the live db)
    denv = {**env, "TB_PG_RESTORE_CMD": srv.restore_cmd()}
    with _on_sigterm(), _pgpassword(_password()):
        try:
            manifest = bk.unpack(file, key, unpacked, lake_from_restic=False)  # D-968: the sealed part
            res.update(created_at=manifest["created_at"], site=manifest.get("site", ""),
                       sha256=manifest["_sha256"], files=len(manifest["files"]))  # fmt: skip
            for db in manifest["databases"]:
                if db not in srcs:
                    raise DrillError(f"the backup holds database {db} but its URL is not set on this box")
            srv.start(os.environ["PGPASSWORD"])
            res["server"] = {"container": srv.name, "image": srv.image}
            _restore_all(manifest, srcs, srv.admin_dsn, scratch_name, unpacked, denv, res, made)
        except (bk.BackupError, DrillError, OSError) as e:
            res["error"] = str(e)[-400:]
        except Exception as e:  # a database that refused (psycopg), a damaged dump: a failed drill, said
            res["error"] = f"{type(e).__name__}: {str(e)[-400:]}"
        finally:
            _clean(srv, made, unpacked, res, rec_file)
    return res


# ------------------------------------------------------------------- H-88: the restore in the box's Python image
#: what the drill's container is given of this process's environment, by name (the values never on a command line):
#: the throwaway's password, and the box's URLs for the database names and tb_prefix only (it has no network)
PASSED = ("PGPASSWORD", "TB_DB_URL", "TB_HAPI_DB_URL")


def restore_argv(srv: Throwaway, image: str, file: Path, key: Path, holder: Path) -> list[str]:
    """The drill's container: the box's Python image, never pulled; no network (it reaches the throwaway through the
    socket folder, mounted at its own path, and nothing else: no Docker socket, no volume or network of the box);
    the backup and the key read-only; the unpack folder; no capability but reading the database user's socket
    folder; this process's uid and gid (its files stay the invoking user's); the drill's label, so a sweep takes it."""
    f, k = file.resolve(), key.resolve()
    names = [x for n in PASSED for x in ("-e", n)]
    return [*srv.docker, "run", "--rm", "--name", srv.restore_name, "--label", f"{LABEL}={srv.drill_id}",
            "--network", "none", "--pull", "never", "--user", f"{os.getuid()}:{os.getgid()}", "--read-only",
            "--cap-drop", "ALL", "--cap-add", "DAC_READ_SEARCH", "--security-opt", "no-new-privileges:true",
            "--pids-limit", str(PIDS), *names, "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", f"TMPDIR={holder / 't'}",
            "-v", f"{f}:{f}:ro", "-v", f"{k}:{k}:ro", "-v", f"{holder}:{holder}",
            "-v", f"{srv.sock_parent}:{srv.sock_parent}", image, "python", "-m", "tools.trialbox.restore_drill",
            "--inner", str(holder / "spec.json")]  # fmt: skip


def _drill_in_image(file: Path, key: Path, env: Mapping[str, str], srv: Throwaway, state: Path, work: Path,
                    now: datetime, swept: list[str], image: str) -> dict[str, Any]:  # fmt: skip
    res, rec_file, holder = _begin(srv, state, work, file, now, swept)
    unpacked, queue = holder / "u", holder / "q"
    queue.mkdir(mode=0o700)
    spec = {"file": str(file.resolve()), "key": str(key.resolve()), "unpacked": str(unpacked), "queue": str(queue),
            "sock": str(srv.sock), "prefix": f"{SCRATCH_PREFIX}{srv.drill_id}_"}  # fmt: skip
    (holder / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (holder / "t").mkdir(mode=0o700)  # the container's temp folder: its root is read-only
    inner: dict[str, Any] = {}
    p: subprocess.Popen[str] | None = None
    with _on_sigterm(), _pgpassword(_password()):
        try:
            srv.start(os.environ["PGPASSWORD"])
            res["server"] = {"container": srv.name, "image": srv.image}
            penv = {**os.environ, **{n: env[n] for n in PASSED[1:] if env.get(n)}}
            srv.made.append(srv.restore_name)
            p = subprocess.Popen(restore_argv(srv, image, file, key, holder), env=penv, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # fmt: skip
            out, err = _serve(p, srv, queue, unpacked)
            try:
                inner = json.loads(out.strip().splitlines()[-1])
            except (ValueError, IndexError) as e:
                raise DrillError(f"the drill's restore container failed (exit {p.returncode}): "
                                 f"{(err or out).strip()[-300:]}") from e  # fmt: skip
            for k in ("created_at", "site", "sha256", "files", "databases", "ok", "error"):
                if k in inner:
                    res[k] = inner[k]
        except (DrillError, OSError) as e:
            res["error"] = str(e)[-400:]
        finally:
            if p is not None and p.poll() is None:
                p.kill()
                with contextlib.suppress(Exception):
                    p.communicate(timeout=30)
            _clean(srv, [], unpacked, res, rec_file, inner.get("scratch_dropped", []), inner.get("scratch_left", []))
    return res


def _serve(p: subprocess.Popen[str], srv: Throwaway, queue: Path, unpacked: Path) -> tuple[str, str]:
    """While the drill's container runs: each restore it asks for (:func:`relay`) is run here, ``pg_restore`` in the
    throwaway (``docker exec``, as :meth:`Throwaway.restore_cmd`), with the dump it names from the unpack folder as
    input. Returns the container's output."""
    import threading

    got: dict[str, str] = {}

    def read(name: str, stream: IO[str] | None) -> None:
        got[name] = stream.read() if stream is not None else ""

    readers = [threading.Thread(target=read, args=(n, s), daemon=True) for n, s in (("out", p.stdout),
                                                                                   ("err", p.stderr))]  # fmt: skip
    for t in readers:
        t.start()
    while True:
        running = p.poll() is None
        for req in sorted(queue.glob("*.req")):
            done = req.with_suffix(".done")
            if not done.exists():
                rc, why = _restore_here(req, srv, unpacked)
                tmp = req.with_suffix(".tmp")
                tmp.write_text(json.dumps({"rc": rc, "err": why}), encoding="utf-8")
                tmp.replace(done)
        if not running:
            break
        time.sleep(0.05)
    for t in readers:
        t.join(timeout=60)
    return got.get("out", ""), got.get("err", "")


def _restore_here(req: Path, srv: Throwaway, unpacked: Path) -> tuple[int, str]:
    """One restore the container asked for: only restore's own flags into a scratch database on the throwaway's
    socket, from a dump in the unpack folder; anything else is refused."""
    try:
        ask = json.loads(req.read_text(encoding="utf-8"))
        args, dump = [str(a) for a in ask["args"]], Path(os.path.realpath(str(ask["dump"])))
    except (OSError, ValueError, KeyError, TypeError) as e:
        return 2, f"refused: an unreadable restore request ({e})"
    conn = dict(x.split("=", 1) for x in (args[-1].split() if args else []) if "=" in x)
    ok = (len(args) == len(RESTORE_FLAGS) + 2 and args[: len(RESTORE_FLAGS)] == RESTORE_FLAGS
          and args[-2] == "--dbname" and conn.get("host") == str(srv.sock)
          and str(conn.get("dbname", "")).startswith(f"{SCRATCH_PREFIX}{srv.drill_id}_")
          and dump.is_relative_to(Path(os.path.realpath(unpacked))) and dump.is_file())  # fmt: skip
    if not ok:
        return 2, "refused: a restore that is not the drill's own (its flags, its scratch database, its dump)"
    with dump.open("rb") as fh:
        r = subprocess.run([*shlex.split(srv.restore_cmd()), *args], stdin=fh, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, check=False)  # fmt: skip
    return r.returncode, r.stderr.decode(errors="replace")[-2000:]


def relay(queue: Path, args: Sequence[str]) -> int:
    """``TB_PG_RESTORE_CMD`` in the drill's container (no Docker there): ask the host to run ``pg_restore`` in the
    throwaway with these flags and the dump this process reads (its stdin, a file of the unpack folder); wait for
    its answer; its exit code and errors are this command's."""
    dump = os.readlink("/proc/self/fd/0")
    n = secrets.token_hex(6)
    tmp, req, done = queue / f"{n}.tmp", queue / f"{n}.req", queue / f"{n}.done"
    tmp.write_text(json.dumps({"args": list(args), "dump": dump}), encoding="utf-8")
    tmp.replace(req)
    while not done.exists():
        time.sleep(0.05)
    ans = json.loads(done.read_text(encoding="utf-8"))
    sys.stderr.write(str(ans.get("err") or ""))
    return int(ans["rc"])


def inner(spec: Mapping[str, str], environ: Mapping[str, str]) -> dict[str, Any]:
    """The drill's container: unpack the backup, restore each database into a scratch database of the throwaway (the
    restore relayed to the host), compare, drop the scratch databases. Returns what the host's result takes."""
    from psycopg.conninfo import make_conninfo

    from tools.trialbox import backup as bk

    res: dict[str, Any] = {"ok": False, "databases": {}}
    made: list[str] = []
    admin = make_conninfo("", host=spec["sock"], port="5432", user="postgres", dbname="postgres")
    relay_cmd = shlex.join([sys.executable, "-m", "tools.trialbox.restore_drill", "--relay", spec["queue"]])
    denv = {**environ, "TB_PG_RESTORE_CMD": relay_cmd}
    try:
        srcs = {s.name: s for s in bk.db_sources(environ)}
        manifest = bk.unpack(Path(spec["file"]), Path(spec["key"]), Path(spec["unpacked"]), lake_from_restic=False)
        _restore_all(manifest, srcs, admin, lambda db: f"{spec['prefix']}{db}", Path(spec["unpacked"]), denv, res,
                     made)  # fmt: skip
    except (bk.BackupError, DrillError, OSError) as e:
        res["error"] = str(e)[-400:]
    except Exception as e:  # a database that refused (psycopg), a damaged dump: a failed drill, said
        res["error"] = f"{type(e).__name__}: {str(e)[-400:]}"
    finally:
        res["scratch_dropped"], res["scratch_left"] = [], []
        for n in made:
            try:
                _drop(admin, n)
                res["scratch_dropped"].append(n)
            except Exception:  # removed with the throwaway by the host
                res["scratch_left"].append(n)
    return res


def _clean(
    srv: Throwaway,
    made: list[str],
    unpacked: Path,
    res: dict[str, Any],
    rec_file: Path,
    dropped_inside: Sequence[str] = (),
    left_inside: Sequence[str] = (),
) -> None:
    """Drop the scratch databases, remove the throwaway and its folders and the unpacked files; the result names only
    what was made, and what could not be removed is said (and its record kept, for the next drill's sweep)."""
    blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})  # a SIGTERM now waits for the clean-up
    try:
        _clean_up(srv, made, unpacked, res, rec_file, dropped_inside, left_inside)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, blocked)


def _clean_up(
    srv: Throwaway,
    made: list[str],
    unpacked: Path,
    res: dict[str, Any],
    rec_file: Path,
    dropped_inside: Sequence[str] = (),
    left_inside: Sequence[str] = (),
) -> None:
    dropped: list[str] = list(dropped_inside)  # H-88: what the drill's container dropped itself, and could not
    gone_with_server: list[str] = list(left_inside)
    for n in made:
        try:
            _drop(srv.admin_dsn, n)
            dropped.append(n)
        except Exception:  # the server is removed next, with it: said as such, never as dropped
            gone_with_server.append(n)
    left = srv.remove()
    shutil.rmtree(unpacked.parent, ignore_errors=True)
    if unpacked.parent.exists():
        left.append(f"folder {unpacked.parent}")
    if gone_with_server:
        if any(x == f"folder {srv.root}" for x in left):
            res.setdefault("left_behind", []).extend(f"{n} (in {srv.root})" for n in gone_with_server)
        else:
            res["scratch_removed_with_server"] = gone_with_server
    if left:
        res.setdefault("left_behind", []).extend(left)
    res["scratch_dropped"] = dropped
    res["unpacked_removed"] = not unpacked.parent.exists()
    if "server" in res:
        res["server"]["removed"] = not any(x.startswith("container ") for x in left)
    if not left:
        rec_file.unlink(missing_ok=True)


def record(deploy: Path, res: Mapping[str, Any], env: Mapping[str, str], dirs: Mapping[str, Path]) -> str:
    """The drill's result as the box's key-check record and an audit event; never the key or its path."""
    from tb_common import metrics

    metrics.record_drill(deploy, res)
    detail = {k: res.get(k) for k in ("ok", "at", "file", "created_at", "files", "databases", "error", "drill")}
    actor = {**env, "TB_RESTORE_ACTOR": env.get("TB_RESTORE_ACTOR") or "trialbox restore-drill"}
    if _launch.has_libs(LIBS):
        from tools.trialbox import backup as bk

        return bk._audit(dirs, actor, EVENT, str(res.get("sha256") or ""), detail)
    return _audit_here(dirs, actor, str(res.get("sha256") or ""), detail)


#: H-88: ``backup.layout``'s audit folder and ``backup._audit``, for the host's python3 (backup.py imports zstandard
#: and cryptography); ``test_the_host_record_finds_the_audit_folder_as_backup_does`` holds them to backup.py's
AUDIT_VOLUME = "/var/lib/docker/volumes/trialbox_audit-data/_data"


def audit_layout(env: Mapping[str, str], given: Sequence[str] = ()) -> dict[str, Path]:
    pairs = list(given) or [p for p in (env.get("TB_BACKUP_DIRS") or "").split(",") if p.strip()]
    if pairs:
        out = {}
        for p in pairs:
            name, _, path = p.strip().partition("=")
            if not name or not path:
                raise DrillError(f"bad directory {p!r}: use name=path")
            out[name] = Path(path)
        return {k: v for k, v in out.items() if k == "audit"}
    return {"audit": Path(AUDIT_VOLUME)}


def _audit_here(dirs: Mapping[str, Path], env: Mapping[str, str], sha: str, detail: dict[str, Any]) -> str:
    where = dirs.get("audit") or (Path(env["TB_AUDIT_DIR"]) if env.get("TB_AUDIT_DIR") else None)
    if where is None:
        return "not written: no audit directory in the layout (or TB_AUDIT_DIR)"
    from tb_common.audit import AuditLog

    log = AuditLog(Path(where), tz=env["TB_TZ"]) if env.get("TB_TZ") else AuditLog(Path(where))
    log.append(EVENT, actor=env.get("TB_RESTORE_ACTOR") or "trialbox restore", input_sha=sha, detail=detail)
    folder = Path(where)
    if os.geteuid() == 0 and folder.is_dir():  # D-724: what root wrote there is given to the folder's owner
        st = folder.stat()
        if st.st_uid != 0:
            for p in folder.rglob("*"):
                if not p.is_symlink() and p.lstat().st_uid == 0:
                    os.chown(p, st.st_uid, st.st_gid, follow_symlinks=False)
    return str(where)


def main(argv: Sequence[str]) -> int:
    """``python -m tools.trialbox.restore_drill --inner SPEC`` (the drill's container) or ``--relay QUEUE ARGS``
    (its TB_PG_RESTORE_CMD)."""
    if argv[:1] == ["--relay"] and len(argv) >= 2:
        return relay(Path(argv[1]), argv[2:])
    if argv[:1] == ["--inner"] and len(argv) == 2:
        spec = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        print(json.dumps(inner(spec, os.environ)))
        return 0
    print("usage: python -m tools.trialbox.restore_drill --inner SPEC | --relay QUEUE ARGS", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
