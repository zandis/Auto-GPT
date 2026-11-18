"""D-999: the make targets that run the e2e tests mark the branch's test root first.

The nightly compose job of 2026-11-17 (trialbox-e2e.yml, `make test-compose`) failed in the new-study walk, its first
night in that job (H-10): the walk starts a local box with ``tools/demo.py``, which marks ``TB_TEST_ROOT``
(``pglocal.mark_test_root``), and the root, already holding files the job's earlier steps wrote, had no
``.tb-test-root`` marker, so the guard refused it ("it holds files and no .tb-test-root marker (not a test root)").
``make test``, ``make walk`` and the walk targets mark the root before they run; ``test-compose`` and ``test-e2e``,
whose pytest collects ``tests/e2e``, did not.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARK = '@PYTHONPATH=libs:services:. $(PY) -m tools.pglocal mark "$(TB_TEST_ROOT)" >/dev/null'


def _recipe(target: str) -> list[str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n)+)", text, re.M)
    assert m, f"no target {target}"
    return [ln[1:] for ln in m.group(1).splitlines()]


def test_the_e2e_targets_mark_the_root_before_pytest() -> None:
    for target in ("test-compose", "test-e2e"):
        lines = _recipe(target)
        runs = next(i for i, ln in enumerate(lines) if "-m pytest" in ln)
        assert MARK in lines[:runs], f"{target} runs pytest before it marks TB_TEST_ROOT"


def test_the_e2e_tests_that_start_a_box_are_what_these_targets_collect() -> None:
    """The walk tests start tools/demo.py, which refuses an unmarked root that holds files."""
    demo = (ROOT / "tools" / "demo.py").read_text(encoding="utf-8")
    assert "pglocal.mark_test_root(" in demo
    starters = [p.name for p in (ROOT / "tests" / "e2e").glob("test_*.py") if "tools.demo" in p.read_text("utf-8")]
    assert "test_new_study_walk.py" in starters
    assert "tests/e2e" in " ".join(_recipe("test-compose")) and "-m e2e" in " ".join(_recipe("test-e2e"))
