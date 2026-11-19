"""Card H-52, the static guard: every ``pq.read_table`` in libs/, services/ and tools/ reads with ``use_threads=False``
(a threaded read can abort a one-shot process at exit; docs/handover/parquet-exit-abort-2026-11-19.md). The subprocess
loop of the rehearsal's command is tests/unit/test_parquet_read_exit_abort_h52.py."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]  # D-1119: the guard step of `checks`; no database

ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("libs", "services", "tools")
READERS = {"read_table"}  # pyarrow.parquet's whole-table reader; ParquetFile and dataset() are not used here (H-52)


def _parquet_aliases(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.asname or a.name for a in node.names if a.name == "pyarrow.parquet"}
        elif isinstance(node, ast.ImportFrom) and node.module == "pyarrow":
            names |= {a.asname or a.name for a in node.names if a.name == "parquet"}
    return names


def _sites() -> list[tuple[str, int, bool]]:
    out: list[tuple[str, int, bool]] = []
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            if ".venv" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "pyarrow" not in text:
                continue
            tree = ast.parse(text, str(path))
            aliases = _parquet_aliases(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                f = node.func
                if f.attr in READERS and isinstance(f.value, ast.Name) and f.value.id in aliases:
                    single = any(
                        k.arg == "use_threads" and isinstance(k.value, ast.Constant) and k.value.value is False
                        for k in node.keywords
                    )
                    out.append((str(path.relative_to(ROOT)), node.lineno, single))
    return out


def test_every_parquet_read_is_single_threaded() -> None:
    sites = _sites()
    # the scan must see the sites it guards (15 at H-52); an empty scan would pass for the wrong reason
    assert len(sites) >= 15, sites
    threaded = [f"{p}:{n}" for p, n, single in sites if not single]
    assert not threaded, (
        "pq.read_table without use_threads=False (H-52: a one-shot process can abort at exit after a threaded read): "
        + ", ".join(threaded)
    )
