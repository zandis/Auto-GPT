"""A throwaway local PostgreSQL for the test suite, ``e2e_simple``, ``public_e2e`` and the demo (D-126).

    python -m tools.pglocal start <dir>     # prints a TB_DB_URL; idempotent (reuses a running cluster)
    python -m tools.pglocal stop <dir>      # idempotent
    python -m tools.pglocal --gc            # stop and remove the clusters whose owner process is dead (D-201)
    python -m tools.pglocal clean-tmp       # `make clean-tmp`: earlier runs' leftovers in /tmp and .cache (D-201)

In code: ``url = ensure(Path(...))``. The cluster listens on a Unix socket in its own directory only (no TCP port),
trusts the local user, and runs with ``fsync=off``: it is for tests and demos, never for a box, where the compose
``db`` service is the database. The PostgreSQL server binaries are found through ``TB_PG_BIN``, ``pg_config
--bindir`` or ``/usr/lib/postgresql/<n>/bin``.

Parallel work on one machine (D-201, RUNBOOK §13): every temporary root of a test run derives from ``TB_TEST_ROOT``
(``make`` sets it per branch, default ``$TB_SCRATCH/tb-tests-<branch>``); a cluster made for one process carries an
``.owner`` file (pid and start time) so that ``--gc`` can reap it after a ``kill -9``. A socket path too long for a
Unix socket is moved to a short private directory that ``<root>/run`` links to.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

DB = "trialbox_wf"
SOCK_MAX = 100  # sun_path holds 108 bytes on Linux and 104 on macOS
# D-572: the one limit for a branch's slug in a test root (tests/unit/test_test_isolation.py reads it). A worker's
# socket is <scratch>/tb-tests-<slug>/pg-gw<n>/run/.s.PGSQL.5432. With the default scratch folder and a five-digit
# uid (/var/tmp/trialbox-65534, 23 bytes), "/tb-tests-" (10), a two-digit worker's "/pg-gw99/run" (12) and the
# socket's name (14) that is 59 bytes beside the slug: 40 keeps the path inside SOCK_MAX, so the cluster's socket
# stays in the branch's own root; a longer slug sends it to the short-socket fallback.
SLUG_MAX = 40
SLUG_HASH = 8  # hex characters of the whole name's sha256 that a cut slug ends with


#: H-139: the db image's pinned extensions (deploy/images.lock): the test server's vector may not be older
IMAGES_LOCK = Path(__file__).resolve().parents[1] / "deploy" / "images.lock"


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text.split("-", maxsplit=1)[0])[:3])


def vector_behind_pin(offered: str | None, pinned: str) -> str:
    """Why a test server's vector extension cannot stand in for the db image's: older than ``pinned``. Empty when
    the server offers none (the tests that need it say so themselves) or one at least as new."""
    if not offered or _version(offered) >= _version(pinned):
        return ""
    return (
        f"the test PostgreSQL offers the vector extension {offered}, older than the db image's {pinned} "
        f"(deploy/images.lock): its types (halfvec among them) are missing, so the tests would fail for the host, "
        f"not for the code. Install pgvector {pinned} or newer for this server, or give one in TB_TEST_DB_URL"
    )


def vector_check(url: str, lock: Path = IMAGES_LOCK) -> str:
    """:func:`vector_behind_pin` for the server at ``url`` (its ``vector`` default version) and the image's pin."""
    import json

    import psycopg

    pinned = str(json.loads(lock.read_text(encoding="utf-8"))["images"]["db"]["extensions"]["vector"])
    with psycopg.connect(url, autocommit=True, connect_timeout=10) as con:
        row = con.execute("SELECT default_version FROM pg_available_extensions WHERE name = 'vector'").fetchone()
    return vector_behind_pin(str(row[0]) if row and row[0] else None, pinned)


def bindir() -> Path:
    env = os.environ.get("TB_PG_BIN")
    if env:
        return Path(env)
    if shutil.which("pg_config"):
        out = subprocess.run(["pg_config", "--bindir"], capture_output=True, text=True, check=False).stdout.strip()
        if out and (Path(out) / "initdb").exists():
            return Path(out)
    found = sorted(Path("/usr/lib/postgresql").glob("*/bin/initdb"), key=lambda p: int(p.parent.parent.name))
    if found:
        return found[-1].parent
    if shutil.which("initdb"):
        return Path(str(shutil.which("initdb"))).parent
    raise RuntimeError("no PostgreSQL server binaries (initdb): install postgresql or set TB_PG_BIN")


