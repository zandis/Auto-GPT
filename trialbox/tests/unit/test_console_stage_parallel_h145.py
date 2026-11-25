"""H-145 (#1504, ruling 7161808787): `make test-console` runs the console tests as `make test` runs the unit suite.

The stage takes the same lock as `make test` (the marked TB_TEST_ROOT, flock on its `.lock`), runs the xdist workers
with `-n $(PYTEST_N)` and `--dist worksteal`, keeps TMPDIR and basetemp under the root, and allows no skip
(TB_STRICT_SKIPS=1, tests/conftest.py): a browser file that cannot start its browser fails, it never turns the stage
green. Synthetic data only.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


def _recipe(target: str) -> str:
    """The recipe lines of `target` in the Makefile, joined."""
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n)+)", text, re.MULTILINE)
    assert m is not None, f"the Makefile has no {target} target with a recipe"
    return m.group(1)


def _dry(target: str, n: str, tmp_path: Path) -> str:
    make = shutil.which("make")
    if make is None:
        pytest.fail("make is not installed")
    r = subprocess.run(
        [make, "-n", "--no-print-directory", target, f"PYTEST_N={n}", f"TB_TEST_ROOT={tmp_path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return r.stdout


def test_h145_the_console_stage_takes_the_unit_lock() -> None:
    unit, console = _recipe("test"), _recipe("test-console")
    mark = '$(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)"'
    lock = 'flock -n -E 75 "$(TB_TEST_ROOT)/.lock" $(MAKE) --no-print-directory'
    assert mark in unit and lock in unit
    assert mark in console, "test-console does not mark its TB_TEST_ROOT as make test does"
    assert f"{lock} test-console-locked" in console, "test-console does not hold make test's lock"


def test_h145_the_console_stage_runs_the_workers_and_allows_no_skip() -> None:
    locked = _recipe("test-console-locked")
    assert "-n $(PYTEST_N) $(XDIST_DIST)" in locked
    assert "TB_STRICT_SKIPS=1" in locked
    assert 'TMPDIR="$(TB_TEST_ROOT)/tmp"' in locked and '--basetemp "$(TB_TEST_ROOT)/pytest"' in locked


def test_h145_the_workers_steal_queued_console_tests(tmp_path: Path) -> None:
    out = _dry("test-console-locked", "auto", tmp_path)
    assert "-m pytest -q -n auto --dist worksteal " in out and "tests/console" in out
    assert "TB_STRICT_SKIPS=1" in out
    out4 = _dry("test-console-locked", "4", tmp_path)
    assert "-m pytest -q -n 4 --dist worksteal " in out4


def test_h145_a_serial_console_run_names_no_schedule_and_still_allows_no_skip(tmp_path: Path) -> None:
    out = _dry("test-console-locked", "0", tmp_path)
    assert "-m pytest -q -n 0 " in out and "--dist" not in out
    assert "TB_STRICT_SKIPS=1" in out
