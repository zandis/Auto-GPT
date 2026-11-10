"""A throwaway local PostgreSQL for the test suite, ``e2e_simple``, ``public_e2e`` and the demo (D-126).

    python -m tools.pglocal start <dir>     # prints a TB_DB_URL; idempotent (reuses a running cluster)
    python -m tools.pglocal stop <dir>      # idempotent
    python -m tools.pglocal --gc            # stop and remove the clusters whose owner process is dead (D-201)
    python -m tools.pglocal clean-tmp       # `make clean-tmp`: earlier runs' leftovers in /tmp and .cache (D-201)

In code: ``url = ensure(Path(...))``. The cluster listens on a Unix socket in its own directory only (no TCP port),
trusts the local user, and runs with ``fsync=off``: it is for tests and demos, never for a box, where the compose
``db`` service is the database. The PostgreSQL server binaries are found through ``TB_PG_BIN``, ``pg_config
--bindir`` or ``/usr/lib/postgresql/<n>/bin``.

Parallel work on one machine (D-201, RUNBOOK §12): every temporary root of a test run derives from ``TB_TEST_ROOT``
(``make`` sets it per branch, default ``$TB_SCRATCH/tb-tests-<branch>``); a cluster made for one process carries an
``.owner`` file (pid and start time) so that ``--gc`` can reap it after a ``kill -9``. A socket path too long for a
Unix socket is moved to a short private directory that ``<root>/run`` links to.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

DB = "trialbox_wf"
SOCK_MAX = 100  # sun_path holds 108 bytes on Linux and 104 on macOS


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


def ensure(root: Path) -> str:
    """Start (or reuse) the cluster under ``root`` and return its ``TB_DB_URL``."""
    root = root.resolve()
    data = root / "data"
    pre = _as_postgres_user()
    if running(root):
        return url_for(root)
    root.mkdir(parents=True, exist_ok=True)
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
    return url_for(root)


def _socket_dir(root: Path) -> Path:
    """``root/run``; when that path is too long for a Unix socket, a short private directory ``root/run`` links to
    (removed with the cluster by :func:`remove`)."""
    run = root / "run"
    if run.is_symlink() and not run.resolve().is_dir():
        run.unlink()
    if run.is_symlink() or run.is_dir():
        return run.resolve()
    if len(str(run)) + len("/.s.PGSQL.5432") <= SOCK_MAX:
        run.mkdir()
        return run
    short = Path(tempfile.mkdtemp(prefix="tbpg-", dir="/tmp"))
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


def stop(root: Path) -> None:
    """Stop the cluster under ``root``. Idempotent: a missing directory, no cluster or a stopped one is a no-op."""
    data = root.resolve() / "data"
    pidfile = data / "postmaster.pid"
    if not pidfile.exists():
        return
    pid = _postmaster_pid(pidfile)
    _run([*_as_postgres_user(), str(bindir() / "pg_ctl"), "-D", str(data), "-m", "immediate", "-w", "stop"])
    if pid and _alive(pid) and _comm(pid) in ("postgres", "postmaster"):  # pg_ctl could not (a foreign version)
        with contextlib.suppress(OSError):
            os.kill(pid, 9)


def _comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


def remove(root: Path) -> None:
    """Stop the cluster under ``root`` and delete the directory, with its short socket directory if it has one."""
    if not root.exists() and not root.is_symlink():
        return
    stop(root)
    run = root / "run"
    if run.is_symlink():
        shutil.rmtree(run.resolve(), ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------ temp roots and owners (D-201)
def scratch_root() -> Path:
    """Where per-branch temp roots live: ``TB_SCRATCH`` (an agent's scratchpad), else ``/var/tmp/trialbox-<uid>``;
    never a fixed name directly under ``/tmp``, which every agent on the machine shares."""
    env = os.environ.get("TB_SCRATCH")
    return Path(env) if env else Path(f"/var/tmp/trialbox-{os.getuid()}")


def branch_slug(repo: Path | None = None) -> str:
    """The checkout's branch as one short path segment (``agent/T-003-x`` -> ``agent-T-003-x``)."""
    where = repo or Path(__file__).resolve().parents[1]
    r = _run(["git", "-C", str(where), "rev-parse", "--abbrev-ref", "HEAD"])
    name = r.stdout.strip() if r.returncode == 0 else ""
    return (re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "detached")[:40]


def check_test_root(path: Path) -> Path:
    """``TB_TEST_ROOT`` is an absolute directory of the branch's own: never ``/``, a top-level directory, ``/tmp``,
    ``/var/tmp`` or the home directory (the suite deletes what it made under it)."""
    p = Path(os.path.normpath(path))
    if not p.is_absolute() or len(p.parts) < 3 or p in {Path("/tmp"), Path("/var/tmp"), Path.home()}:
        raise ValueError(f"TB_TEST_ROOT={path} is refused: give a directory of this branch's own, such as "
                         f"{scratch_root()}/tb-tests-<branch>")  # fmt: skip
    return p


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


def owner_alive(root: Path) -> bool:
    """True while the ``.owner`` process runs: the same pid with the same start time (a reused pid counts as dead)."""
    try:
        pid_s, _, started = (root / ".owner").read_text(encoding="utf-8").strip().partition(" ")
        pid = int(pid_s)
    except (OSError, ValueError):
        return False
    if not _alive(pid):
        return False
    now = _start_time(pid)
    return not started or not now or now == started


def _owned(bases: Iterable[Path]) -> list[Path]:
    """Directories holding an ``.owner`` file, at depth 0 to 2 under each base (a test root, the scratch root)."""
    found: set[Path] = set()
    for base in bases:
        if base.is_dir():
            for pattern in (".owner", "*/.owner", "*/*/.owner"):
                found.update(p.parent for p in base.glob(pattern))
    return sorted(found)


def gc(bases: Iterable[Path] | None = None) -> list[Path]:
    """Stop and remove every owned cluster whose owner is dead; return what was removed. A cluster without an
    ``.owner`` file (an older checkout's, or the shared one of :func:`for_work`) is never touched here."""
    if bases is None:
        bases = [scratch_root()]
        if os.environ.get("TB_TEST_ROOT"):
            bases.insert(0, test_root())
    removed = []
    for root in _owned(bases):
        if not owner_alive(root):
            remove(root)
            removed.append(root)
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


def _cluster_in_use(root: Path) -> bool:
    """An owner that lives, or a running server with a client connected (another agent's run)."""
    if owner_alive(root):
        return True
    if not running(root):
        return False
    q = "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()"
    r = _run([*_as_postgres_user(), str(bindir() / "psql"), "-h", str((root / "run").resolve()), "-U", "postgres",
              "-d", "postgres", "-tAqc", q])  # fmt: skip
    return r.returncode != 0 or r.stdout.strip() not in ("", "0")


def clean_tmp(
    repo: Path,
    tmp: Path = Path("/tmp"),
    dry_run: bool = False,
    rehearsal: Path | None = None,
    clusters: Iterable[Path] = (),
    gc_first: bool = True,
) -> list[tuple[Path, int]]:
    """Remove what earlier runs left behind and nobody uses now; return ``(path, bytes)`` for each removal.

    The owned clusters of dead owners (:func:`gc`); in ``tmp``: ``pytest-of-*`` run directories, the ``tb-pgtest-*``
    and ``tb-pglocal-*`` clusters, ``tb-backup-drill*``, ``tb-drill``, ``tb-e2e-simple*`` and the rehearsal's ``runs``
    (``rehearsal``, default ``TB_REHEARSAL_DIR`` or ``tmp/tb-rehearsal``); the extra ``clusters`` (the branch's shared
    one); in ``repo/.cache/complete-run`` the ``src.tgz`` and ``results.tgz`` of every run but the
    two newest (their reports stay). A path that a running process holds (working directory, open file, command
    line, environment), a pytest run directory whose ``.lock`` names a live process, a cluster with an owner alive
    or a client connected, and the rehearsal's ``runs`` while a ``rehearse.sh`` runs are kept."""
    out: list[tuple[Path, int]] = []

    def drop(path: Path, cluster: bool = False) -> None:
        size = _size(path) if path.is_dir() else (path.stat().st_size if path.exists() else 0)
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
        if root.is_dir() and not _cluster_in_use(root):
            drop(root, cluster=True)
    for base in sorted(tmp.glob("pytest-of-*")):
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
    if not any(s.endswith("rehearse.sh") for s in busy):  # between two cases no process names runs/ itself
        work.append(rehearsal / "runs")
    for path in sorted(work):
        if path.exists() and not _in_use(path, busy):
            drop(path)
    runs = sorted(p for p in (repo / ".cache" / "complete-run").glob("*") if p.is_dir())
    for run in runs[:-2]:
        for tgz in sorted([*run.glob("shard-*/results.tgz"), *run.glob("shard-*/src.tgz")]):
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
    """Drop every schema whose name starts with ``prefix``."""
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
    ap.add_argument("cmd", nargs="?", choices=["start", "stop", "url", "gc", "clean-tmp"])
    ap.add_argument("root", nargs="?", type=Path)
    ap.add_argument("--gc", nargs="?", const="", metavar="DIR", help="the gc command (DIR: where to look)")
    ap.add_argument("--dry-run", action="store_true", help="clean-tmp: list, remove nothing")
    a = ap.parse_args(argv)
    cmd = "gc" if a.gc is not None else a.cmd
    if a.gc:
        a.root = Path(a.gc)
    if cmd in ("start", "stop", "url") and a.root is None:
        ap.error(f"{cmd} needs a directory")
    if cmd == "start":
        print(ensure(a.root))
    elif cmd == "stop":
        stop(a.root)
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
