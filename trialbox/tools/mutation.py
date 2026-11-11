"""mutation: mutation testing of the safety core, run nightly (T-651, ENG-029; TB-DR-04 §3.3).

    python -m tools.mutation                       # every target of tools/mutation.toml; exit 1 under the floor
    python -m tools.mutation --list                # print the mutants, run nothing
    python -m tools.mutation --target services/matching/pair.py --workers 4 --report dist/mutation.json

A mutant is one small change to one line of a safety-core file (a comparison flipped or moved by one, ``and`` for
``or``, a ``not`` dropped, ``True`` for ``False``, a number moved by one, a value returned as ``None``, ``break`` for
``continue``, ``+`` for ``-``). Each mutant is written into a private copy of the tree and the target's unit tests run
against it with ``-x``: a failing run kills the mutant, a green run means no test noticed the change. A mutant on a
line the target's tests never execute is counted as surviving without a run. The score is killed / (all - accepted),
where "accepted" are the equivalent mutants listed with a reason in the config (a change no test can see because the
behaviour is the same).

Why not a third-party tool: mutmut 3 only follows ``./``, ``src/`` or ``source/`` layouts and this tree imports from
``libs`` and ``services`` (pytest ``pythonpath``); the runner here is a few hundred lines with no new dependency.

The config (``tools/mutation.toml``) lists the safety-core files (also read by ``tools.coverage_ratchet``), the
mutation targets with their tests, the target score (``threshold``, 90 %), the ``floor`` under which the run fails
(a ratchet: raise it as tests are added, until it reaches the threshold) and the accepted mutants. A mutant id is
``<file>:<line>:<col>:<operator>``; it moves when lines are added above it, so an accepted mutant whose id no longer
exists is reported (never an error) and should be removed.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tools.pglocal import scratch_root

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "tools" / "mutation.toml"
NO_MUTATE = "pragma: no mutate"
# copied into each worker's tree as links, never copied (big, read-only for the tests)
LINKED = (".venv", ".cache")
IGNORED = shutil.ignore_patterns(".venv", ".cache", "__pycache__", ".git", "node_modules", "dist", ".mutation")

_COMPARE_SWAP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
}
_BINOP_SWAP: dict[type[ast.operator], type[ast.operator]] = {ast.Add: ast.Sub, ast.Sub: ast.Add}


@dataclass(frozen=True)
class Mutant:
    file: str  # relative to the root, with "/"
    line: int
    col: int
    operator: str
    index: int  # the position of the node in the walk order of the file (how the mutant is applied)

    @property
    def id(self) -> str:
        return f"{self.file}:{self.line}:{self.col}:{self.operator}"


@dataclass
class Target:
    file: str
    tests: list[str]


@dataclass
class Config:
    threshold: float
    floor: float
    targets: list[Target]
    accepted: dict[str, str] = field(default_factory=dict)  # mutant id -> why it is equivalent
    safety_core: list[str] = field(default_factory=list)


@dataclass
class Result:
    mutant: str
    status: str  # killed | survived | no-coverage | timeout | error | accepted | not-run (out of time; not scored)
    seconds: float = 0.0


def load_config(path: Path = CONFIG) -> Config:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    targets = [Target(file=t["file"], tests=list(t["tests"])) for t in data.get("target", [])]
    return Config(
        threshold=float(data.get("threshold", 90.0)),
        floor=float(data.get("floor", data.get("threshold", 90.0))),
        targets=targets,
        accepted={str(k): str(v) for k, v in data.get("accepted", {}).items()},
        safety_core=list(data.get("safety_core", {}).get("files", [])),
    )


# --- the operators -------------------------------------------------------------------------------------------------


def _skipped_lines(source: str) -> set[int]:
    return {n for n, line in enumerate(source.splitlines(), 1) if NO_MUTATE in line}


def _docstring_ids(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                out.add(id(body[0].value))
    return out


def _annotation_ids(tree: ast.AST) -> set[int]:
    """Nodes inside annotations: changing them changes no behaviour."""
    out: set[int] = set()
    roots: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign | ast.arg) and node.annotation is not None:
            roots.append(node.annotation)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is not None:
            roots.append(node.returns)
    for r in roots:
        out.update(id(n) for n in ast.walk(r))
    return out


def _operators(node: ast.AST) -> list[str]:
    """The mutations that apply to one node, by name."""
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE_SWAP:
        return [f"cmp:{type(node.ops[0]).__name__}->{_COMPARE_SWAP[type(node.ops[0])].__name__}"]
    if isinstance(node, ast.BoolOp):
        return ["bool:and->or" if isinstance(node.op, ast.And) else "bool:or->and"]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return ["not:drop"]
    if isinstance(node, ast.Constant):
        if node.value is True:
            return ["const:True->False"]
        if node.value is False:
            return ["const:False->True"]
        if type(node.value) is int:
            return ["const:+1"]
        return []
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOP_SWAP:
        return [f"binop:{type(node.op).__name__}->{_BINOP_SWAP[type(node.op)].__name__}"]
    if isinstance(node, ast.Return) and node.value is not None:
        if isinstance(node.value, ast.Constant) and node.value.value is None:
            return []
        return ["return:None"]
    if isinstance(node, ast.Continue):
        return ["flow:continue->break"]
    if isinstance(node, ast.Break):
        return ["flow:break->continue"]
    return []


def _walk(tree: ast.AST) -> list[ast.AST]:
    """Every node, in a fixed order (ast.walk is breadth first and stable for one source)."""
    return list(ast.walk(tree))


def enumerate_mutants(source: str, file: str) -> list[Mutant]:
    tree = ast.parse(source)
    skip_lines = _skipped_lines(source)
    skip_ids = _docstring_ids(tree) | _annotation_ids(tree)
    out: list[Mutant] = []
    for index, node in enumerate(_walk(tree)):
        if id(node) in skip_ids:
            continue
        line = getattr(node, "lineno", 0)
        if line in skip_lines:
            continue
        for op in _operators(node):
            out.append(Mutant(file=file, line=line, col=getattr(node, "col_offset", 0), operator=op, index=index))
    return out


class _Replace(ast.NodeTransformer):
    def __init__(self, target: ast.AST, new: ast.AST) -> None:
        self.target, self.new = target, new

    def visit(self, node: ast.AST) -> ast.AST:
        if node is self.target:
            return self.new
        result: ast.AST = super().visit(node)
        return result


def apply_mutant(source: str, mutant: Mutant) -> str:
    """The source with the one mutation applied (unparsed: comments are lost, behaviour is not)."""
    tree = ast.parse(source)
    node = _walk(tree)[mutant.index]
    op = mutant.operator
    new: ast.AST
    if op.startswith("cmp:"):
        assert isinstance(node, ast.Compare)
        new = copy.copy(node)
        new.ops = [_COMPARE_SWAP[type(node.ops[0])]()]
    elif op.startswith("bool:"):
        assert isinstance(node, ast.BoolOp)
        new = copy.copy(node)
        new.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif op == "not:drop":
        assert isinstance(node, ast.UnaryOp)
        new = node.operand
    elif op.startswith("const:"):
        assert isinstance(node, ast.Constant)
        assert isinstance(node.value, int)  # bool is an int too
        new = ast.Constant(value=(not node.value) if isinstance(node.value, bool) else node.value + 1)
    elif op.startswith("binop:"):
        assert isinstance(node, ast.BinOp)
        new = copy.copy(node)
        new.op = _BINOP_SWAP[type(node.op)]()
    elif op == "return:None":
        new = ast.Return(value=ast.Constant(value=None))
    elif op == "flow:continue->break":
        new = ast.Break()
    elif op == "flow:break->continue":
        new = ast.Continue()
    else:  # pragma: no cover - the operator names come from _operators
        raise ValueError(op)
    ast.copy_location(new, node)
    mutated = ast.fix_missing_locations(_Replace(node, new).visit(tree))
    return ast.unparse(mutated) + "\n"


# --- running -------------------------------------------------------------------------------------------------------


def _env(tree: Path) -> dict[str, str]:
    # a run under pytest-cov (the unit job) must not pass its coverage settings down: the runner measures on its own
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS" and not k.startswith(("COVERAGE_", "COV_"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # a pyc of the same second and size would hide a mutant
    env["PYTHONPATH"] = os.pathsep.join(str(tree / p) for p in (".", "libs", "services"))
    return env


def pytest_command(python: str, tests: Sequence[str], timeout: float) -> list[str]:
    return [
        python,
        "-m",
        "pytest",
        "-x",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
        "-n",
        "0",
        f"--timeout={int(timeout)}",
        *tests,
    ]


def make_worker_tree(root: Path, into: Path) -> Path:
    tree = into / "tree"
    shutil.copytree(root, tree, ignore=IGNORED, symlinks=True)
    for name in LINKED:
        if (root / name).exists():
            (tree / name).symlink_to((root / name).resolve())
    return tree


def covered_lines(tree: Path, python: str, target: Target, timeout: float) -> tuple[set[int], float, int]:
    """Run the target's tests once, unmutated, under coverage: (executed lines of the file, seconds, exit code)."""
    data = tree / ".mutation-coverage"
    cmd = [
        python,
        "-m",
        "coverage",
        "run",
        f"--data-file={data}",
        f"--include={target.file}",
        "-m",
        "pytest",
        *pytest_command(python, target.tests, timeout)[3:],
    ]
    start = time.monotonic()
    proc = subprocess.run(cmd, cwd=tree, env=_env(tree), capture_output=True, text=True, check=False)
    seconds = time.monotonic() - start
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout[-4000:] + proc.stderr[-2000:])
        return set(), seconds, proc.returncode
    script = (
        "import coverage, json, sys\n"
        "c = coverage.Coverage(data_file=sys.argv[1]); c.load()\n"
        "d = c.get_data(); f = [x for x in d.measured_files() if x.endswith(sys.argv[2])]\n"
        "print(json.dumps(sorted(d.lines(f[0]) or []) if f else []))\n"
    )
    out = subprocess.run(
        [python, "-c", script, str(data), target.file],
        cwd=tree,
        env=_env(tree),
        capture_output=True,
        text=True,
        check=True,
    )
    data.unlink(missing_ok=True)
    return set(json.loads(out.stdout or "[]")), seconds, 0


