"""H-145 (#1504, ruling 7161808787): `make test-console` runs the console tests as `make test` runs the unit suite.

The stage takes the same lock as `make test` (the marked TB_TEST_ROOT, flock on its `.lock`), runs the xdist workers
with `-n $(PYTEST_N)` and `--dist worksteal`, keeps TMPDIR and basetemp under the root, and allows no skip
(TB_STRICT_SKIPS=1, tests/conftest.py): a browser file that cannot start its browser fails, it never turns the stage
green. The lead's bench: a run that ignores SIGHUP (nohup) is refused, and so is a root under a folder that others
can write without the sticky bit. Synthetic data only.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
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


def _preflight(root: Path, hup: signal.Handlers) -> subprocess.CompletedProcess[str]:
    make = shutil.which("make")
    if make is None:
        pytest.fail("make is not installed")
    return subprocess.run(
        [make, "--no-print-directory", "test-console-preflight", f"TB_TEST_ROOT={root}", f"PY={sys.executable}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        preexec_fn=lambda: signal.signal(signal.SIGHUP, hup),
    )


#: a stand-in for $(PY): `-m pytest` exits PYTEST_RC, `-m tools.pglocal stop-idle` exits STOP_RC; no cluster, no test
STANDIN = """#!/bin/sh
case "$*" in
  *"-m pytest"*) exit "$PYTEST_RC" ;;
  *"stop-idle"*) echo "stand-in stop-idle exits $STOP_RC" >&2; exit "$STOP_RC" ;;
esac
exit 99
"""


def _locked(tmp_path: Path, pytest_rc: int, stop_rc: int) -> tuple[subprocess.CompletedProcess[str], Path]:
    make = shutil.which("make")
    if make is None:
        pytest.fail("make is not installed")
    tmp_path.mkdir(parents=True, exist_ok=True)
    py = tmp_path / "standin-python"
    py.write_text(STANDIN, encoding="utf-8")
    py.chmod(0o755)
    root = tmp_path / "root"
    (root / "pytest").mkdir(parents=True)
    env = {**os.environ, "PYTEST_RC": str(pytest_rc), "STOP_RC": str(stop_rc)}
    r = subprocess.run(
        [make, "--no-print-directory", "test-console-locked", f"TB_TEST_ROOT={root}", f"PY={py}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )
    return r, root


def test_h145_a_failed_cleanup_fails_a_green_console_run(tmp_path: Path) -> None:
    """R1 (#1539, 7186855564): pytest green, stop-idle red: the target fails with the cleanup's status, after every
    cleanup step ran."""
    r, root = _locked(tmp_path, pytest_rc=0, stop_rc=3)
    assert r.returncode != 0, r.stderr
    assert "stand-in stop-idle exits 3" in r.stderr and "Error 3" in r.stderr
    assert not (root / "tmp").exists() and not (root / "pytest").exists()
    r, root = _locked(tmp_path / "green", pytest_rc=0, stop_rc=0)
    assert r.returncode == 0, r.stderr
    assert not (root / "pytest").exists()


def test_h145_a_red_console_run_keeps_pytests_status_when_cleanup_also_fails(tmp_path: Path) -> None:
    r, root = _locked(tmp_path, pytest_rc=1, stop_rc=3)
    assert r.returncode != 0
    assert "stand-in stop-idle exits 3" in r.stderr and "Error 1" in r.stderr and "Error 3" not in r.stderr
    assert not (root / "tmp").exists() and (root / "pytest").is_dir()  # a red run keeps its basetemp


def test_h145_the_console_stage_takes_the_unit_lock() -> None:
    unit, console, pre = _recipe("test"), _recipe("test-console"), _recipe("test-console-preflight")
    mark = '$(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)"'
    lock = 'flock -n -E 75 "$(TB_TEST_ROOT)/.lock" $(MAKE) --no-print-directory'
    assert mark in unit and lock in unit
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^test-console: [^\n]*\btest-console-preflight\b", text, re.MULTILINE)
    assert mark in pre, "test-console does not mark its TB_TEST_ROOT as make test does"
    assert f"{lock} test-console-locked" in console, "test-console does not hold make test's lock"


def test_h145_a_run_that_ignores_sighup_is_refused_before_it_touches_the_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    r = _preflight(root, signal.SIG_IGN)
    assert r.returncode != 0 and "SIGHUP is ignored" in r.stderr
    assert not root.exists()
    r = _preflight(root, signal.SIG_DFL)
    assert r.returncode == 0, r.stderr
    assert (root / ".tb-test-root").is_file()


def test_h145_a_root_under_a_folder_others_can_write_is_refused(tmp_path: Path) -> None:
    shared = tmp_path / "open"
    shared.mkdir()
    shared.chmod(0o777)
    r = _preflight(shared / "root", signal.SIG_DFL)
    assert r.returncode != 0 and f"{shared} (drwxrwxrwx) can be written by others" in r.stderr
    shared.chmod(0o1777)  # sticky, as /tmp: others cannot remove or replace what this user made in it
    r = _preflight(shared / "root", signal.SIG_DFL)
    assert r.returncode == 0, r.stderr


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
