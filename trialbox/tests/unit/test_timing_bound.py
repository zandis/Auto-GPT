"""rc1 line 1: the nightlies' own reds (tools/timing_bound.py, the Makefile's test-pure). Synthetic data only."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import timing_bound as tb

ROOT = Path(__file__).resolve().parents[2]


def test_a_bound_grows_only_in_a_run_that_measures_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(tb.RUN_DIR_ENV, raising=False)
    assert tb.bound(5.0) == 5.0 and tb.factor() == 1  # a plain run, the pull-request gate and a box keep the bound
    monkeypatch.setenv(tb.RUN_DIR_ENV, str(ROOT))
    assert tb.bound(5.0) == 15.0 and tb.factor() == tb.COVERAGE_FACTOR == 3


def test_the_run_dir_name_is_the_one_the_coverage_run_sets() -> None:
    from tools import coverage_shards

    assert tb.RUN_DIR_ENV == coverage_shards.RUN_DIR_ENV


def test_test_pure_makes_its_test_root_before_the_tests_use_it(tmp_path: Path) -> None:
    """The nightly's `pure` job ran a test that makes a temp file in TB_TEST_ROOT, which nothing had made."""
    root = tmp_path / "tb-tests-x"
    out = subprocess.run(
        ["make", "-n", "test-pure", f"TB_TEST_ROOT={root}"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout
    lines = [ln for ln in out.splitlines() if "pytest" in ln or f'mkdir -p "{root}"' in ln]
    assert lines and lines[0] == f'mkdir -p "{root}"', lines
