"""coverage_shards: the coverage of a test that ran is never lost in silence (card H-63).

    pytest -n auto --cov ...                          # tests/conftest.py: coverage_shards.register(config)
    python -m tools.coverage_shards check DIR         # CI `unit`, before the combine: every shard's data is there

Coverage data was lost without a word, and the ratchet then read the loss as a fall of coverage
(docs/handover/coverage-ratchet-lost-lines-2026-11-19.md). The cause shown, and two more ways the same loss can come:

* **A nested pytest with coverage in the same folder.** A test that runs ``python -m pytest`` in ``trialbox/`` with
  the outer run's environment carries CI's ``PYTEST_ADDOPTS=--cov ...``. At its end pytest-cov combines every
  ``.coverage.*`` file of that folder and deletes them, among them the files that already finished xdist workers of
  the outer run had saved there; the outer run then combines without them. :func:`register` refuses such a nested
  run at once (exit 4, a usage error naming the folder) instead.
* **A worker that went down without returning its data.** Under ``pytest -n``, each xdist worker keeps its own
  coverage and hands it to the controller when it finishes. A worker that dies after its last test (no test is then
  pending, so no test fails) leaves no data, and every line only its tests ran is missing from the shard's
  ``.coverage``. xdist prints one "node down" line and the run stays green; pytest-cov names the worker only in its
  report, and CI runs with ``--cov-report=``. :class:`WorkerWatch` names such a worker and fails the run.
* **A shard whose data never reached ``unit``.** ``coverage combine`` over a glob combines what it finds; a shard
  with no ``coverage.db`` simply is not there. ``check`` reads how many shards the run had from the shards' own
  records (``tools.test_shard``), requires each shard's ``coverage.db`` with measured lines, and prints the lines
  per shard, so that two runs can be compared shard by shard. It never judges coverage itself: that is the ratchet's.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

LEAD = "coverage_shards"
RUN_DIR_ENV = "TB_COVERAGE_RUN_DIR"  # the folder of the run that measures coverage, inherited by what it starts


class WorkerWatch:
    """The xdist controller's side: every worker that went down must have returned its coverage data."""

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.lost: list[tuple[str, str]] = []

    def _measuring(self) -> bool:
        cov = self.config.pluginmanager.get_plugin("_cov")  # pytest-cov's plugin, registered only with --cov
        if cov is None or getattr(cov, "_disabled", True):
            return False
        return getattr(cov, "cov_controller", None) is not None

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodedown(self, node: Any, error: object | None) -> None:
        if not self._measuring():
            return
        output = getattr(node, "workeroutput", None) or {}
        if error is not None or "cov_worker_node_id" not in output:
            why = f"it went down: {error}" if error is not None else "it finished without its coverage data"
            self.lost.append((str(getattr(getattr(node, "gateway", None), "id", node)), why))

    def messages(self) -> list[str]:
        return [
            f"{LEAD}: xdist worker {wid} returned no coverage data ({why}); the lines only its tests ran are missing "
            "from this run's coverage, so the run fails here rather than as a false fall at the coverage ratchet "
            "(card H-63)"
            for wid, why in self.lost
        ]

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        msgs = self.messages()
        if not msgs:
            return
        tr = self.config.pluginmanager.get_plugin("terminalreporter")
        for msg in msgs:
            if tr is not None:
                tr.write_line(msg, red=True)  # write_line is not silenced by -q
            print(msg, file=sys.stderr)
        if session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def register(config: pytest.Config) -> None:
    """On the controller of a run with coverage (tests/conftest.py): refuse to be a nested run with coverage in the
    folder of a run that measures coverage already, then watch the workers."""
    if hasattr(config, "workerinput") or not config.pluginmanager.has_plugin("_cov"):
        return
    if getattr(config.option, "no_cov", False):
        return
    here = str(Path.cwd().resolve())
    if os.environ.get(RUN_DIR_ENV) == here:
        raise pytest.UsageError(
            f"{LEAD}: this pytest measures coverage in {here}, the folder of the pytest run that started it; at its "
            "end it would combine and delete the coverage files the outer run's workers saved there (card H-63). "
            "Start it without the outer run's PYTEST_ADDOPTS (or with --no-cov, or in another folder)"
        )
    os.environ[RUN_DIR_ENV] = here  # inherited by the xdist workers and by every process a test starts
    config.pluginmanager.register(WorkerWatch(config), "tb-coverage-workers")


@dataclass(frozen=True)
class ShardData:
    shard: int
    files: int
    lines: int


def measured(db: Path) -> tuple[int, int]:
    """(files, lines) measured in one coverage data file."""
    from coverage import CoverageData

    data = CoverageData(str(db))
    data.read()
    files = data.measured_files()
    return len(files), sum(len(data.lines(f) or ()) for f in files)


def shard_count(root: Path) -> tuple[int | None, list[str]]:
    """How many shards the run had, from the shards' own records (``unit-shard-*/shard.json``)."""
    counts: set[int] = set()
    problems: list[str] = []
    for rec in sorted(root.glob("unit-shard-*/shard.json")):
        try:
            counts.add(int(json.loads(rec.read_text(encoding="utf-8"))["count"]))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            problems.append(f"{rec}: not a shard record ({exc})")
    if not counts:
        problems.append(f"no shard record under {root}: the number of shards is unknown")
        return None, problems
    if len(counts) > 1:
        problems.append(f"the shard records disagree on the number of shards: {sorted(counts)}")
        return None, problems
    return counts.pop(), problems


def check(root: Path) -> tuple[list[ShardData], list[str]]:
    count, problems = shard_count(root)
    found: list[ShardData] = []
    if count is None:
        return found, problems
    for i in range(1, count + 1):
        db = root / f"unit-shard-{i}" / "coverage.db"
        if not db.is_file():
            problems.append(f"shard {i}/{count}: no coverage data ({db} is missing)")
            continue
        try:
            files, lines = measured(db)
        except Exception as exc:  # coverage raises its own DataError, sqlite its own: all mean unreadable
            problems.append(f"shard {i}/{count}: {db} cannot be read as coverage data ({exc})")
            continue
        if lines == 0:
            problems.append(f"shard {i}/{count}: {db} holds no measured line")
            continue
        found.append(ShardData(i, files, lines))
    return found, problems


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.coverage_shards", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="every shard's coverage data is present and holds measured lines")
    c.add_argument("root", type=Path, help="the folder holding unit-shard-<i>/ (shard.json, coverage.db)")
    a = ap.parse_args(argv)
    found, problems = check(a.root)
    for s in found:
        print(f"{LEAD}: shard {s.shard}: {s.lines} lines in {s.files} files")
    for p in problems:
        print(f"{LEAD}: {p}", file=sys.stderr)
    if problems:
        print(f"{LEAD}: the coverage ratchet does not judge a combined coverage without a shard", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
