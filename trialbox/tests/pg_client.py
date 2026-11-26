"""H-139: the PostgreSQL client tools a test hands to the product, from the test cluster's own server folder.

The test cluster is started from ``tools.pglocal.bindir()``, which is not always on PATH: a host may keep its
PostgreSQL in a folder of its own, with no ``psql`` on PATH. The product runs ``psql``, ``pg_dump`` and ``pg_restore``
as ``TB_PSQL_CMD``, ``TB_PG_DUMP_CMD`` and ``TB_PG_RESTORE_CMD`` say (the bare names by default), so a test that runs
a backup or a restore on the host gives it the tools beside the server it talks to. A folder without a tool leaves
its bare name, as before.
"""

from __future__ import annotations

import os
import shlex

import pytest

TOOLS = {"psql": "TB_PSQL_CMD", "pg_dump": "TB_PG_DUMP_CMD", "pg_restore": "TB_PG_RESTORE_CMD"}


def tool(name: str) -> str:
    """The path of the client tool ``name`` beside the test cluster's server, else ``name``."""
    from tools import pglocal

    try:
        path = pglocal.bindir() / name
    except RuntimeError:
        return name
    return str(path) if path.is_file() and os.access(path, os.X_OK) else name


def env() -> dict[str, str]:
    """The product's settings for the three client tools, each one command line (``shlex``) as the product reads it."""
    return {var: shlex.quote(tool(name)) for name, var in TOOLS.items()}


def setenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same three settings in the process environment, for code that reads it (the CLI, the drills)."""
    for var, cmd in env().items():
        monkeypatch.setenv(var, cmd)
