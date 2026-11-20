"""Card H-52, the static guard: every ``pq.read_table`` in libs/, services/ and tools/ reads with ``use_threads=False``
(a threaded read can abort a one-shot process at exit; docs/handover/parquet-exit-abort-2026-11-19.md). The subprocess
loop of the rehearsal's command is tests/unit/test_parquet_read_exit_abort_h52.py.

Card H-62 (docs/handover/exit-abort-third-sighting-2026-11-19.md): ``read_table`` goes through the dataset scanner,
which still runs on Arrow's IO thread pool with ``use_threads=False``. When its source is a Python object (``bytes`` in
``pa.BufferReader``, ``io.BytesIO``), that pool's worker can drop the last reference after the interpreter has begun to
finalize; taking the GIL then ends the thread with ``pthread_exit``, and the forced unwind through Arrow's ``noexcept``
destructor calls ``std::terminate``. So an in-memory source is read with ``pq.ParquetFile(src).read(use_threads=False)``,
which starts no thread, and both forms count as guarded sites."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TypeGuard

import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("libs", "services", "tools")
READERS = {"read_table"}  # pyarrow.parquet's whole-table reader (dataset() is not used here)
# H-62: a source built in memory from a Python object; read_table would hand it to the IO pool's worker thread
IN_MEMORY = {"BufferReader", "BytesIO", "py_buffer", "BufferOutputStream", "memoryview", "bytes", "bytearray"}


def _parquet_aliases(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.asname or a.name for a in node.names if a.name == "pyarrow.parquet"}
        elif isinstance(node, ast.ImportFrom) and node.module == "pyarrow":
            names |= {a.asname or a.name for a in node.names if a.name == "parquet"}
    return names


def _single(call: ast.Call) -> bool:
    return any(
        k.arg == "use_threads" and isinstance(k.value, ast.Constant) and k.value.value is False for k in call.keywords
    )


def _in_memory(call: ast.Call) -> bool:
    """The source of a ``read_table`` call is built in memory from a Python object (H-62)."""
    src = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "source"), None)
    if isinstance(src, ast.Constant):
        return isinstance(src.value, bytes)
    if not isinstance(src, ast.Call):
        return False  # a name or a path expression; its type is not known statically
    f = src.func
    return (f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else "") in IN_MEMORY


def _scan() -> tuple[list[tuple[str, int, bool]], list[str], list[str]]:
    """(every guarded read: path, line, single-threaded), read_table calls on an in-memory source, and ParquetFile
    objects not read at once with ``.read(...)`` (whose read this guard cannot see)."""
    sites: list[tuple[str, int, bool]] = []
    in_memory: list[str] = []
    loose: list[str] = []
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            if ".venv" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "pyarrow" not in text:
                continue
            tree = ast.parse(text, str(path))
            aliases = _parquet_aliases(tree)
            rel = str(path.relative_to(ROOT))
            read_at_once: set[int] = set()  # id() of ParquetFile(...) calls that are the target of .read(...)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                f = node.func
                if f.attr in READERS and isinstance(f.value, ast.Name) and f.value.id in aliases:
                    sites.append((rel, node.lineno, _single(node)))
                    if _in_memory(node):
                        in_memory.append(f"{rel}:{node.lineno}")
                elif f.attr == "read" and _is_parquet_file(f.value, aliases):
                    read_at_once.add(id(f.value))
                    sites.append((rel, node.lineno, _single(node)))
            for node in ast.walk(tree):
                if _is_parquet_file(node, aliases) and id(node) not in read_at_once:
                    loose.append(f"{rel}:{node.lineno}")
    return sites, in_memory, loose


def _is_parquet_file(node: ast.AST, aliases: set[str]) -> TypeGuard[ast.Call]:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "ParquetFile"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in aliases
    )


def _sites() -> list[tuple[str, int, bool]]:
    return _scan()[0]


def test_every_parquet_read_is_single_threaded() -> None:
    sites = _sites()
    # the scan must see the sites it guards (15 at H-52: 11 read_table and 4 ParquetFile reads since H-62); an empty
    # scan would pass for the wrong reason
    assert len(sites) >= 15, sites
    threaded = [f"{p}:{n}" for p, n, single in sites if not single]
    assert not threaded, (
        "pq.read_table or pq.ParquetFile(...).read without use_threads=False (H-52: a one-shot process can abort at exit "
        "after a threaded read): " + ", ".join(threaded)
    )


def test_no_parquet_read_hands_a_python_object_to_the_io_pool() -> None:
    sites, in_memory, loose = _scan()
    assert sum(1 for p, _, _ in sites if p.endswith(("installed.py", "data_scan.py", "sets.py"))) >= 4, sites
    assert not in_memory, (
        "pq.read_table on an in-memory source (H-62: Arrow's IO pool can release the Python object after the "
        "interpreter has begun to finalize, and the process aborts at exit); read it with "
        "pq.ParquetFile(src).read(use_threads=False): " + ", ".join(in_memory)
    )
    assert not loose, "pq.ParquetFile(...) not read at once with .read(use_threads=False): " + ", ".join(loose)


def test_the_guard_flags_the_h62_forms() -> None:
    """The guard's own rules on the forms it must catch and the ones it must pass (no file of the tree needed)."""
    src = (
        "import io\nimport pyarrow as pa\nimport pyarrow.parquet as pq\n"
        "pq.read_table(pa.BufferReader(d), use_threads=False)\n"
        "pq.read_table(io.BytesIO(d), use_threads=False)\n"
        "pq.read_table(path, use_threads=False)\n"
        "pq.ParquetFile(io.BytesIO(d)).read(use_threads=False)\n"
        "f = pq.ParquetFile(io.BytesIO(d))\n"
    )
    tree = ast.parse(src)
    aliases = _parquet_aliases(tree)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    reads = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "read_table"]
    assert [_in_memory(c) for c in sorted(reads, key=lambda c: c.lineno)] == [True, True, False]
    pfs = sorted((c for c in calls if _is_parquet_file(c, aliases)), key=lambda c: c.lineno)
    assert [c.lineno for c in pfs] == [7, 8]
