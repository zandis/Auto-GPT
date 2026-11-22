"""H-72: ``tools.pglocal.ensure`` called by several processes at once starts one server, and every caller gets its URL.

The PostgreSQL binaries are stand-ins (``TB_PG_BIN``): ``initdb`` and ``pg_ctl start`` each write one line to the
cluster folder's ``calls.log`` and take their time, so that without the cross-process lock two callers that both found
no server would both run them (and one would remove the other's half-made ``data/``)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="flock and the stand-ins' shell")

ROOT = Path(__file__).resolve().parents[2]
N = 6

FAKES = {
    # initdb -D <data> ...: slow, then PG_VERSION
    "initdb": r"""#!/bin/sh
d=$2; echo "initdb $$" >> "$(dirname "$d")/calls.log"
[ ! -e "$d" ] || { echo "initdb: directory $d exists" >&2; exit 1; }
mkdir -p "$d" && sleep 0.5 && echo 16 > "$d/PG_VERSION"
""",
    # pg_ctl -D <data> -l <log> -o <opts> -w start: slow, then the pid file and the socket's stand-in
    "pg_ctl": r"""#!/bin/sh
d=$2; r=$(dirname "$d")
case " $* " in *" start "*)
  echo "start $$" >> "$r/calls.log"
  [ ! -e "$d/postmaster.pid" ] || { echo "pg_ctl: another server might be running" >&2; exit 1; }
  sleep 0.5; echo $$ > "$d/postmaster.pid"; touch "$r/run/.ready" ;;
esac
exit 0
""",
    # pg_isready -h <run> -q: ready once the stand-in server started
    "pg_isready": r"""#!/bin/sh
[ -e "$2/.ready" ]
""",
    "psql": "#!/bin/sh\necho 1\n",
}


@pytest.fixture
def fakes() -> Iterator[Path]:
    """The stand-in binaries in a folder anyone may read and run: as root, pglocal runs them as another user."""
    d = Path(tempfile.mkdtemp(prefix="tb-pgfakes-"))
    d.chmod(0o755)
    for name, text in FAKES.items():
        (d / name).write_text(text)
        (d / name).chmod(0o755)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def cluster() -> Iterator[Path]:
    d = Path(tempfile.mkdtemp(prefix="tb-pglock-"))
    d.chmod(0o755)
    yield d / "pg-h72"
    shutil.rmtree(d, ignore_errors=True)


def _callers(fakes: Path, cluster: Path, n: int) -> list[subprocess.CompletedProcess[str]]:
    """n processes, each released at the same moment (a go file), each calling ensure() on the same folder."""
    go = cluster.parent / "go"
    code = ("import sys, time; from pathlib import Path\n"
            "go = Path(sys.argv[2])\n"
            "while not go.exists(): time.sleep(0.005)\n"
            "import tools.pglocal as p; print(p.ensure(Path(sys.argv[1])))\n")  # fmt: skip
    env = {**os.environ, "TB_PG_BIN": str(fakes), "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    procs = [subprocess.Popen([sys.executable, "-c", code, str(cluster), str(go)], cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(n)]  # fmt: skip
    time.sleep(1.0)  # every caller is waiting on the go file
    go.touch()
    out = []
    for p in procs:
        o, e = p.communicate(timeout=120)
        out.append(subprocess.CompletedProcess(p.args, p.returncode, o, e))
    return out


def test_callers_at_once_start_one_server_and_all_get_its_url(fakes: Path, cluster: Path) -> None:
    done = _callers(fakes, cluster, N)
    assert all(r.returncode == 0 for r in done), [r.stderr[-400:] for r in done if r.returncode]
    urls = {r.stdout.strip() for r in done}
    assert len(urls) == 1 and urls.pop().endswith(f"?host={(cluster / 'run').resolve()}")
    calls = (cluster / "calls.log").read_text().split()
    assert calls.count("initdb") == 1 and calls.count("start") == 1, calls
    assert (cluster / "data" / "PG_VERSION").read_text().strip() == "16"


def test_a_later_caller_reuses_the_server_without_the_lock_or_a_start(fakes: Path, cluster: Path) -> None:
    first = _callers(fakes, cluster, 1)
    assert first[0].returncode == 0, first[0].stderr
    (cluster / ".ensure.lock").unlink()  # a running server is reused before the lock is even taken
    again = _callers(fakes, cluster, 2)
    assert all(r.returncode == 0 for r in again), [r.stderr[-400:] for r in again]
    assert (cluster / "calls.log").read_text().split().count("start") == 1
    assert not (cluster / ".ensure.lock").exists()


def test_the_lock_file_does_not_make_a_failed_cluster_folder_unknown_to_the_gc(cluster: Path) -> None:
    import tools.pglocal as pglocal

    cluster.mkdir()
    (cluster / pglocal.ENSURE_LOCK).touch()
    (cluster / "server.log").touch()
    assert pglocal._is_cluster_dir(cluster)
