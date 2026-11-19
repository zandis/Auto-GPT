"""H-63: coverage data of tests that ran is never lost in silence (tools/coverage_shards.py).

A shard's ``.coverage`` once held about 18,700 fewer lines than the same shard on the run before, with every test
passed and no line in the log: the lines of one xdist worker's tests. The ratchet then read the loss as a fall. These
tests hold the two guards: a worker that returns no coverage data fails the pytest run by name, and ``unit`` refuses to
combine when a shard's data is absent, naming the shard.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from coverage import CoverageData

from tools import coverage_shards as cs

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT.parent / ".github" / "workflows" / "trialbox-ci.yml"


def _shard(root: Path, i: int, n: int, lines: dict[str, list[int]] | None, *, db: bool = True) -> None:
    d = root / f"unit-shard-{i}"
    d.mkdir(parents=True)
    (d / "shard.json").write_text(json.dumps({"shard": i, "count": n, "collected": [], "kept": []}), encoding="utf-8")
    if db:
        data = CoverageData(str(d / "coverage.db"))
        data.add_lines(lines or {})
        data.write()


def test_every_shard_present_is_counted_shard_by_shard(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _shard(tmp_path, 1, 2, {"/x/a.py": [1, 2, 3]})
    _shard(tmp_path, 2, 2, {"/x/b.py": [1], "/x/c.py": [4, 5]})
    found, problems = cs.check(tmp_path)
    assert problems == []
    assert [(s.shard, s.files, s.lines) for s in found] == [(1, 1, 3), (2, 2, 3)]
    assert cs.main(["check", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "shard 1: 3 lines in 1 files" in out and "shard 2: 3 lines in 2 files" in out


def test_a_shard_without_its_data_is_named_and_the_ratchet_does_not_judge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _shard(tmp_path, 1, 3, {"/x/a.py": [1]})
    _shard(tmp_path, 2, 3, None, db=False)  # the record came back, the coverage data did not
    _shard(tmp_path, 3, 3, {"/x/a.py": [2]})
    assert cs.main(["check", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "shard 2/3: no coverage data" in err and "does not judge" in err
    assert "shard 1/3" not in err and "shard 3/3" not in err


def test_a_shard_whose_record_is_missing_too_is_still_named(tmp_path: Path) -> None:
    _shard(tmp_path, 1, 2, {"/x/a.py": [1]})  # shard 2 uploaded nothing at all
    _, problems = cs.check(tmp_path)
    assert problems == [f"shard 2/2: no coverage data ({tmp_path / 'unit-shard-2' / 'coverage.db'} is missing)"]


def test_an_empty_or_unreadable_data_file_is_a_problem(tmp_path: Path) -> None:
    _shard(tmp_path, 1, 2, {})
    _shard(tmp_path, 2, 2, None, db=False)
    (tmp_path / "unit-shard-2" / "coverage.db").write_bytes(b"not a database at all, just bytes" * 40)
    _, problems = cs.check(tmp_path)
    assert len(problems) == 2
    assert "shard 1/2" in problems[0] and "no measured line" in problems[0]
    assert "shard 2/2" in problems[1] and "cannot be read" in problems[1]


def test_no_record_or_records_that_disagree_are_refused(tmp_path: Path) -> None:
    assert cs.check(tmp_path)[1] == [f"no shard record under {tmp_path}: the number of shards is unknown"]
    _shard(tmp_path, 1, 2, {"/x/a.py": [1]})
    _shard(tmp_path, 2, 3, {"/x/a.py": [1]})
    assert cs.check(tmp_path)[1] == ["the shard records disagree on the number of shards: [2, 3]"]


class _Pm:
    def __init__(self, cov: object | None) -> None:
        self.cov = cov

    def get_plugin(self, name: str) -> object | None:
        return self.cov if name == "_cov" else None


def _watch(cov: object | None) -> cs.WorkerWatch:
    return cs.WorkerWatch(SimpleNamespace(pluginmanager=_Pm(cov)))  # type: ignore[arg-type]


def _node(wid: str, output: dict[str, object] | None) -> SimpleNamespace:
    n = SimpleNamespace(gateway=SimpleNamespace(id=wid))
    if output is not None:
        n.workeroutput = output
    return n


def test_the_watch_names_a_worker_that_went_down_or_returned_no_data() -> None:
    active = SimpleNamespace(_disabled=False, cov_controller=object())
    w = _watch(active)
    w.pytest_testnodedown(_node("gw0", {"cov_worker_node_id": "gw0"}), None)  # a worker that finished well
    w.pytest_testnodedown(_node("gw1", None), "Not properly terminated")  # died: xdist replaces it
    w.pytest_testnodedown(_node("gw2", {"exitstatus": 0}), None)  # finished, but without its coverage data
    assert [wid for wid, _ in w.lost] == ["gw1", "gw2"]
    msgs = w.messages()
    assert "worker gw1 returned no coverage data (it went down: Not properly terminated)" in msgs[0]
    assert "H-63" in msgs[1] and "finished without its coverage data" in msgs[1]


@pytest.mark.parametrize("cov", [None, SimpleNamespace(_disabled=True, cov_controller=None)])
def test_without_coverage_the_watch_says_nothing(cov: object | None) -> None:
    w = _watch(cov)
    w.pytest_testnodedown(_node("gw1", None), "Not properly terminated")
    assert w.lost == []


_CONFTEST = """
import os
import pytest

