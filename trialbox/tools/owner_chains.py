"""Print every owner-chain step past its latest start with no start date (TB-PLAN-06 §3.3, card T-663).

    python -m tools.owner_chains                     # today's date; exit 0
    python -m tools.owner_chains --today 2026-11-21  # as of a date
    python -m tools.owner_chains --strict            # exit 1 when a step is late

It reads the "Chains" table of ``docs/plan/owner-chains.md``: a step whose "Latest start" is before today and whose
"Started" cell is empty is late. The status file prints this list on its first screen.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKER = ROOT / "docs" / "plan" / "owner-chains.md"


def rows(text: str) -> list[dict[str, str]]:
    """The rows of the first table under '## Chains', as dicts keyed by the header."""
    out: list[dict[str, str]] = []
    header: list[str] | None = None
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.strip() == "## Chains"
            continue
        if not inside or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
        elif not all(set(c) <= set("-: ") for c in cells):
            out.append(dict(zip(header, cells, strict=False)))
    return out


def late(text: str, today: dt.date) -> list[dict[str, str]]:
    found = []
    for r in rows(text):
        try:
            latest = dt.date.fromisoformat(r.get("Latest start", ""))
        except ValueError:
            continue
        if latest < today and not r.get("Started"):
            found.append(r)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--file", type=Path, default=TRACKER)
    ap.add_argument("--strict", action="store_true", help="exit 1 when a step is late")
    a = ap.parse_args(argv)
    found = late(a.file.read_text(encoding="utf-8"), a.today)
    for r in found:
        print(f"LATE {r['Chain']}: {r['Step']} (owner: {r['Owner role']}; latest start {r['Latest start']})")
    print(f"owner_chains: {len(found)} step(s) past the latest start with no start date, as of {a.today}")
    return 1 if found and a.strict else 0


if __name__ == "__main__":
    sys.exit(main())
