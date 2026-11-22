"""Gate 5's planted mistakes (review 2026-11-22 §3.5 step 5, §5.3): the acceptance of the cross-path test itself.

Each mutation of ``tools/gate5_planted.json`` is applied, one at a time, to a scratch copy of ``trialbox/`` (never to
this tree), and the cross-path test (``tests/unit/test_gate5_cross_path.py``) is run on the copy. A mutation is
**caught** when the run has a finding the unmutated run does not have. The unmutated run may itself be red (an exit
not yet behind the gate), so the comparison is of every finding line in full (its invariant, road, person,
identifier, class, placement and the decoding it was found in), counted per case: new damage on a road that is
already red shows as a new or more frequent line, never as a case id alone.

    python -m tools.gate5_planted --work <scratch dir> [--only a,b] [-n 2] [-k <pytest -k>] [--out results.json]

Prints one line per mutation: ``<id> <what> -> red|green`` and, when red, the invariants and roads of its new
findings. Writes the whole result as JSON with ``--out``. Exit 0 when every mutation is caught, 1 otherwise. The
mutations are data (``gate5_planted.json``) so this module names no other module's file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/unit/test_gate5_cross_path.py"
MUTATIONS_FILE = Path(__file__).with_suffix(".json")
IGNORE = shutil.ignore_patterns(
    ".venv", ".cache", "node_modules", "__pycache__", ".pytest_cache", "*.pyc", ".mypy_cache", ".ruff_cache"
)


@dataclass(frozen=True)
class Mutation:
    id: str
    what: str
    edits: tuple[tuple[str, str, str], ...]  # (file, old text, new text); old must occur exactly once
    new_files: tuple[tuple[str, str], ...] = ()


def mutations() -> tuple[Mutation, ...]:
    rows = json.loads(MUTATIONS_FILE.read_text(encoding="utf-8"))["mutations"]
    return tuple(
        Mutation(
            r["id"],
            r["what"],
            tuple((a, b, c) for a, b, c in r["edits"]),
            tuple((a, b) for a, b in r.get("new_files", [])),
        )
        for r in rows
    )


_CASE = re.compile(r"^E\s+AssertionError: (\S+) / (\S+): \d+ findings")
_FINDING = re.compile(r"^E {9}([a-z-]+) road=(\S+) (.*)$")
_SITES = re.compile(r"^E\s+AssertionError: (\d+) exit sites with no road")
_FAILED = re.compile(r"^(FAILED|ERROR) (\S+)")


@dataclass
class Run:
    rc: int
    seconds: float
    failed: set[str] = field(default_factory=set)
    findings: Counter[tuple[str, str]] = field(default_factory=Counter)  # (case, finding line) -> how many


def parse(text: str) -> Run:
    run = Run(rc=0, seconds=0.0)
    case = ""
    for line in text.splitlines():
        if m := _CASE.match(line):
            case = f"{m[1]}-{m[2]}"
        elif (m := _FINDING.match(line)) and case:
            run.findings[(case, line[10:])] += 1
        elif m := _SITES.match(line):
            run.findings[("exit-sites", f"{m[1]} exit sites with no road")] += 1
        elif m := _FAILED.match(line):
            run.failed.add(m[2])
    return run


def copy_tree(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ROOT, dest, ignore=IGNORE, symlinks=True)


def apply(tree: Path, m: Mutation) -> None:
    for rel, old, new in m.edits:
        path = tree / rel
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise SystemExit(f"mutation {m.id}: the text to change occurs {text.count(old)} times in {rel}")
        path.write_text(text.replace(old, new), encoding="utf-8")
    for rel, body in m.new_files:
        (tree / rel).write_text(body, encoding="utf-8")


def restore(tree: Path, m: Mutation) -> None:
    for rel, _, _ in m.edits:
        shutil.copyfile(ROOT / rel, tree / rel)
    for rel, _ in m.new_files:
        (tree / rel).unlink(missing_ok=True)


def run_test(tree: Path, log: Path, workers: int, basetemp: Path, select: str = "") -> Run:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(tree / p) for p in ("libs", "services", "."))}
    # the copy, never this tree: an editable install would otherwise answer the imports
    probe = subprocess.run(
        [sys.executable, "-c", "import mail_gateway, tb_common; print(mail_gateway.__file__, tb_common.__file__)"],
        cwd=tree,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or probe.stdout.count(str(tree)) != 2:
        raise SystemExit(f"the copy's modules are not the ones imported: {probe.stdout.strip()} {probe.stderr[-300:]}")
    t0 = time.monotonic()
    with log.open("w", encoding="utf-8") as fh:
        rc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "-n",
                str(workers),
                "--basetemp",
                str(basetemp),
                TEST,
            ]
            + (["-k", select] if select else []),
            cwd=tree,
            env=env,
            check=False,
            stdout=fh,
            stderr=subprocess.STDOUT,
        ).returncode
    run = parse(log.read_text(encoding="utf-8", errors="replace"))
    run.rc, run.seconds = rc, round(time.monotonic() - t0, 1)
    return run


def describe(new: Counter[tuple[str, str]]) -> str:
    """The invariants that caught a mutation, with the roads and identifiers they caught it on."""
    caught: dict[str, set[str]] = {}
    for _case, line in new:
        inv, _, rest = line.partition(" ")
        road = re.search(r"road=(\S+)", rest)
        ident = re.search(r"id=(\S+)", rest)
        caught.setdefault(inv, set()).add(f"{road[1] if road else '?'}/{ident[1] if ident else '?'}")
    return "; ".join(f"{inv} on {', '.join(sorted(where))}" for inv, where in sorted(caught.items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--work", type=Path, required=True, help="a scratch folder (the copy and the logs go there)")
    ap.add_argument("--only", default="", help="mutation ids, comma separated (default: all)")
    ap.add_argument("-n", type=int, default=2, help="pytest workers (default 2)")
    ap.add_argument("--out", type=Path, help="write the results as JSON here")
    ap.add_argument("-k", dest="select", default="", help="a pytest -k expression")
    ap.add_argument("--from-logs", action="store_true", help="judge the logs an earlier run left in --work again")
    args = ap.parse_args(argv)
    only = {x for x in args.only.split(",") if x}
    todo = [m for m in mutations() if not only or m.id in only]
    tree = args.work / "trialbox"

    def logged(name: str) -> Run:
        return parse((args.work / name).read_text(encoding="utf-8", errors="replace"))

    if not args.from_logs:
        copy_tree(tree)
    base = (
        logged("baseline.log")
        if args.from_logs
        else run_test(tree, args.work / "baseline.log", args.n, args.work / "pytest-baseline", args.select)
    )
    print(
        f"baseline: rc {base.rc}, {len(base.failed)} failing cases, {base.findings.total()} findings, {base.seconds} s",
        flush=True,
    )
    results = []
    for m in todo:
        if args.from_logs:
            got = logged(f"mutation-{m.id}.log")
        else:
            apply(tree, m)
            try:
                got = run_test(
                    tree, args.work / f"mutation-{m.id}.log", args.n, args.work / f"pytest-{m.id}", args.select
                )
            finally:
                restore(tree, m)
        new = got.findings - base.findings
        newly_failed = got.failed - base.failed
        red = bool(new or newly_failed)
        line = f"{m.id} {m.what} -> {'red' if red else 'green'}"
        if new:
            line += f": {describe(new)}"
        if newly_failed and not new:
            line += f": newly failing {sorted(newly_failed)[:3]}"
        print(line, flush=True)
        results.append(
            {
                "id": m.id,
                "what": m.what,
                "red": red,
                "caught_by": describe(new),
                "new_findings": [[c, ln, n] for (c, ln), n in sorted(new.items())],
                "newly_failed": sorted(newly_failed),
                "seconds": got.seconds,
            }
        )
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "baseline": {
                        "failed": sorted(base.failed),
                        "findings": base.findings.total(),
                        "seconds": base.seconds,
                    },
                    "mutations": results,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return 0 if all(r["red"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
