"""Parser backend comparison for site documents (DECISIONS D-02: Docling chosen over marker; the lite backend is the
CPU fallback). For every PDF/DOCX in a directory and every available backend (``lite`` always; ``docling`` when
installed — the production doc-parser image), reports sections, I/E items and tables found, the parse time, and —
when ``<document>.gold.json`` sits next to the file — **table-cell recall** and **I/E item recall** against the gold:

    {"inclusion": ["…", …], "exclusion": ["…", …], "tables": [[["cell", …], …], …]}

    python tools/parser_compare.py tests/fixtures/protocols [--json out.json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    sys.path.insert(0, str(ROOT / _p))


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s)).lower()


def recall(found: list[str], gold: list[str]) -> float | None:
    if not gold:
        return None
    have = {_norm(x) for x in found}
    return round(100.0 * sum(1 for g in gold if _norm(g) in have) / len(gold), 1)


def table_recall(tables: list[list[list[str]]], gold: list[list[list[str]]]) -> float | None:
    cells = [_norm(c) for t in gold for row in t for c in row if str(c).strip()]
    if not cells:
        return None
    have = {_norm(c) for t in tables for row in t for c in row}
    return round(100.0 * sum(1 for c in cells if c in have) / len(cells), 1)


def backends() -> list[str]:
    out = ["lite"]
    if importlib.util.find_spec("docling") is not None:
        out.append("docling")
    return out


def compare(directory: Path) -> list[dict[str, Any]]:
    from doc_parser.parser import parse

    rows = []
    for doc in sorted(p for p in directory.iterdir() if p.suffix.lower() in (".pdf", ".docx")):
        gold_path = doc.with_name(doc.name + ".gold.json")
        gold = json.loads(gold_path.read_text(encoding="utf-8")) if gold_path.exists() else {}
        for backend in backends():
            t0 = time.perf_counter()
            parsed = parse(doc.read_bytes(), doc.name, backend=backend)
            dt = time.perf_counter() - t0
            tables = [t.rows for t in parsed.tables or []]
            rows.append(
                {
                    "document": doc.name,
                    "backend": backend,
                    "language": parsed.language,
                    "seconds": round(dt, 2),
                    "sections": len(parsed.sections or []),
                    "inclusion": len(parsed.ie_block.inclusion),
                    "exclusion": len(parsed.ie_block.exclusion),
                    "tables": len(tables),
                    "ie_recall": recall(
                        [*parsed.ie_block.inclusion, *parsed.ie_block.exclusion],
                        [*gold.get("inclusion", []), *gold.get("exclusion", [])],
                    ),
                    "table_cell_recall": table_recall(tables, gold.get("tables", [])),
                }
            )
    return rows


def markdown(rows: list[dict[str, Any]]) -> str:
    head = "| document | backend | lang | s | sections | incl | excl | tables | I/E recall % | table-cell recall % |"
    out = [head, "|" + " --- |" * 10]
    for r in rows:
        ie = "—" if r["ie_recall"] is None else r["ie_recall"]
        cells = "—" if r["table_cell_recall"] is None else r["table_cell_recall"]
        out.append(
            f"| {r['document']} | {r['backend']} | {r['language']} | {r['seconds']} | {r['sections']} | "
            f"{r['inclusion']} | {r['exclusion']} | {r['tables']} | {ie} | {cells} |"
        )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    rows = compare(args.directory)
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    sys.stdout.write(markdown(rows))
    if "docling" not in backends():
        print("\n(docling not installed here: run in the production doc-parser image for the D-02 comparison)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