def url_for(root: Path) -> str:
    return f"postgresql://{_user()}@/{DB}?host={(root / 'run').resolve()}"


def _user() -> str:
    return "trialbox"


def _run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)  # type: ignore[call-overload,no-any-return]


def _as_postgres_user() -> list[str]:
    """initdb and the server refuse to run as root: run them as an unprivileged owner of the directory."""
    if os.geteuid() != 0:
        return []
    for who in ("postgres", "nobody"):
        if _run(["id", who]).returncode == 0:
            return ["runuser", "-u", who, "--"]
    raise RuntimeError("running as root and no 'postgres' user to own the throwaway cluster")


def running(root: Path) -> bool:
    return (root / "data" / "postmaster.pid").exists() and _run(
        [str(bindir() / "pg_isready"), "-h", str((root / "run").resolve()), "-q"]
    ).returncode == 0


ENSURE_LOCK = ".ensure.lock"  # beside data/: held across ensure's check-and-start (H-72)


@contextlib.contextmanager
def _ensure_lock(root: Path) -> Iterator[None]:
    """One ``ensure`` at a time for this cluster, across processes: an exclusive ``flock`` on ``<root>/.ensure.lock``.
    Two processes that both found no server would otherwise both initdb (one removing the other's half-made data/)
    and both start one. The kernel lets the lock go when its holder dies, so a ``kill -9`` leaves nothing held."""
    import fcntl

    with (root / ENSURE_LOCK).open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def ensure(root: Path) -> str:
    """Start (or reuse) the cluster under ``root`` and return its ``TB_DB_URL``. Safe to call from several processes
    at once: the check and the start are done under one cross-process lock, so one of them starts the server and the
    others reuse it."""
    root = root.resolve()
    if running(root):
        return url_for(root)
    root.mkdir(parents=True, exist_ok=True)
    with _ensure_lock(root):
        return _ensure_locked(root)


def _ensure_locked(root: Path) -> str:
    data = root / "data"
    pre = _as_postgres_user()
    if running(root):  # another process started it while this one waited for the lock
        return url_for(root)
    sock = _socket_dir(root)
    if pre:
        owner = pre[2]
        _grant_traverse(root, owner)
        shutil.chown(root, owner)
        shutil.chown(sock, owner)
    b = bindir()
    if not (data / "PG_VERSION").exists():
        if data.exists():
            shutil.rmtree(data)
        r = _run([*pre, str(b / "initdb"), "-D", str(data), "-U", "postgres", "-A", "trust", "-E", "UTF8",
                  "--locale=C.UTF-8", "--no-instructions"])  # fmt: skip
        if r.returncode != 0:
            r = _run([*pre, str(b / "initdb"), "-D", str(data), "-U", "postgres", "-A", "trust", "-E", "UTF8",
                      "--locale=C"])  # fmt: skip
        if r.returncode != 0:
            raise RuntimeError(f"initdb failed: {r.stderr.strip()[-400:]}")
    opts = f"-c listen_addresses='' -c unix_socket_directories='{sock}' -c fsync=off -c synchronous_commit=off " \
           "-c full_page_writes=off -c max_connections=300"  # fmt: skip
    r = _run([*pre, str(b / "pg_ctl"), "-D", str(data), "-l", str(root / "server.log"), "-o", opts, "-w", "start"])
    if r.returncode != 0 and not running(root):
        log = (root / "server.log").read_text(errors="replace")[-600:] if (root / "server.log").exists() else ""
        raise RuntimeError(f"pg_ctl start failed: {r.stderr.strip()[-300:]} {log}")
    for _ in range(50):
        if running(root):
            break
        time.sleep(0.1)
    psql = [*pre, str(b / "psql"), "-h", str(sock), "-U", "postgres", "-d", "postgres", "-tAqc"]
    if _run([*psql, f"SELECT 1 FROM pg_roles WHERE rolname='{_user()}'"]).stdout.strip() != "1":
        _run([*psql, f"CREATE ROLE {_user()} LOGIN CREATEDB"])
    if _run([*psql, f"SELECT 1 FROM pg_database WHERE datname='{DB}'"]).stdout.strip() != "1":
        r = _run([*psql, f"CREATE DATABASE {DB} OWNER {_user()}"])
        if r.returncode != 0:
            raise RuntimeError(f"create database failed: {r.stderr.strip()}")
    # pgvector, where this server's PostgreSQL has it installed, is created as the image's db-init creates it (D-204,
    # D-439): by the superuser, in schema public, never by a store; a server without it is left as it is
    on_db = [*psql[:-3], "-d", DB, "-tAqc"]
    if _run([*on_db, "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"]).stdout.strip() == "1":
        _run([*on_db, "CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"])
    return url_for(root)