if os.environ.get("H63_WATCH") == "1":
    def pytest_configure(config):
        from tools import coverage_shards
        coverage_shards.register(config)

@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtestloop(session):
    result = yield
    # the stand-in for a native abort after a worker's last test, before pytest-cov keeps its data (no test pending)
    if getattr(session.config, "workerinput", {}).get("workerid") == "gw1":
        os._exit(134)
    return result
"""


def _run_project(tmp_path: Path, watch: bool) -> subprocess.CompletedProcess[str]:
    proj = tmp_path / ("watched" if watch else "unwatched")
    proj.mkdir()
    (proj / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (proj / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    (proj / "measured.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    tests = "".join(f"def test_{i}():\n    from measured import one\n    assert one() == 1\n\n" for i in range(8))
    (proj / "test_some.py").write_text(textwrap.dedent(tests), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "COV_", "COVERAGE_", "TB_COVERAGE_"))}
    env["PYTHONPATH"] = os.pathsep.join([str(proj), str(ROOT)])
    env["H63_WATCH"] = "1" if watch else "0"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-n", "2", "-p", "no:randomly", "-p", "no:cacheprovider",
         "--cov=measured", "--cov-report=", "-W", "ignore::pytest.PytestUnraisableExceptionWarning", "test_some.py"],
        cwd=proj, env=env, capture_output=True, text=True, timeout=300, check=False,
    )  # fmt: skip


def test_a_worker_lost_after_its_last_test_was_silent_and_now_fails_the_run(tmp_path: Path) -> None:
    quiet = _run_project(tmp_path, watch=False)
    assert quiet.returncode == 0, quiet.stdout[-2000:] + quiet.stderr[-2000:]  # the loss as CI saw it: silent
    assert "8 passed" in quiet.stdout  # xdist's one "node down" line is all there is
    loud = _run_project(tmp_path, watch=True)
    assert loud.returncode == 1, loud.stdout[-2000:] + loud.stderr[-2000:]
    assert "8 passed" in loud.stdout
    assert "coverage_shards: xdist worker gw1 returned no coverage data" in loud.stdout + loud.stderr


def test_unit_checks_every_shards_data_before_it_combines() -> None:
    if not WORKFLOW.is_file():
        pytest.skip("workflows not in this checkout")
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["unit"]["steps"]
    names = [str(s.get("name", "")) for s in steps]
    runs = [str(s.get("run", "")) for s in steps]
    at = names.index("Every shard's coverage data is present")
    assert runs[at].strip() == '.venv/bin/python -m tools.coverage_shards check "$RUNNER_TEMP/shards"'
    assert "if" not in steps[at]  # a missing shard stops the job before the combine and the ratchet
    assert (
        names.index("Every collected test ran in exactly one shard")
        < at
        < names.index("Combined coverage of all shards")
    )
    assert at < names.index("Coverage ratchet")


def test_the_suite_registers_the_watch() -> None:
    text = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "coverage_shards.register(config)" in text


_NESTED = """
import os, subprocess, sys

def test_runs_a_nested_pytest_with_the_outer_environment():
    # what tests/unit/test_test_shard.py did before H-63: its own pytest, in the same folder, with PYTEST_ADDOPTS
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-n", "0", "-p", "no:cacheprovider", "--collect-only",
                        "test_nothing.py"], capture_output=True, text=True)
    print("NESTED", r.returncode, r.stdout[-600:], r.stderr[-600:])
    assert r.returncode == 4 and "would combine and delete" in r.stdout + r.stderr
"""


def test_a_nested_pytest_with_coverage_in_the_same_folder_is_refused(tmp_path: Path) -> None:
    proj = tmp_path / "nested"
    proj.mkdir()
    (proj / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (proj / "conftest.py").write_text(
        "def pytest_configure(config):\n    from tools import coverage_shards\n    coverage_shards.register(config)\n",
        encoding="utf-8",
    )
    (proj / "test_outer.py").write_text(_NESTED, encoding="utf-8")
    (proj / "test_nothing.py").write_text("def test_n():\n    pass\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "COV_", "COVERAGE_", "TB_COVERAGE_"))}
    env["PYTHONPATH"] = os.pathsep.join([str(proj), str(ROOT)])
    env["PYTEST_ADDOPTS"] = "--cov=. --cov-report="  # as CI sets it for the shards
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-s", "-n", "0", "-p", "no:randomly", "-p", "no:cacheprovider",
         "test_outer.py"],
        cwd=proj, env=env, capture_output=True, text=True, timeout=300, check=False,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert "NESTED 4" in r.stdout
