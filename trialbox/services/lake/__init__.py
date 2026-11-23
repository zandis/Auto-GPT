"""The lake's native thread pools follow one setting, never the host's CPU count.

DuckDB, Arrow and the BLAS/OpenMP libraries each start one thread per core unless told otherwise. Two HTTP workers and
the rebuild process each hold those pools, so on a many-core server the lake reaches the container's process limit and
a rebuild stops without an answer. ``TB_LAKE_THREADS`` caps every pool; when it is unset its declared default applies
here, in the code, and not only in Compose. This runs before duckdb's public module is imported, in each worker and in
the rebuild process, which inherits the environment set here.

One setting governs every pool: the library variables below take its value even where the operator set them, as
Compose sets them all to it. Arrow's two pools are bounded here even if Arrow ran before ``lake`` was imported. The
BLAS and OpenMP libraries read their variable once, when they load: a process that loads numpy (pyarrow loads it)
before importing ``lake`` keeps their per-core pools. Both of the lake's entry points (``lake.app`` under uvicorn and
``python -m lake.build``) import ``lake`` first; a tool that does not must set the variables itself.
"""

import os
from collections.abc import MutableMapping

from tb_common.config import DECLARED

SETTING = "TB_LAKE_THREADS"
# The native libraries' own variables: each takes the one setting.
POOL_VARIABLES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "OMP_THREAD_LIMIT", "MKL_NUM_THREADS", "ARROW_IO_THREADS")


class LakeThreadsInvalid(ValueError):
    """The thread setting is not a whole number of at least 1."""


def lake_threads(environ: MutableMapping[str, str]) -> int:
    """The cap for every pool: the setting, else its declared default; the host's CPU count is never read."""
    raw = environ.get(SETTING) or DECLARED[SETTING].default
    raw = raw.strip()
    threads = int(raw) if raw.isascii() and raw.isdigit() else 0
    if threads < 1:
        raise LakeThreadsInvalid(
            f"{SETTING} must be a whole number of at least 1 / {SETTING} 必須是至少 1 的整數 / "
            f"{SETTING} は 1 以上の整数にしてください"
        )
    return threads


def cap_pools(environ: MutableMapping[str, str]) -> int:
    """Write the cap into the environment the libraries and the rebuild process read, then bound DuckDB's default
    connection and Arrow's two pools. The native DuckDB module ships with our pinned wheel and opens no database on
    import; the public module would open its default with one thread per core."""
    threads = lake_threads(environ)
    environ[SETTING] = str(threads)
    for name in POOL_VARIABLES:
        environ[name] = str(threads)

    import _duckdb
    import pyarrow

    _duckdb.set_default_connection(_duckdb.connect(config={"threads": str(threads)}))
    pyarrow.set_cpu_count(threads)
    pyarrow.set_io_thread_count(threads)
    return threads


cap_pools(os.environ)