def _short_socket_parent() -> Path:
    """Where a short socket directory goes: under the scratch root when that is short enough, else ``/tmp``."""
    base = scratch_root()
    return base if len(str(base)) + len("/tbpg-xxxxxxxx/.s.PGSQL.5432") <= SOCK_MAX else Path("/tmp")


def _ours_short(target: Path) -> bool:
    """A short socket directory this module made: ``tbpg-*`` directly under its parent, owned by this user (or, as
    root, by the cluster's ``postgres`` user), holding nothing but socket files."""
    try:
        st = target.lstat()
        names = [p.name for p in target.iterdir()]
    except OSError:
        return False
    owners = {os.geteuid(), *_postgres_uids()}
    return (
        target.name.startswith("tbpg-")
        # resolved on both sides: a TB_SCRATCH spelled with ".." (CI) must still match the directory made under it
        and target.parent.resolve() in {_short_socket_parent().resolve(), Path("/tmp").resolve()}
        and not target.is_symlink()
        and st.st_uid in owners
        and all(n.startswith(".s.PGSQL.") for n in names)
    )


def _postgres_uids() -> set[int]:
    if os.geteuid() != 0:
        return set()
    import pwd

    out = set()
    for who in ("postgres", "nobody"):
        with contextlib.suppress(KeyError):
            out.add(pwd.getpwnam(who).pw_uid)
    return out


def _socket_dir(root: Path) -> Path:
    """``root/run``; when that path is too long for a Unix socket, a short private directory ``root/run`` links to
    (removed with the cluster by :func:`remove`). A ``run`` link to anything else is replaced, never followed."""
    run = root / "run"
    if run.is_symlink():
        target = Path(os.path.realpath(run))
        if _ours_short(target):
            return target
        run.unlink()
    if run.is_dir():
        return run
    if len(str(run)) + len("/.s.PGSQL.5432") <= SOCK_MAX:
        run.mkdir()
        return run
    parent = _short_socket_parent()
    parent.mkdir(parents=True, exist_ok=True)
    short = Path(tempfile.mkdtemp(prefix="tbpg-", dir=parent))
    short.chmod(0o755)
    run.symlink_to(short, target_is_directory=True)
    return short


def _grant_traverse(root: Path, owner: str) -> None:
    """As root the server runs as ``owner``, which must reach ``root``: add the search bit (o+x, never o+r) to each
    parent that lacks it, and say so. A private scratchpad (mode 0700) is the usual case."""
    if _run(["runuser", "-u", owner, "--", "test", "-x", str(root.parent)]).returncode == 0:
        return
    for parent in reversed(root.parents):
        mode = parent.stat().st_mode
        if not mode & 0o001:
            parent.chmod(mode | 0o001)
            print(f"pglocal: added o+x (search only) to {parent} so that '{owner}' reaches {root}", file=sys.stderr)


def _our_postmaster(pid: int, data: Path) -> bool:
    """``pid`` is the postmaster of ``data``: alive, and its working directory is that data directory (a postmaster
    runs in its data directory). A stale ``postmaster.pid`` naming a reused pid fails this."""
    if not pid or not _alive(pid):
        return False
    try:
        return Path(os.readlink(f"/proc/{pid}/cwd")) == data.resolve()
    except OSError:
        return False


def stop(root: Path) -> None:
    """Stop the cluster under ``root``. Idempotent: a missing directory, no cluster or a stopped one is a no-op. Only
    a postmaster that runs in this data directory is signalled; a stale pid file is left alone."""
    data = root.resolve() / "data"
    pidfile = data / "postmaster.pid"
    if not pidfile.exists():
        return
    pid = _postmaster_pid(pidfile)
    if not _our_postmaster(pid, data):
        return
    _run([*_as_postgres_user(), str(bindir() / "pg_ctl"), "-D", str(data), "-m", "immediate", "-w", "stop"])
    if _our_postmaster(pid, data):  # pg_ctl could not (a foreign version): the same signal pg_ctl sends, harder
        with contextlib.suppress(OSError):
            os.kill(pid, 9)


