"""H-73 (D-1355): `make test` runs the xdist workers with `--dist worksteal`, and a serial run has no `--dist`.

Under xdist's default `load` the seven long role walks of tests/console/test_prefs_10f1.py ran one after another on
one worker: unit-shard (1/6) was cancelled at its 40-minute limit. Synthetic data only.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.nodb


def _dry(n: str, tmp_path: Path) -> str:
    make = shutil.which("make")
    if make is None:
        pytest.fail("make is not installed")
    r = subprocess.run(
        [make, "-n", "--no-print-directory", "test-locked", f"PYTEST_N={n}", f"TB_TEST_ROOT={tmp_path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return r.stdout


def test_h73_the_workers_steal_queued_tests(tmp_path: Path) -> None:
    assert "-m pytest -q -n auto --dist worksteal " in _dry("auto", tmp_path)
    assert "-m pytest -q -n 4 --dist worksteal " in _dry("4", tmp_path)


def test_h73_a_serial_run_names_no_schedule(tmp_path: Path) -> None:
    out = _dry("0", tmp_path)
    assert "-m pytest -q -n 0 " in out and "--dist" not in out
