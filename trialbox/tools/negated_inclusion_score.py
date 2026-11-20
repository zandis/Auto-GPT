"""negated_inclusion_score: score a file of inclusion lines against the negated-inclusion rule (card 10A-1c).

    python -m tools.negated_inclusion_score lines.tsv            # misses and unnecessary holds, by class and language
    python -m tools.negated_inclusion_score lines.tsv --rows     # also every miss and every unnecessary hold

Each line is compiled as the compiler compiles an inclusion: ``postprocess`` with the coded concept as a structured
inclusion whose logic asks its presence ("any of <concept>"), with the coded concept and the line's other concepts as
the extractor's candidates, and an empty terminology. No model is called. A line is **held** when it goes to a person
(``negated_inclusion_presence``).

* A **miss** is a line labelled ``held`` (its coded concept is negated, excepted or doubtful) that runs.
* An **unnecessary hold** is a line labelled ``runs`` (its coded concept is present) that is held.

The input is either a tab-separated file with a header row, or a JSON file shaped like
``tests/fixtures/negated_inclusion/*.json`` (``{"rows": [...]}``). Columns (JSON keys):

* ``text``: the criterion line, as written;
* ``concept``: the coded concept's name;
* ``expect``: ``held`` or ``runs``, the right reading;
* ``lang`` (optional): any label, for the table (``en``, ``ja``, ``zh``);
* ``synonyms`` and ``others`` (optional): the coded concept's other names, and the line's other concept candidates.
  In a TSV, separate several with ``;``;
* ``domain`` (optional): ``condition`` (the default), ``procedure``, ``medication``, ``observation`` …;
* ``hold_class`` (optional): any label, for the table.

The exit status is 1 when any line is missed, else 0. Synthetic or public lines only.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

FLAG = "negated_inclusion_presence"


def read_rows(path: Path) -> list[dict[str, Any]]:
    """The labelled lines in ``path`` (JSON with ``rows``, or a TSV with a header)."""
    if path.suffix.lower() == ".json":
        rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["rows"]
        return rows
    with path.open(encoding="utf-8", newline="") as fh:
        out: list[dict[str, Any]] = []
        for raw in csv.DictReader(fh, delimiter="\t"):
            row: dict[str, Any] = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
            for key in ("synonyms", "others"):
                row[key] = [x.strip() for x in str(row.get(key) or "").split(";") if x.strip()]
            out.append(row)
        return out


def score(rows: list[dict[str, Any]]) -> list[bool]:
    """Whether each row is held, compiled as one ruleset of structured inclusions."""
    from criteria_compiler.ir_extract import postprocess as pp
    from criteria_compiler.terminology.mapper import Terminology
    from tb_contracts import LlmExtractOutput

    crits = []
    for r in rows:
        domain = r.get("domain") or "condition"
        cands = [{"domain": domain, "name": r["concept"], "synonyms": list(r.get("synonyms") or [])}]
        cands += [{"domain": domain, "name": x, "synonyms": []} for x in r.get("others") or []]
        crits.append(
            {
                "kind": "inclusion",
                "class": "structured",
                "text": r["text"],
                "logic": {"domain": domain, "concept": r["concept"], "quantifier": "any"},
                "concept_candidates": cands,
            }
        )
    out = pp.postprocess("SCORE", LlmExtractOutput.model_validate({"criteria": crits}), Terminology(), "1.0.0")
    return [FLAG in (x.flags or []) for x in out.criteria]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", type=Path, help="a .tsv with a header row, or a .json with rows")
    ap.add_argument("--rows", action="store_true", help="print every miss and every unnecessary hold")
    args = ap.parse_args(argv)
    rows = read_rows(args.file)
    bad = [i for i, r in enumerate(rows) if r.get("expect") not in ("held", "runs") or not r.get("text")]
    if bad:
        print(f"rows {bad[:10]}: each row needs text, concept and expect (held or runs)", file=sys.stderr)
        return 2
    held = score(rows)
    missed, over = Counter[tuple[str, str]](), Counter[tuple[str, str]]()
    total: Counter[tuple[str, str]] = Counter()
    for r, h in zip(rows, held, strict=True):
        key = (str(r.get("hold_class") or "-"), str(r.get("lang") or "-"))
        total[(r["expect"], key[1])] += 1
        if r["expect"] == "held" and not h:
            missed[key] += 1
            if args.rows:
                print(f"MISS  [{key[1]}] {r['text']}  | coded: {r['concept']}")
        elif r["expect"] == "runs" and h:
            over[key] += 1
            if args.rows:
                print(f"HOLD  [{key[1]}] {r['text']}  | coded: {r['concept']}")
    n_held = sum(v for (e, _), v in total.items() if e == "held")
    n_runs = sum(v for (e, _), v in total.items() if e == "runs")
    print(f"{args.file.name}: {len(rows)} lines")
    print(f"missed (negated line that runs): {sum(missed.values())} / {n_held}")
    print(f"held unnecessarily (present line held): {sum(over.values())} / {n_runs}")
    for name, counts in (("missed", missed), ("held unnecessarily", over)):
        for (cls, lang), v in sorted(counts.items()):
            print(f"  {name:20s} {cls:22s} {lang:4s} {v}")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.path[:0] = [p for p in ("libs", "services") if p not in sys.path]
    raise SystemExit(main())