def remove(root: Path) -> None:
    """Stop the cluster under ``root`` and delete the directory, and its short socket directory when it is one this
    module made. Links are never followed."""
    if root.is_symlink() or not root.exists():
        return
    stop(root)
    run = root / "run"
    if run.is_symlink():
        target = Path(os.path.realpath(run))
        run.unlink()
        if _ours_short(target):
            shutil.rmtree(target, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)


def stop_idle(root: Path) -> bool:
    """Stop the cluster under ``root`` when no client is connected; True when it is (now) stopped."""
    if not running(root):
        return True
    if _clients(root) != 0:
        return False
    stop(root)
    return not running(root)


# ------------------------------------------------------------------ temp roots and owners (D-201)
def scratch_root() -> Path:
    """Where per-branch temp roots live: ``TB_SCRATCH`` (an agent's scratchpad), else ``/var/tmp/trialbox-<uid>``;
    never a fixed name directly under ``/tmp``, which every agent on the machine shares."""
    env = os.environ.get("TB_SCRATCH")
    return Path(os.path.abspath(env)) if env else Path(f"/var/tmp/trialbox-{os.getuid()}")  # no ".." left in it


def slug_of(name: str) -> str:
    """A branch name as one path segment of at most :data:`SLUG_MAX` characters (``agent/T-003-x`` ->
    ``agent-T-003-x``). A longer name keeps its start and ends with a short hash of the whole name, so two branches
    that share their first characters do not share a test root."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "detached"
    if len(slug) <= SLUG_MAX:
        return slug
    digest = hashlib.sha256(name.encode()).hexdigest()[:SLUG_HASH]
    return f"{slug[: SLUG_MAX - SLUG_HASH - 1].rstrip('-.')}-{digest}"


def branch_slug(repo: Path | None = None) -> str:
    """The checkout's branch as one short path segment (``agent/T-003-x`` -> ``agent-T-003-x``); a detached HEAD
    (CI, a review worktree) is ``detached-<short sha>``, so two detached checkouts do not share a root."""
    where = repo or Path(__file__).resolve().parents[1]
    r = _run(["git", "-C", str(where), "rev-parse", "--abbrev-ref", "HEAD"])
    name = r.stdout.strip() if r.returncode == 0 else ""
    if name in ("", "HEAD"):
        sha = _run(["git", "-C", str(where), "rev-parse", "--short=10", "HEAD"]).stdout.strip()
        name = f"detached-{sha}" if sha else "detached"
    return slug_of(name)


SYSTEM_DIRS = ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/opt", "/proc", "/root", "/run", "/sbin", "/srv",
               "/sys", "/usr", "/var/lib", "/var/log", "/var/cache", "/var/spool", "/home")  # fmt: skip
MARKER = ".tb-test-root"


def check_test_root(path: Path) -> Path:
    """``TB_TEST_ROOT`` is an absolute directory of the branch's own (the suite deletes what it made under it):
    never ``/``, a top-level directory, ``/tmp``, ``/var/tmp``, the home directory, a system directory itself or a
    directory directly in one, and links are resolved first. An existing, non-empty directory must carry the
    ``.tb-test-root`` marker that :func:`mark_test_root` writes, so an existing folder of other files is refused."""
    p = Path(os.path.realpath(os.path.normpath(path))) if Path(path).is_absolute() else Path(".")
    bad = {Path("/tmp"), Path("/var/tmp"), Path.home(), *(Path(d) for d in SYSTEM_DIRS)}
    if not p.is_absolute() or len(p.parts) < 3 or p in bad or p.parent in bad - {Path("/tmp"), Path("/var/tmp")}:
        raise ValueError(f"TB_TEST_ROOT={path} is refused: give a directory of this branch's own, such as "
                         f"{scratch_root()}/tb-tests-<branch>")  # fmt: skip
    if p.is_dir() and any(p.iterdir()) and not (p / MARKER).exists():
        raise ValueError(f"TB_TEST_ROOT={path} is refused: it holds files and no {MARKER} marker (not a test root)")
    return p


def _close_to_others(folder: Path) -> None:
    """Take group and others' write from ``folder`` if this user owns it (the search bit stays). A shared folder (a
    sticky one such as /tmp, a group's setgid folder, the home folder, / or a system folder) is never changed. The
    folder is opened once without following a link, and the folder looked at is the folder changed."""
    if folder in {Path("/"), Path.home(), *(Path(d) for d in SYSTEM_DIRS)}:
        return
    try:
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:  # a link, gone, or not a folder: left as it is
        return
    try:
        st = os.fstat(fd)
        shared = st.st_mode & (stat.S_ISVTX | stat.S_ISGID) or st.st_uid != os.geteuid()
        if not shared and st.st_mode & 0o022:
            os.fchmod(fd, stat.S_IMODE(st.st_mode) & ~0o022)
    finally:
        os.close(fd)


def mark_test_root(path: Path) -> Path:
    """Check ``path`` as a test root, create it and write its marker.

    H-115: the folders it creates are 0700 whatever the umask. The test root, and the folders from it up to the
    per-user scratch root when it lies under that root, lose group and others' write if this user owns them. A folder
    above the scratch root is never changed, nor any folder when the scratch root is ``/`` or a top-level folder. A
    folder in that chain that another account owns (not root), sticky or not, is refused: its owner could swap what
    this run makes. The marker is written through the root's own descriptor, opened without following a link.
    Under an ordinary user's umask 002 these folders were 0775, and the product's checks that walk the real folders
    from ``/`` rightly refused every tree a test built below them."""
    p = check_test_root(path)
    for folder in reversed([p, *p.parents]):
        if not folder.exists():
            with contextlib.suppress(FileExistsError):  # another run made it a moment ago: checked below
                folder.mkdir(mode=0o700)
                folder.chmod(0o700)
    scratch = Path(os.path.realpath(scratch_root()))  # p is a real path: compare like with like
    for folder in [p, *p.parents]:
        if folder != p and (len(scratch.parts) < 3 or not folder.is_relative_to(scratch)):
            break
        st = os.lstat(folder)
        if st.st_uid not in (0, os.geteuid()):  # a sticky bit does not hold off the folder's own owner
            raise ValueError(f"TB_TEST_ROOT={path} is refused: {folder} is uid {st.st_uid}'s, not this user's: "
                             "its owner could swap what the run makes; give a root of this user's own")  # fmt: skip
        _close_to_others(folder)
        if folder == scratch:
            break
    _write_marker(p)
    return p


def _write_marker(root: Path) -> None:
    """The marker, written in ``root`` itself: a root swapped for a link after the checks is refused (an OSError),
    never followed, and a marker that is a link is not followed either."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
        os.close(os.open(MARKER, flags, 0o600, dir_fd=fd))
    finally:
        os.close(fd)


