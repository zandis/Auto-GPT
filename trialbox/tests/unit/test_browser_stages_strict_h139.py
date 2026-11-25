"""H139-13 (the integrator's 7158672355): a stage that needs the browser never reads as passed when the browser driver
could not be loaded.

In the walk's diagnostic full set, node could not load the browser driver. The walks stage failed at once, as it
runs with TB_STRICT_SKIPS=1. The poc stage "passed" with its 7 tests skipped, and the console stage with 15 skipped.
The full set's console and poc stages (``make test-console``, ``make test-console-e2e``) now allow no skip either. A
browser test without its driver is one plain failure that names it. The unit shards keep the old terms (lane J's
7155589428): there a host with no node still skips the browser tests with their own reasons.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools import full_set

pytestmark = pytest.mark.nodb
ROOT = Path(__file__).resolve().parents[2]
#: a browser test as the console's are written: its skip comes from the shared Node Playwright check
PROBE = """import pytest

from tests.console.test_cjk_layout import _node_playwright


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")
def test_a_page_in_the_browser() -> None:
    assert True
"""


def _recipe(target: str) -> str:
    m = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n)+)", (ROOT / "Makefile").read_text(encoding="utf-8"),
                  re.M)  # fmt: skip
    assert m, target
    return m.group(1)


@pytest.mark.parametrize("target", ["test-console", "test-console-e2e", "test-walks", "test-compose"])
def test_every_full_set_stage_that_needs_the_browser_allows_no_skip(target: str) -> None:
    assert "TB_STRICT_SKIPS=1" in _recipe(target), target


def test_the_full_sets_console_and_poc_stages_run_those_targets() -> None:
    by_name = {s.name: " ".join(" ".join(c) for c in s.commands) for s in full_set.STAGES}
    assert "test-console" in by_name["console"] and "test-console-e2e" in by_name["poc"]


def _run_probe(tmp_path: Path, strict: bool) -> subprocess.CompletedProcess[str]:
    """The probe under this repository's conftest, on a PATH that has no node (python's own folder only)."""
    probe = tmp_path / ("strict" if strict else "plain")
    probe.mkdir()
    (probe / "test_browser_probe.py").write_text(PROBE, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "TB_STRICT", "TB_TEST_DB_URL"))}
    env.update(PATH=str(Path(sys.executable).parent), TB_PG_BIN="/nonexistent", TB_ENV="TEST",
               PYTHONPATH=os.pathsep.join(str(ROOT / p) for p in ("libs", "services", ".")))  # fmt: skip
    if strict:
        env["TB_STRICT_SKIPS"] = "1"
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "-n",
                           "0", "-rs", str(probe), "-p", "tests.conftest", "--rootdir", str(probe), "-c", os.devnull],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=300, check=False)  # fmt: skip


def test_without_node_a_strict_stage_fails_plainly_and_an_ordinary_run_skips(tmp_path: Path) -> None:
    strict = _run_probe(tmp_path, strict=True)
    out = strict.stdout + strict.stderr
    assert strict.returncode != 0, out[-2000:]
    assert "skipped under TB_STRICT_SKIPS=1, which allows no skip" in out and "Node Playwright is not available" in out
    plain = _run_probe(tmp_path, strict=False)
    assert plain.returncode == 0, (plain.stdout + plain.stderr)[-2000:]
    assert "1 skipped" in plain.stdout and "Node Playwright is not available" in plain.stdout
