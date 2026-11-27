"""prof16 stop-gap (CODED-PROFILE ruling Q2): the lake marks pandas absent when it starts, so DuckDB's binding of a pid
list parameter does not search ``sys.path`` for pandas twice per element (53.7 % of a SCREEN job at 100k patients,
where every query carries the whole hospital's pids)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.nodb

ROOT = Path(__file__).resolve().parents[2]

# a fresh interpreter in which pandas is not installed, as in the lake image; every look for it is counted
PROBE = r"""
import importlib.abc
import sys

seen = []


class Absent(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "pandas":
            seen.append(name)
            raise ModuleNotFoundError(name)
        return None


sys.meta_path.insert(0, Absent())
sys.modules.pop("pandas", None)
import lake.store  # noqa: E402,F401  the lake's start
import duckdb  # noqa: E402

at_start = len(seen)
pids = [f"p{i:05d}" for i in range(5000)]
duckdb.connect().execute("SELECT count(*) FROM range(3) WHERE list_contains($1, range::VARCHAR)", [pids]).fetchall()
print(at_start, len(seen) - at_start)
"""


def test_a_pid_list_parameter_never_looks_for_pandas_once_the_lake_has_started() -> None:
    env = {**os.environ, "PYTHONPATH": "libs:services:."}
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    at_start, during = (int(x) for x in out.stdout.split())
    assert at_start <= 2, out.stdout  # the lake starts with pyarrow's own two looks (it must see pandas absent first)
    assert during == 0, f"{during} looks for pandas while binding 5,000 pids (two per element before the stop-gap)"
