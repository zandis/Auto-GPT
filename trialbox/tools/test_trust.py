"""test_trust: the tables of a test-trust page come from its JSON files, whole (card V-4, plan 8 V19).

    python -m tools.test_trust --check   # exit 1 when a table of the page differs from its JSON
    python -m tools.test_trust --write   # rewrite the tables of the page from the JSON

The page ``docs/plan/measurements/test-trust-2026-11-17.md`` holds three generated tables, each between a begin and
an end marker (``<!-- test-trust:begin NAME -->`` and ``<!-- test-trust:end NAME -->``):

* ``mutation``: per safety-core file, the results of ``tools/mutation.py`` in ``mutation.json``, scored as the tool
  scores them (``tools.mutation.score``);
* ``coverage``: per safety-core file, line and branch coverage in ``coverage.json`` against the targets;
* ``findings``: the rows of ``findings.json``.

A table is compared as a whole: one changed count in the page or in the JSON fails the check.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.mutation import Result, score

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "plan" / "measurements" / "test-trust-2026-11-17.md"
NAMES = ("mutation", "coverage", "findings")
_BLOCK = re.compile(r"(<!-- test-trust:begin (\w+) -->\n)(.*?)(<!-- test-trust:end \2 -->)", re.S)


def _folder(page: Path) -> Path:
    return page.with_suffix("")


def _load(page: Path, name: str) -> Any:
    return json.loads((_folder(page) / f"{name}.json").read_text(encoding="utf-8"))


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.1f} %"


def mutation_table(data: dict[str, Any]) -> str:
    """One row per mutated file: the mutants the tool makes, then the results of the runs in ``runs``."""
    by_file: dict[str, list[Result]] = {}
    for run in data["runs"].values():
        for r in run["results"]:
            by_file.setdefault(r["mutant"].split(":", 1)[0], []).append(Result(**r))
    lines = [
        "| File | Made | Run here | Killed | Timeout | Survived | No coverage | Error | Accepted | Not run | Score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    every: list[Result] = []
    for file in sorted(by_file):
        rs = by_file[file]
        every += rs
        lines.append(_mutation_row(f"`{file}`", data["made"].get(file, 0), rs))
    lines.append(_mutation_row("**all run here**", sum(data["made"].get(f, 0) for f in by_file), every))
    return "\n".join(lines) + "\n"


def _mutation_row(name: str, made: int, rs: list[Result]) -> str:
    s, c = score(rs)
    cells = [made, len(rs), c.get("killed", 0), c.get("timeout", 0), c.get("survived", 0), c.get("no-coverage", 0)]
    cells += [c.get("error", 0), c.get("accepted", 0), c.get("not-run", 0)]
    return f"| {name} | " + " | ".join(str(x) for x in cells) + f" | {s:.1f} % |"


def coverage_table(data: dict[str, Any]) -> str:
    lt, bt = data["line_target"], data["branch_target"]
    lines = [
        "| File | Line (nightly) | Branch (nightly) | Branch arcs missed | Line (target tests) | Branch (target tests) "
        "| Baseline line | Baseline branch | Against target |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in data["rows"]:
        ci, loc, base = r["ci_nightly"] or {}, r["local_target_tests"] or {}, r["baseline"] or {}
        verdict = "met" if ci and ci["line"] >= lt and ci["branch"] >= bt else "UNDER"
        lines.append(
            f"| `{r['file']}` | {_pct(ci.get('line'))} | {_pct(ci.get('branch'))} | {len(ci.get('missing_branches', []))} "
            f"| {_pct(loc.get('line'))} | {_pct(loc.get('branch'))} | {_pct(base.get('line'))} | "
            f"{_pct(base.get('branch'))} | {verdict} |"
        )
    return "\n".join(lines) + "\n"


def findings_table(data: dict[str, Any]) -> str:
    lines = ["| Id | Severity | Lane | Basis | Place | Claim |", "| --- | --- | --- | --- | --- | --- |"]
    for f in data["findings"]:
        claim = f["claim"].replace("|", "\\|")
        lines.append(f"| {f['id']} | {f['severity']} | {f['lane']} | {f['basis']} | `{f['place']}` | {claim} |")
    return "\n".join(lines) + "\n"


RENDER = {"mutation": mutation_table, "coverage": coverage_table, "findings": findings_table}


def render(page: Path) -> dict[str, str]:
    return {name: RENDER[name](_load(page, name)) for name in NAMES}


def check(page: Path = PAGE) -> list[str]:
    """The names of the tables that differ from their JSON (a missing block counts as differing)."""
    text = page.read_text(encoding="utf-8")
    found = {m.group(2): m.group(3) for m in _BLOCK.finditer(text)}
    want = render(page)
    return [name for name in NAMES if found.get(name) != want[name]]


def write(page: Path = PAGE) -> None:
    want = render(page)
    text = page.read_text(encoding="utf-8")
    page.write_text(_BLOCK.sub(lambda m: m.group(1) + want.get(m.group(2), m.group(3)) + m.group(4), text), "utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.test_trust", description=__doc__.split("\n\n")[0])
    ap.add_argument("--page", type=Path, default=PAGE)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.write:
        write(args.page)
        return 0
    bad = check(args.page)
    for name in bad:
        print(f"{args.page}: the table '{name}' differs from {name}.json (run python -m tools.test_trust --write)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
