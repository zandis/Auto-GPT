"""The traceability table from the tests (NEW-STD-3; STD-003, STD-011): which requirement each test proves, and the
result of the run that ran it.

    python -m tools.traceability --srs docs/plan/design/01-SRS.md --out DIR TRACE.jsonl [TRACE.jsonl ...]

A test says what it proves with ``@pytest.mark.req("<spec v4 id>", ...)``. A run with ``TB_TRACE_OUT=FILE`` (``make
test TRACE=FILE``; one file per CI shard) has ``tests/conftest.py`` write one JSON line per such test: its node id,
its result and the ids.
TB-DS-01 (``01-SRS.md``) Appendix D maps each spec v4 id to its TB-DS-01 requirement ("Design" and "Retired" rows
included). The tool writes, under ``--out``:

* ``traceability.csv``: one row per requirement and test: requirement, spec v4 id, test, result;
* ``traceability.md``: one row per requirement: its tests, how many passed, failed and were skipped, and a verdict
  (``passing``, ``FAILING``, ``skipped only``); then the spec v4 ids the tests cite that Appendix D does not map, and
  the mapped ids no test in the run cites;
* ``summary.md``: the counts, for the CI job's summary.

A report, never a gate (D-311): a requirement with no passing test is listed as such and the command still exits 0.
It exits 2 only when it cannot read its input.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

APPENDIX_HEAD = "| Spec-v4 IDs (markers) |"
_SPEC_ID = re.compile(r"([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\s*\(\d+\)")
_DS_ID = re.compile(r"\b(?:FR|NFR|CON|DR|IR|SR|UR|AM|HER|SC)(?:-[A-Z0-9]+)+[a-z]?\b")


@dataclass(frozen=True)
class Case:
    test: str  # the pytest node id
    result: str  # passed | failed | skipped
    reqs: tuple[str, ...]


def appendix(srs: Path) -> dict[str, list[str]]:
    """Appendix D of TB-DS-01: spec v4 id -> its TB-DS-01 ids ("Design" or "Retired" when it has no SRS row)."""
    lines = srs.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith(APPENDIX_HEAD))
    except StopIteration:
        raise ValueError(f"{srs}: no Appendix D table (a line starting {APPENDIX_HEAD!r})") from None
    out: dict[str, list[str]] = {}
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        target = _DS_ID.findall(cells[2])
        if not target:
            target = ["Retired"] if cells[2].startswith("Retired") else ["Design"]
        for spec in _SPEC_ID.findall(cells[0]):
            out.setdefault(spec, [])
            out[spec] += [t for t in target if t not in out[spec]]
    return out


def cases(paths: Iterable[Path]) -> list[Case]:
    """Every test of the run's trace files, with its result and the ids it declares."""
    out: list[Case] = []
    for path in paths:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                result, reqs = str(row["result"]), tuple(sorted(set(str(row["req"]).split())))
                test = str(row["test"])
            except (ValueError, KeyError, TypeError):
                raise ValueError(f"{path}:{n}: not a trace line") from None
            if result not in ("passed", "failed", "skipped"):
                raise ValueError(f"{path}:{n}: result {result!r}")
            out.append(Case(test, result, reqs))
    return out


def table(mapping: dict[str, list[str]], run: Sequence[Case]) -> tuple[list[list[str]], list[str], list[str]]:
    """(rows of requirement, spec id, test, result; spec ids not mapped; mapped spec ids no test cites)."""
    rows: list[list[str]] = []
    cited: set[str] = set()
    for c in run:
        for spec in c.reqs:
            cited.add(spec)
            for req in mapping.get(spec, ["Unmapped"]):
                rows.append([req, spec, c.test, c.result])
    rows.sort()
    unmapped = sorted(s for s in cited if s not in mapping)
    untested = sorted(s for s in mapping if s not in cited)
    return rows, unmapped, untested


def verdict(results: Sequence[str]) -> str:
    if "failed" in results:
        return "FAILING"
    if "passed" in results:
        return "passing"
    return "skipped only"


def write(out: Path, rows: list[list[str]], unmapped: list[str], untested: list[str], sources: int) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "traceability.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["requirement", "spec_v4_id", "test", "result"])
        w.writerows(rows)
    by_req: dict[str, list[list[str]]] = defaultdict(list)
    for r in rows:
        by_req[r[0]].append(r)
    md = ["# Traceability from the tests (NEW-STD-3)", "",
          f"From {sources} trace file(s). A report, never a gate (D-311).", "",
          "| Requirement | Spec v4 ids | Tests | Passed | Failed | Skipped | Verdict |",
          "| --- | --- | ---: | ---: | ---: | ---: | --- |"]  # fmt: skip
    counts = {"passing": 0, "FAILING": 0, "skipped only": 0}
    for req, rs in sorted(by_req.items()):
        res = [r[3] for r in rs]
        v = verdict(res)
        counts[v] += 1
        specs = ", ".join(sorted({r[1] for r in rs}))
        md.append(f"| {req} | {specs} | {len({r[2] for r in rs})} | {res.count('passed')} | {res.count('failed')} | "
                  f"{res.count('skipped')} | {v} |")  # fmt: skip
    md += ["", "## Spec v4 ids the tests cite that Appendix D does not map", ""]
    md += [f"- {s}" for s in unmapped] or ["(none)"]
    md += ["", "## Spec v4 ids Appendix D maps that no test in this run cites", ""]
    md += [f"- {s}" for s in untested] or ["(none)"]
    (out / "traceability.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    summary = {"requirements": len(by_req), **counts, "unmapped_ids": len(unmapped), "untested_ids": len(untested)}
    (out / "summary.md").write_text(
        "### Traceability from the tests (NEW-STD-3)\n\n"
        + "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in summary.items())
        + "\n\nThe table is the `traceability` artifact (traceability.md, traceability.csv).\n",
        encoding="utf-8",
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.traceability", description=__doc__.split("\n\n")[0])
    ap.add_argument("trace", type=Path, nargs="+", help="the run's trace files (one per shard)")
    ap.add_argument("--srs", type=Path, required=True, help="TB-DS-01 (docs/plan/design/01-SRS.md)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        mapping = appendix(a.srs)
        run = cases(a.trace)
    except (OSError, ValueError) as exc:
        print(f"traceability: {exc}", file=sys.stderr)
        return 2
    summary = write(a.out, *table(mapping, run), sources=len(a.trace))
    print("traceability: " + ", ".join(f"{k} {v}" for k, v in summary.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