def test_root() -> Path:
    """This run's temp root: ``TB_TEST_ROOT`` (checked), else ``<scratch root>/tb-tests-<branch>``."""
    env = os.environ.get("TB_TEST_ROOT")
    return check_test_root(Path(env)) if env else scratch_root() / f"tb-tests-{branch_slug()}"


def cluster_dir(worker: str | None = None) -> Path:
    """The test session's own cluster: ``<test root>/pg-<xdist worker>`` (``pg-main`` without xdist)."""
    return test_root() / f"pg-{worker or os.environ.get('PYTEST_XDIST_WORKER') or 'main'}"


def _start_time(pid: int) -> str:
    """The process's start time in clock ticks since boot (``/proc/<pid>/stat`` field 22), "" if it is gone."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return ""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _postmaster_pid(pidfile: Path) -> int:
    try:
        return int(pidfile.read_text().split("\n", 1)[0])
    except (OSError, ValueError):
        return 0


def claim(root: Path, pid: int | None = None) -> None:
    """Record ``pid`` (default: this process) as the owner of the cluster under ``root``."""
    pid = pid or os.getpid()
    root.mkdir(parents=True, exist_ok=True)
    (root / ".owner").write_text(f"{pid} {_start_time(pid)}\n", encoding="utf-8")


def _owner(root: Path) -> tuple[int, str] | None:
    """The ``.owner`` record, or None when it is missing or unreadable."""
    try:
        pid_s, _, started = (root / ".owner").read_text(encoding="utf-8").strip().partition(" ")
        return int(pid_s), started
    except (OSError, ValueError):
        return None


def owner_alive(root: Path) -> bool:
    """True while the ``.owner`` process runs: the same pid with the same start time (a reused pid counts as dead).
    An unreadable owner file counts as alive: what cannot be read is kept."""
    rec = _owner(root)
    if rec is None:
        return (root / ".owner").exists()
    pid, started = rec
    if not _alive(pid):
        return False
    now = _start_time(pid)
    return not started or not now or now == started


def _is_cluster_dir(root: Path) -> bool:
    """A folder this module made for a cluster: named ``pg-*``, ``tb-pgtest-*`` or ``pglocal``, and holding a data
    directory or nothing but its own files."""
    if root.is_symlink() or not root.is_dir():
        return False
    if not (root.name.startswith(("pg-", "tb-pgtest-", "tb-pglocal-")) or root.name == "pglocal"):
        return False
    known = {".owner", ENSURE_LOCK, "data", "run", "server.log"}
    return (root / "data" / "PG_VERSION").exists() or all(p.name in known for p in root.iterdir())


def _owned(bases: Iterable[Path]) -> list[Path]:
    """Cluster folders holding an ``.owner`` file, at depth 1 or 2 under each base (a test root, the scratch root)."""
    found: set[Path] = set()
    for base in bases:
        if base.is_dir() and not base.is_symlink():
            for pattern in ("*/.owner", "*/*/.owner"):
                found.update(p.parent for p in base.glob(pattern) if _is_cluster_dir(p.parent))
    return sorted(found)


def gc(bases: Iterable[Path] | None = None) -> list[Path]:
    """Stop and remove every owned cluster whose owner is gone; return what was removed. A cluster without an
    ``.owner`` file (an older checkout's) is never touched here; the shared one of :func:`for_work` directly in a
    given base or in this run's test root (``<root>/pglocal``) is stopped, not removed, when no client uses it (a
    killed ``make test`` leaves it running)."""
    if bases is None:
        bases = [scratch_root()]
        if os.environ.get("TB_TEST_ROOT"):
            bases.insert(0, test_root())
    bases = list(bases)
    removed = []
    for root in _owned(bases):
        if not owner_alive(root):
            remove(root)
            removed.append(root)
    for base in bases:
        shared = base / "pglocal"
        if _is_cluster_dir(shared) and _mine(shared) and running(shared):
            stop_idle(shared)
    return removed


def shared_dir() -> Path:
    """The cluster that :func:`for_work` shares between runs: ``TB_PG_DIR``, else ``<TB_TEST_ROOT>/pglocal`` when a
    test root is set (``make`` sets one), else ``/tmp/tb-pglocal-<uid>`` (a demo or a drill run by hand)."""
    if os.environ.get("TB_PG_DIR"):
        return Path(os.environ["TB_PG_DIR"])
    if os.environ.get("TB_TEST_ROOT"):
        return test_root() / "pglocal"
    return Path(f"/tmp/tb-pglocal-{os.getuid()}")


# ------------------------------------------------------------------ make clean-tmp (D-201, review §5.3)
def _size(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(dirpath, name)).st_blocks * 512
    return total


def _busy_paths() -> set[str]:
    """Every path a running process names: its working directory, open files, command line words, environment."""
    seen: set[str] = set()
    me = os.getpid()
    for proc in Path("/proc").glob("[0-9]*"):
        if int(proc.name) == me:
            continue
        try:
            seen.add(os.readlink(proc / "cwd"))
            seen.update((proc / "cmdline").read_bytes().decode(errors="replace").split("\0"))
            seen.update((proc / "environ").read_bytes().decode(errors="replace").split("\0"))  # TB_COMPLETE_DIR=...
            for fd in (proc / "fd").iterdir():
                seen.add(os.readlink(fd))
        except OSError:
            continue
    return seen


def _in_use(path: Path, busy: set[str]) -> bool:
    p = str(path)
    return any(s == p or s.startswith(p + "/") or s.startswith(p + "=") or ("=" + p) in s for s in busy if s)


def _clients(root: Path) -> int:
    """Client connections to the cluster under ``root`` (-1 when the server does not answer the question)."""
    q = "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()"
    r = _run([*_as_postgres_user(), str(bindir() / "psql"), "-h", str((root / "run").resolve()), "-U", "postgres",
              "-d", "postgres", "-tAqc", q])  # fmt: skip
    try:
        return int(r.stdout.strip()) if r.returncode == 0 else -1
    except ValueError:
        return -1


def _locked(root: Path) -> bool:
    """A ``make test`` holds this test root (``flock`` on ``<root>/.lock``): what is under it is in use."""
    lock = root / ".lock"
    if not lock.exists():
        return False
    import fcntl

    try:
        with lock.open("a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        return True
    return False


def _mine(path: Path) -> bool:
    """Made by this user (or, as root, by the throwaway clusters' ``postgres`` user): another user's files stay."""
    try:
        return path.lstat().st_uid in {os.geteuid(), *_postgres_uids()}
    except OSError:
        return False


def clean_tmp(
    repo: Path,
    tmp: Path = Path("/tmp"),
    dry_run: bool = False,
    rehearsal: Path | None = None,
    clusters: Iterable[Path] = (),
    gc_first: bool = True,
    rehearsing: bool | None = None,
) -> list[tuple[Path, int]]:
    """Remove what earlier runs left behind and nobody uses now; return ``(path, bytes)`` for each removal.

    The owned clusters of dead owners (:func:`gc`); in ``tmp``: ``pytest-of-*`` run directories, the ``tb-pgtest-*``
    and ``tb-pglocal-*`` clusters, ``tb-backup-drill*``, ``tb-drill``, ``tb-e2e-simple*`` and the rehearsal's ``runs``
    (``rehearsal``, default ``TB_REHEARSAL_DIR`` or ``tmp/tb-rehearsal``); the extra ``clusters`` (the branch's shared
    one); in ``repo/.cache/complete-run`` the ``src.tgz`` and ``results.tgz`` of every run but the two newest by
    time (their reports stay). Kept: anything another user made, a link, a path that a running process holds
    (working directory, open file, command line, environment), a pytest run directory whose ``.lock`` names a live
    process, a cluster that is running (with an owner or without one: a server is stopped only by its owner or by
    :func:`gc`), a folder that does not look like a cluster, and the rehearsal's ``runs`` while ``rehearse.sh``
    runs."""
    out: list[tuple[Path, int]] = []

    def drop(path: Path, cluster: bool = False) -> None:
        size = _size(path) if path.is_dir() else (path.lstat().st_size if path.exists() else 0)
        if not dry_run:
            if cluster:
                remove(path)
            elif path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        out.append((path, size))

    if gc_first and not dry_run:
        out.extend((p, 0) for p in gc())
    busy = _busy_paths()
    for root in [*sorted([*tmp.glob("tb-pgtest-*"), *tmp.glob("tb-pglocal-*")]), *clusters]:
        if (
            _is_cluster_dir(root)
            and _mine(root)
            and not owner_alive(root)
            and not running(root)
            and not _in_use(root, busy)
            and not _locked(root.parent)
        ):
            drop(root, cluster=True)
    for base in sorted(tmp.glob("pytest-of-*")):
        if base.is_symlink() or not _mine(base):
            continue
        for run in sorted([*base.glob("pytest-*"), *base.glob("garbage-*")]):
            if run.is_symlink() or not run.is_dir():
                continue
            lock = run / ".lock"
            holder = _postmaster_pid(lock) if lock.exists() else 0
            if (holder and _alive(holder)) or _in_use(run, busy):
                continue
            drop(run)
        if not dry_run and all(p.is_symlink() for p in base.iterdir()):
            shutil.rmtree(base, ignore_errors=True)
    rehearsal = rehearsal or Path(os.environ.get("TB_REHEARSAL_DIR") or tmp / "tb-rehearsal")
    work = [*tmp.glob("tb-backup-drill*"), tmp / "tb-drill", *tmp.glob("tb-e2e-simple*")]
    if rehearsing is None:  # between two cases no process names runs/ itself: a running rehearse.sh does
        rehearsing = any(s.endswith("rehearse.sh") for s in busy)
    if not rehearsing:
        work.append(rehearsal / "runs")
    for path in sorted(work):
        if path.exists() and not path.is_symlink() and _mine(path) and not _in_use(path, busy):
            drop(path)
    runs = sorted((p for p in (repo / ".cache" / "complete-run").glob("*") if p.is_dir() and not p.is_symlink()),
                  key=lambda p: p.stat().st_mtime)  # fmt: skip
    for run in runs[:-2]:
        for tgz in sorted([*run.glob("shard-*/results.tgz"), *run.glob("shard-*/src.tgz")]):
            if not tgz.is_symlink():
                drop(tgz)
    return out


def for_work(work: Path) -> str:
    """The ``TB_DB_URL`` for a run whose files live in ``work`` (e2e_simple, public_e2e, the demos, the in-process box).

    ``TB_DB_URL`` in the environment wins (a box, CI with its own server, a test's ``db_url`` fixture). Otherwise
    one shared throwaway cluster (:func:`shared_dir`) gives each work directory its own schemas (prefix from the
    directory's path). A new work directory (no ``.tb_db`` marker) starts from empty schemas, as it starts from empty
    files. The URL is also put in ``os.environ``.
    """
    if os.environ.get("TB_DB_URL"):
        return os.environ["TB_DB_URL"]
    import hashlib

    base = ensure(shared_dir())
    prefix = "w" + hashlib.sha1(str(work.resolve()).encode()).hexdigest()[:10] + "_"
    marker = work / ".tb_db"
    if not marker.exists():
        drop_prefix(base, prefix)
        work.mkdir(parents=True, exist_ok=True)
        marker.write_text(prefix + "\n", encoding="utf-8")
    url = f"{base}&tb_prefix={prefix}"
    os.environ["TB_DB_URL"] = url
    return url


def drop_prefix(url: str, prefix: str) -> None:
    """Drop every schema whose name starts with ``prefix`` (never all of them: an empty prefix is refused)."""
    if not prefix:
        raise ValueError("drop_prefix: an empty prefix would drop every schema in the database")
    import psycopg
    from tb_common.db import split_url

    dsn, _ = split_url(url)
    with psycopg.connect(dsn, autocommit=True) as con:
        names = [
            r[0] for r in con.execute("SELECT nspname FROM pg_namespace WHERE starts_with(nspname, %s)", (prefix,))
        ]
        for n in names:
            con.execute(f'DROP SCHEMA "{n}" CASCADE')


def _gib(n: int) -> str:
    return f"{n / 2**30:.2f} GiB"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", nargs="?", choices=["start", "stop", "stop-idle", "url", "gc", "clean-tmp", "mark"])
    ap.add_argument("root", nargs="?", type=Path)
    ap.add_argument("--gc", nargs="?", const="", metavar="DIR", help="the gc command (DIR: where to look)")
    ap.add_argument("--dry-run", action="store_true", help="clean-tmp: list, remove nothing")
    a = ap.parse_args(argv)
    cmd = "gc" if a.gc is not None else a.cmd
    if a.gc:
        a.root = Path(a.gc)
    if cmd in ("start", "stop", "stop-idle", "url", "mark") and a.root is None:
        ap.error(f"{cmd} needs a directory")
    if cmd == "start":
        print(ensure(a.root))
    elif cmd == "stop":
        stop(a.root)
    elif cmd == "stop-idle":
        if not stop_idle(a.root):
            print(f"pglocal: {a.root} has clients; left running", file=sys.stderr)
    elif cmd == "mark":
        try:
            print(mark_test_root(a.root))
        except ValueError as e:
            print(f"pglocal: {e}", file=sys.stderr)
            return 1
    elif cmd == "url":
        print(url_for(a.root))
    elif cmd == "gc":
        for p in gc([a.root] if a.root else None):
            print(f"pglocal gc: removed {p} (owner gone)")
    elif cmd == "clean-tmp":
        mine = [test_root() / "pglocal"] if os.environ.get("TB_TEST_ROOT") else []
        done = clean_tmp(Path(__file__).resolve().parents[1], dry_run=a.dry_run, clusters=mine)
        for p, n in done:
            print(f"{'would remove' if a.dry_run else 'removed'} {p} ({_gib(n)})")
        print(f"clean-tmp: {'would free' if a.dry_run else 'freed'} {_gib(sum(n for _, n in done))}")
    else:
        ap.error("give a command, or --gc")
    return 0


if __name__ == "__main__":
    sys.exit(main())
