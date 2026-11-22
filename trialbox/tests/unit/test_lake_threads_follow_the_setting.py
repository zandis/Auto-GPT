"""The lake's thread pools follow TB_LAKE_THREADS, or its declared default, and never the host's CPU count.

The MVP walk on a many-core host: with the setting unset (outside Compose's default), DuckDB, Arrow and the BLAS pools
each took one thread per core in both HTTP workers and the rebuild, and the lake reached the process limit. Each probe
runs in a fresh interpreter with no thread variable set and a planted CPU count of 512, as a large server reports it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from tb_common.config import DECLARED

ROOT = Path(__file__).resolve().parents[2]
PLANTED_CPUS = 512
POOLS = (
    "TB_LAKE_THREADS",
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "OMP_THREAD_LIMIT",
    "MKL_NUM_THREADS",
    "ARROW_IO_THREADS",
)

PROBE = textwrap.dedent(
    """
    import json, os, multiprocessing, pathlib
    os.cpu_count = lambda: %(cpus)d
    multiprocessing.cpu_count = lambda: %(cpus)d
    %(before)s
    import lake
    from lake import app, store
    import duckdb, pyarrow
    con = store._connect(pathlib.Path(%(db)r))
    out = {
        "connection": int(con.execute("SELECT current_setting('threads')").fetchone()[0]),
        "default": int(duckdb.execute("SELECT current_setting('threads')").fetchone()[0]),
        "arrow_cpu": pyarrow.cpu_count(),
        "arrow_io": pyarrow.io_thread_count(),
        "env": {k: os.environ.get(k) for k in %(pools)r},
        "rebuild_env": {k: app._child_env().get(k) for k in %(pools)r},
    }
    con.close()
    print(json.dumps(out))
    """
)


# Arrow's pools start lazily: a process that used them before importing ``lake`` has them at one thread per core.
ARROW_FIRST = (
    "import pyarrow, pyarrow.compute, pyarrow.parquet; "
    "t = pyarrow.table({'x': list(range(200000))}); pyarrow.compute.sum(t['x']); "
    "pyarrow.parquet.write_table(t, %(db)r + '.parquet'); pyarrow.parquet.read_table(%(db)r + '.parquet')"
)


def _probe(tmp_path: Path, before: str = "", **setting: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in POOLS}
    env.update(setting)
    env["PYTHONPATH"] = os.pathsep.join(str(ROOT / p) for p in ("libs", "services", "."))
    db = str(tmp_path / "probe.duckdb")
    code = PROBE % {"cpus": PLANTED_CPUS, "db": db, "pools": POOLS, "before": before % {"db": db}}
    return subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True, check=False, timeout=120
    )


def _caps(tmp_path: Path, before: str = "", **setting: str) -> dict[str, object]:
    done = _probe(tmp_path, before, **setting)
    assert done.returncode == 0, done.stderr[-2000:]
    caps: dict[str, object] = json.loads(done.stdout.strip().splitlines()[-1])
    return caps


def _assert_every_pool(caps: dict[str, object], expected: int) -> None:
    assert caps["connection"] == expected
    assert caps["default"] == expected
    assert caps["arrow_cpu"] == expected
    assert caps["arrow_io"] == expected
    assert caps["env"] == {k: str(expected) for k in POOLS}
    assert caps["rebuild_env"] == {k: str(expected) for k in POOLS}


def test_unset_takes_the_declared_default_on_a_512_core_host(tmp_path: Path) -> None:
    default = int(DECLARED["TB_LAKE_THREADS"].default)
    assert default < PLANTED_CPUS
    _assert_every_pool(_caps(tmp_path), default)


def test_every_pool_follows_the_setting(tmp_path: Path) -> None:
    _assert_every_pool(_caps(tmp_path, TB_LAKE_THREADS="3"), 3)


def test_arrow_pools_used_before_the_lake_are_bounded_too(tmp_path: Path) -> None:
    _assert_every_pool(_caps(tmp_path, ARROW_FIRST, TB_LAKE_THREADS="1"), 1)


def test_one_setting_governs_a_pool_variable_the_operator_set(tmp_path: Path) -> None:
    _assert_every_pool(_caps(tmp_path, TB_LAKE_THREADS="3", ARROW_IO_THREADS="8", OMP_NUM_THREADS="8"), 3)


@pytest.mark.parametrize("bad", ["0", "-2", "many", "1.5", "\u00b2"])
def test_a_setting_that_is_not_a_count_stops_the_lake_with_its_name(tmp_path: Path, bad: str) -> None:
    done = _probe(tmp_path, TB_LAKE_THREADS=bad)
    assert done.returncode != 0
    assert "LakeThreadsInvalid" in done.stderr
    assert "TB_LAKE_THREADS" in done.stderr
