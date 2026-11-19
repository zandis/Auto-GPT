"""E-PURE (lane D's nightly red, 2026-11-18): a test in the no-database tier never asks for the database.

``make test-pure`` runs the tests marked ``nodb`` (a module's ``pytestmark``, or a module of ``PURE_MODULES`` in
``tests/conftest.py``) with no PostgreSQL at all. A test there that takes ``db_url`` (or ``pg_cluster_url``) starts
a cluster that cannot start, and the whole run stops. The ``nodb`` mark of a module cannot be lifted for one test, so
a test that needs the database lives in a module that is not pure. This reads the files; it starts nothing.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DB_FIXTURES = {"db_url", "pg_cluster_url"}

pytestmark = pytest.mark.nodb


def _pure_files() -> set[Path]:
    src = (ROOT / "tests/conftest.py").read_text(encoding="utf-8")
    listed = re.search(r"PURE_MODULES: tuple\[str, \.\.\.\] = \((.*?)\n\)", src, re.S)
    assert listed, "tests/conftest.py no longer lists PURE_MODULES the way this guard reads it"
    files = {ROOT / m for m in re.findall(r'"([^"]+)"', listed.group(1))}
    for f in (ROOT / "tests").rglob("test_*.py"):  # a module that marks itself nodb as a whole
        if re.search(r"^pytestmark\s*=.*\bnodb\b", f.read_text(encoding="utf-8"), re.M):
            files.add(f)
    return files


def test_no_pure_test_takes_the_database() -> None:
    found = []
    for f in sorted(_pure_files()):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                taken = DB_FIXTURES & {a.arg for a in node.args.args}
                if taken:
                    found.append(f"{f.relative_to(ROOT)}::{node.name} takes {', '.join(sorted(taken))}")
    assert not found, (
        "a test in the no-database tier asks for the database; move it to a module that is not pure:\n"
        + ("\n".join(found))
    )
