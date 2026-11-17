"""How many drafted concepts the terminology resolves without the model (TERM-2, D-1113; lane E's TERM-1 measure).

    python -m tools.terminology_coverage <raw-traces.json> [--installed DIR] [--synonyms] [--json]
    python -m tools.terminology_coverage --concepts <concepts.csv> [--installed DIR] [--json]
    python -m tools.terminology_coverage <raw-traces.json> --write-concepts <concepts.csv>

Reads every ``concept_candidates`` entry of the ``extract_criteria`` calls in a launch's ``raw-traces.json`` (launch
P1b's ``sigir.tgz``: public ClinicalTrials.gov protocols), leaves out the ``demographic`` ones, and maps each with
``Terminology.map`` (no model, no synonym dictionary) against the shipped tables and, with ``--installed``, the code
systems loaded into that folder by ``tools.terminology_install``. ``--synonyms`` also passes the model's synonyms of
each candidate (off by default, as lane E measured). The file is data only: it is parsed as JSON and never run.
Prints the concepts and how many resolved, by domain, and the total.

H-17 (D-1128): the traces cannot be committed, so ``--write-concepts`` derives their concepts in a small committable
form (``domain``, ``name`` as drafted, ``count``; the demographic ones left out; no model synonyms) and
``--concepts`` measures from it, the same figures without the archive (CI). The JSON output also counts, by domain,
the resolved concepts whose answer is for review (``for_review``).
"""

from __future__ import annotations

import argparse
import csv
import io
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
    {domain: {name: n}}}``. ``candidates`` counts every drafted candidate, the demographic ones included (P1b: 1,533);
    the concepts measured, by domain, leave those out (P1b: 1,273)."""
    calls = sum(
        1 for c in traces.get("traces") or [] if (c.get("attributes") or {}).get("tb.role") == "extract_criteria"
    )
    cands = list(candidates(traces))
    result = _count(((c, 1) for c in cands), term, synonyms)
    return {"calls": calls, "candidates": len(cands), **result}


def _count(weighted: Iterator[tuple[dict[str, Any], int]], term: Terminology, synonyms: bool) -> dict[str, Any]:
    """The counts of :func:`measure` over candidates each counted ``n`` times (one map call per distinct one)."""
    by: dict[str, list[int]] = {}
    methods: Counter[str] = Counter()
    review: Counter[str] = Counter()
    unmapped: dict[str, Counter[str]] = {}
    for cand, n in weighted:
        domain = str(cand.get("domain") or "")
        if domain == "demographic":
            continue
        syn = [str(s) for s in cand.get("synonyms") or []] if synonyms else None
        r = term.map(domain, str(cand["name"]), syn)
        row = by.setdefault(domain, [0, 0])
        row[0] += n
        if r.concepts:
            row[1] += n
            methods[r.method] += n
            review[domain] += n if r.needs_review else 0
        else:
            unmapped.setdefault(domain, Counter())[str(cand["name"]).strip().lower()] += n
    return {"by_domain": by, "methods": dict(methods), "for_review": dict(review),
            "unmapped": {d: dict(c.most_common()) for d, c in unmapped.items()}}  # fmt: skip


CONCEPT_COLUMNS = ("domain", "name", "count")


def concept_rows(traces: dict[str, Any]) -> list[dict[str, str]]:
    """The launch's drafted concepts, distinct by domain and name as drafted, with how often each was drafted
    (demographic ones left out), sorted: the committable form ``--concepts`` reads (H-17, D-1128)."""
    counts: Counter[tuple[str, str]] = Counter()
    for cand in candidates(traces):
        domain = str(cand.get("domain") or "")
        if domain != "demographic":
            counts[(domain, str(cand["name"]))] += 1
    return [{"domain": d, "name": n, "count": str(k)} for (d, n), k in sorted(counts.items())]


def write_concepts(rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CONCEPT_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def measure_concepts(text: str, term: Terminology) -> dict[str, Any]:
    """:func:`measure`'s counts from the committable concept list (``domain,name,count``): the same figures as from
    the traces, without the model synonyms."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or set(CONCEPT_COLUMNS) - set(rows[0]):
        raise ValueError(f"a concept list has the columns {', '.join(CONCEPT_COLUMNS)}")
    weighted = (({"domain": r["domain"], "name": r["name"]}, int(r["count"])) for r in rows)
    result = _count(weighted, term, False)
    # H-17 review: the list holds no demographic candidates, so here ``candidates`` is the concepts measured (1,273),
    # not :func:`measure`'s count of every candidate (1,533)
    return {"calls": None, "candidates": sum(v[0] for v in result["by_domain"].values()), **result}


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
    ap.add_argument("traces", type=Path, nargs="?", default=None)
    ap.add_argument("--concepts", type=Path, default=None, help="a concept list (domain,name,count) instead")
    ap.add_argument("--write-concepts", type=Path, default=None, help="write the traces' concept list here")
    ap.add_argument("--installed", type=Path, default=None, help="a TB_TERMINOLOGY_DIR (default: an empty one)")
    ap.add_argument("--synonyms", action="store_true", help="also pass each candidate's model synonyms")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if (args.traces is None) == (args.concepts is None):
        ap.error("give either a raw-traces.json or --concepts")
    traces = json.loads(args.traces.read_text(encoding="utf-8")) if args.traces else {}
    if args.write_concepts:
        if not args.traces:
            ap.error("--write-concepts derives the list from a raw-traces.json")
        rows = concept_rows(traces)
        args.write_concepts.write_text(write_concepts(rows), encoding="utf-8")
        print(f"{len(rows)} distinct concepts, {sum(int(r['count']) for r in rows):,} drafted, "
              f"written to {args.write_concepts}")  # fmt: skip
        return 0
    where = args.installed or Path("/nonexistent/terminology-none")
    term = Terminology(installed=where)
    if term.installed_problems:
        print("refused: " + "; ".join(term.installed_problems), file=sys.stderr)
    if args.concepts:
        result = measure_concepts(args.concepts.read_text(encoding="utf-8"), term)
    else:
        result = measure(traces, term, args.synonyms)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    if result["calls"] is not None:
        print(f"{result['calls']} extract_criteria calls, {result['candidates']:,} candidates (demographic ones "
              "included; the table counts the others)")  # fmt: skip
    else:
        print(f"{result['candidates']:,} concepts (no demographic ones) from {args.concepts.name}")
    print(table(result))
    print("methods: " + ", ".join(f"{m} {n}" for m, n in sorted(result["methods"].items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
