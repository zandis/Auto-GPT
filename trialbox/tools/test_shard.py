"""test_shard: the unit suite in N parallel shards (T-747, D-475).

    pytest --shard 2/6 ...                              # shard 2 of 6 (tests/conftest.py; `make test SHARD=2/6`)
    pytest --shard 2/6 --shard-record shard-2.json ...  # also record the full and the shard's collection
    python -m tools.test_shard check shard-*.json       # every collected test in exactly one shard, all N present
    python -m tools.test_shard files 2/6                # the test files of shard 2 of 6

A test FILE belongs to one shard: ``sha256(<its path from trialbox/>) mod N``. Whole files stay together, so module-
and session-scoped fixtures are built once per shard as before; the shard of a file never moves when another file is
added or removed (only a change of N moves files). The record a shard writes holds pytest's own collection before the
shard is taken (after ``-m``/``-k``) and the node ids the shard kept; ``check`` refuses a run where the shards'
collections differ, a shard is missing or doubled, a test is in no shard or in two.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Shard:
    index: int  # 1-based
    count: int

    def __str__(self) -> str:
        return f"{self.index}/{self.count}"


def parse(text: str) -> Shard:
    """``"i/N"`` with 1 <= i <= N."""
    head, sep, tail = text.strip().partition("/")
    if not sep or not head.isdigit() or not tail.isdigit():
        raise ValueError(f"a shard is i/N, e.g. 2/6, not {text!r}")
    shard = Shard(int(head), int(tail))
    if not 1 <= shard.index <= shard.count:
        raise ValueError(f"shard {text!r}: i must be between 1 and N")
    return shard


def file_of(nodeid: str) -> str:
    """The test file of a node id, as pytest writes it (relative to trialbox/, forward slashes)."""
    return nodeid.split("::", 1)[0]


def shard_of(path: str, count: int) -> int:
    """The 1-based shard of a test file. Stable: depends on the path and N only."""
    if count < 1:
        raise ValueError("N must be at least 1")
    digest = hashlib.sha256(path.replace("\\", "/").encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % count + 1


def keep(nodeids: Iterable[str], shard: Shard) -> list[str]:
    return [n for n in nodeids if shard_of(file_of(n), shard.count) == shard.index]


@dataclass(frozen=True)
class Record:
    """What one shard collected (pytest's collection before the shard was taken) and what it kept."""

    shard: int
    count: int
    collected: tuple[str, ...]
    kept: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> Record:
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(int(d["shard"]), int(d["count"]), tuple(map(str, d["collected"])), tuple(map(str, d["kept"])))

    def write(self, path: Path) -> None:
        data = {"shard": self.shard, "count": self.count, "collected": self.collected, "kept": self.kept}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")


def check(records: Sequence[Record]) -> list[str]:
    """The problems of a set of shard records; empty when every collected test ran in exactly one shard."""
    if not records:
        return ["no shard record"]
    counts = sorted({r.count for r in records})
    if len(counts) != 1:
        return [f"the shards disagree on N: {counts}"]
    count = counts[0]
    problems: list[str] = []
    seen = sorted(r.shard for r in records)
    if seen != list(range(1, count + 1)):
        problems.append(f"shards present {seen}, expected 1..{count}")
    full = set(records[0].collected)
    if len(full) != len(records[0].collected):
        problems.append(f"shard {records[0].shard} collected a node id twice")
    for r in records[1:]:
        if set(r.collected) != full:
            diff = sorted(full.symmetric_difference(r.collected))
            problems.append(f"shard {r.shard} collected another suite than shard {records[0].shard}: {diff[:5]}")
    owner: dict[str, int] = {}
    for r in records:
        for n in r.kept:
            if n in owner:
                problems.append(f"{n} ran in shards {owner[n]} and {r.shard}")
            owner[n] = r.shard
    missing = sorted(full - owner.keys())
    extra = sorted(owner.keys() - full)
    if missing:
        problems.append(f"{len(missing)} collected test(s) ran in no shard, e.g. {missing[:5]}")
    if extra:
        problems.append(f"{len(extra)} test(s) ran outside the collection, e.g. {extra[:5]}")
    return problems


class ShardPlugin:
    """The pytest side (registered by tests/conftest.py for ``--shard``): runs after every other selection hook, keeps
    this shard's files, reports the rest as deselected and, on the first xdist worker (or
    without xdist), writes the record. Every xdist worker collects the same suite, so every worker keeps the same
    tests."""

    def __init__(self, shard: Shard, record_path: str | None) -> None:
        self.shard, self.record_path = shard, record_path

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config: pytest.Config, items: list[pytest.Item]) -> None:
        collected = [i.nodeid for i in items]
        mine = set(keep(collected, self.shard))
        kept = [i for i in items if i.nodeid in mine]
        dropped = [i for i in items if i.nodeid not in mine]
        items[:] = kept
        if dropped:
            config.hook.pytest_deselected(items=dropped)
        worker = getattr(config, "workerinput", {}).get("workerid")
        if self.record_path and worker in (None, "gw0"):
            rec = Record(self.shard.index, self.shard.count, tuple(collected), tuple(i.nodeid for i in kept))
            rec.write(Path(self.record_path))

    def pytest_report_header(self) -> str:
        return f"shard {self.shard} (T-747: test files by a hash of their path)"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.test_shard", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="every collected test in exactly one shard")
    c.add_argument("records", nargs="+", type=Path)
    f = sub.add_parser("files", help="the test files of one shard")
    f.add_argument("shard")
    f.add_argument("--tests", type=Path, default=ROOT / "tests")
    a = ap.parse_args(argv)
    if a.cmd == "files":
        shard = parse(a.shard)
        for p in sorted(a.tests.rglob("test_*.py")):
            rel = p.relative_to(ROOT).as_posix()
            if shard_of(rel, shard.count) == shard.index:
                print(rel)
        return 0
    recs = [Record.load(p) for p in a.records]
    problems = check(recs)
    for p in problems:
        print(f"test_shard: {p}", file=sys.stderr)
    if problems:
        return 1
    sizes = ", ".join(f"{r.shard}: {len(r.kept)}" for r in sorted(recs, key=lambda r: r.shard))
    print(f"test_shard: {len(recs[0].collected)} tests, each in exactly one of {recs[0].count} shards ({sizes})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
