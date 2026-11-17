"""How many drafted concepts the terminology resolves without the model (TERM-2, D-1113; lane E's TERM-1 measure).

    python -m tools.terminology_coverage <raw-traces.json> [--installed DIR] [--synonyms] [--json]

Reads every ``concept_candidates`` entry of the ``extract_criteria`` calls in a launch's ``raw-traces.json`` (launch
P1b's ``sigir.tgz``: public ClinicalTrials.gov protocols), leaves out the ``demographic`` ones, and maps each with
``Terminology.map`` (no model, no synonym dictionary) against the shipped tables and, with ``--installed``, the code
systems loaded into that folder by ``tools.terminology_install``. ``--synonyms`` also passes the model's synonyms of
each candidate (off by default, as lane E measured). The file is data only: it is parsed as JSON and never run.
Prints the concepts and how many resolved, by domain, and the total.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from criteria_compiler.terminology.mapper import Terminology  # noqa: E402

ORDER = ("condition", "observation", "medication", "procedure", "encounter", "claim")


def candidates(traces: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Each concept candidate the ``extract_criteria`` calls drafted, in order (an output that is not JSON: none)."""
    for call in traces.get("traces") or []:
        if (call.get("attributes") or {}).get("tb.role") != "extract_criteria":
            continue
        try:
            out = json.loads(call.get("output") or "")
        except (TypeError, ValueError):
            continue
        for crit in out.get("criteria") or [] if isinstance(out, dict) else []:
            for cand in crit.get("concept_candidates") or []:
                if isinstance(cand, dict) and cand.get("name"):
                    yield cand


def measure(traces: dict[str, Any], term: Terminology, synonyms: bool = False) -> dict[str, Any]:
    """``{"calls", "candidates", "by_domain": {domain: [concepts, resolved]}, "methods": {method: n}, "unmapped":
    {domain: {name: n}}}``; demographic candidates are counted in ``candidates`` only."""
    calls = sum(
        1 for c in traces.get("traces") or [] if (c.get("attributes") or {}).get("tb.role") == "extract_criteria"
    )
    total = 0
    by: dict[str, list[int]] = {}
    methods: Counter[str] = Counter()
    unmapped: dict[str, Counter[str]] = {}
    for cand in candidates(traces):
        total += 1
        domain = str(cand.get("domain") or "")
        if domain == "demographic":
            continue
        syn = [str(s) for s in cand.get("synonyms") or []] if synonyms else None
        r = term.map(domain, str(cand["name"]), syn)
        row = by.setdefault(domain, [0, 0])
        row[0] += 1
        if r.concepts:
            row[1] += 1
            methods[r.method] += 1
        else:
            unmapped.setdefault(domain, Counter())[str(cand["name"]).strip().lower()] += 1
    return {"calls": calls, "candidates": total, "by_domain": by, "methods": dict(methods),
            "unmapped": {d: dict(c.most_common()) for d, c in unmapped.items()}}  # fmt: skip


def table(result: dict[str, Any]) -> str:
    by = result["by_domain"]
    names = [d for d in ORDER if d in by] + sorted(set(by) - set(ORDER))
    lines = ["| Domain | Concepts | Resolved |", "|---|---|---|"]
    for d in names:
        lines.append(f"| {d} | {by[d][0]} | {by[d][1]} |")
    n, k = sum(v[0] for v in by.values()), sum(v[1] for v in by.values())
    lines.append(f"| **all** | **{n:,}** | **{k} ({100 * k / (n or 1):.1f} %)** |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("traces", type=Path)
    ap.add_argument("--installed", type=Path, default=None, help="a TB_TERMINOLOGY_DIR (default: an empty one)")
    ap.add_argument("--synonyms", action="store_true", help="also pass each candidate's model synonyms")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    traces = json.loads(args.traces.read_text(encoding="utf-8"))
    where = args.installed or Path("/nonexistent/terminology-none")
    term = Terminology(installed=where)
    if term.installed_problems:
        print("refused: " + "; ".join(term.installed_problems), file=sys.stderr)
    result = measure(traces, term, args.synonyms)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    print(f"{result['calls']} extract_criteria calls, {result['candidates']:,} candidates")
    print(table(result))
    print("methods: " + ", ".join(f"{m} {n}" for m, n in sorted(result["methods"].items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