def run_mutant(tree: Path, python: str, mutant: Mutant, tests: Sequence[str], timeout: float) -> Result:
    path = tree / mutant.file
    original = path.read_text(encoding="utf-8")
    start = time.monotonic()
    try:
        path.write_text(apply_mutant(original, mutant), encoding="utf-8")
        try:
            proc = subprocess.run(
                pytest_command(python, tests, timeout),
                cwd=tree,
                env=_env(tree),
                capture_output=True,
                text=True,
                timeout=timeout + 60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return Result(mutant.id, "timeout", time.monotonic() - start)
    finally:
        path.write_text(original, encoding="utf-8")
    seconds = time.monotonic() - start
    if proc.returncode == 0:
        return Result(mutant.id, "survived", seconds)
    if proc.returncode in (1, 2):
        # 1: a test failed (a pytest-timeout expiry too); 2: collection stopped (the mutant broke an import)
        return Result(mutant.id, "killed", seconds)
    return Result(mutant.id, "error", seconds)  # 3 to 5: internal error, usage, nothing collected


def run(
    config: Config,
    *,
    root: Path = ROOT,
    workers: int = 2,
    python: str | None = None,
    only: Sequence[str] = (),
    log: bool = True,
    budget_s: float | None = None,
) -> tuple[list[Result], dict[str, object]]:
    python = python or sys.executable
    targets = [t for t in config.targets if not only or t.file in only]
    results: list[Result] = []
    meta: dict[str, object] = {"targets": {}}
    scratch = scratch_root()  # never a fixed folder under the shared /tmp
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tb-mutation-", dir=scratch) as tmp:
        trees = [make_worker_tree(root, Path(tmp) / f"w{i}") for i in range(max(1, workers))]
        jobs: queue.Queue[tuple[Mutant, list[str], float]] = queue.Queue()
        for target in targets:
            source = (root / target.file).read_text(encoding="utf-8")
            mutants = enumerate_mutants(source, target.file)
            lines, seconds, rc = covered_lines(trees[0], python, target, timeout=600)
            timeout = max(60.0, 3 * seconds + 30)
            meta["targets"][target.file] = {"mutants": len(mutants), "baseline_s": round(seconds, 1), "rc": rc}  # type: ignore[index]
            if rc != 0:
                results += [Result(m.id, "error") for m in mutants]
                continue
            for m in mutants:
                if m.id in config.accepted:
                    results.append(Result(m.id, "accepted"))
                elif m.line not in lines:
                    results.append(Result(m.id, "no-coverage"))
                else:
                    jobs.put((m, target.tests, timeout))
        lock = threading.Lock()
        total = jobs.qsize()
        deadline = time.monotonic() + budget_s if budget_s else None

        def work(tree: Path) -> None:
            while True:
                try:
                    m, tests, timeout = jobs.get_nowait()
                except queue.Empty:
                    return
                if deadline is not None and time.monotonic() > deadline:
                    r = Result(m.id, "not-run")  # the job's time is up: listed, left out of the score
                else:
                    r = run_mutant(tree, python, m, tests, timeout)
                with lock:
                    results.append(r)
                    if log:
                        done = sum(1 for x in results if x.seconds)
                        print(f"[{done}/{total}] {r.status:9} {r.mutant} ({r.seconds:.0f} s)", flush=True)

        threads = [threading.Thread(target=work, args=(t,)) for t in trees]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    files = {t.file for t in targets}
    seen = {r.mutant for r in results if r.status == "accepted"}
    meta["stale_accepted"] = sorted(m for m in config.accepted if m.split(":", 1)[0] in files and m not in seen)
    return results, meta


def score(results: Sequence[Result]) -> tuple[float, dict[str, int]]:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    scored = len(results) - counts.get("accepted", 0) - counts.get("not-run", 0)
    killed = counts.get("killed", 0) + counts.get("timeout", 0)
    return (100.0 * killed / scored if scored else 100.0), counts


def _row(name: str, n: int, c: dict[str, int], score_text: str) -> str:
    cells = [c.get("killed", 0) + c.get("timeout", 0)]
    cells += [c.get(k, 0) for k in ("survived", "no-coverage", "error", "accepted", "not-run")]
    return f"| {name} | {n} | " + " | ".join(str(x) for x in cells) + f" | {score_text} |"


def table(results: Sequence[Result], threshold: float, floor: float | None = None) -> str:
    by_file: dict[str, list[Result]] = {}
    for r in results:
        by_file.setdefault(r.mutant.split(":", 1)[0], []).append(r)
    lines = [
        "| File | Mutants | Killed | Survived | No coverage | Errors | Accepted | Not run | Score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for file, rs in sorted(by_file.items()):
        s, c = score(rs)
        lines.append(_row(f"`{file}`", len(rs), c, f"{s:.1f} %"))
    s, c = score(results)
    lines.append(_row("**all**", len(results), c, f"**{s:.1f} %**"))
    lines.append("")
    lines.append(f"Target {threshold:.1f} %: {'met' if s >= threshold else 'not met yet'}.")
    if floor is not None:
        lines.append(f"Floor {floor:.1f} % (the run fails under it): {'held' if s >= floor else 'FELL'}.")
    left = [r for r in results if r.status in ("survived", "no-coverage", "error")]
    if left:
        lines += ["", "Mutants left alive (add a test, or accept an equivalent one in tools/mutation.toml):", ""]
        lines += [f"* `{r.mutant}` ({r.status})" for r in sorted(left, key=lambda r: r.mutant)]
    return "\n".join(lines) + "\n"


def _iter_listed(config: Config, root: Path, only: Sequence[str]) -> Iterator[Mutant]:
    for t in config.targets:
        if not only or t.file in only:
            yield from enumerate_mutants((root / t.file).read_text(encoding="utf-8"), t.file)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.mutation", description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", type=Path, default=CONFIG)
    ap.add_argument("--target", action="append", default=[], help="only this file (repeatable)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--budget-minutes", type=float, help="start no mutant after this; the rest are listed as not run")
    ap.add_argument("--report", type=Path, help="write the results as JSON here")
    ap.add_argument("--list", action="store_true", help="print the mutants and run nothing")
    ap.add_argument("--merge", type=Path, nargs="+", help="score the JSON reports of several shards, run nothing")
    args = ap.parse_args(argv)
    config = load_config(args.config)
    if args.merge:
        return _report(config, *_merge(args.merge), args.report)
    if args.list:
        n = 0
        for m in _iter_listed(config, ROOT, args.target):
            print(m.id + ("  (accepted)" if m.id in config.accepted else ""))
            n += 1
        print(f"{n} mutants", file=sys.stderr)
        return 0
    budget = args.budget_minutes * 60 if args.budget_minutes else None
    results, meta = run(config, workers=args.workers, only=args.target, budget_s=budget)
    return _report(config, results, meta, args.report)


def _merge(paths: Sequence[Path]) -> tuple[list[Result], dict[str, object]]:
    results: list[Result] = []
    targets: dict[str, object] = {}
    stale: list[str] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        results += [Result(**r) for r in data["results"]]
        targets.update(data.get("meta", {}).get("targets", {}))
        stale += data.get("meta", {}).get("stale_accepted", [])
    return results, {"targets": targets, "stale_accepted": sorted(stale)}


def _report(config: Config, results: list[Result], meta: dict[str, object], path: Path | None) -> int:
    s, counts = score(results)
    report = table(results, config.threshold, config.floor)
    if meta["stale_accepted"]:
        report += "\nAccepted mutants that no longer exist (remove them from the config):\n\n"
        report += "".join(f"* `{m}`\n" for m in meta["stale_accepted"])  # type: ignore[attr-defined]
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Mutation score of the safety core\n\n" + report)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "score": round(s, 2),
                    "threshold": config.threshold,
                    "floor": config.floor,
                    "counts": counts,
                    "meta": meta,
                    "results": [asdict(r) for r in results],
                },
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0 if s >= config.floor else 1


if __name__ == "__main__":
    sys.exit(main())
