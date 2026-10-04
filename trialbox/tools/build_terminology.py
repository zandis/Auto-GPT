"""Build the compiler's terminology tables (Parquet) from CSV sources (SPEC §4.3.1).

Default sources are the curated demo tables in ``services/criteria_compiler/terminology/src``. On site, point
``--src`` at a directory holding the official NHI drug file, ICD-10-CM (NHI edition), NHI order codes, the LOINC
TW subset and the local-lab -> LOINC map, converted to the same column layout.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

TERM = Path(__file__).resolve().parents[1] / "services" / "criteria_compiler" / "terminology"
FILES = ["icd10cm_tw", "nhi_drug", "atc", "loinc_tw", "nhi_order", "department", "synonyms"]


def build(src: Path, out: Path) -> dict[str, int]:
    counts = {}
    for name in FILES:
        path = src / f"{name}.csv"
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            rows = [{k: (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(fh)]
        cols = list(rows[0]) if rows else []
        table = pa.table({c: pa.array([r[c] for r in rows], pa.string()) for c in cols})
        pq.write_table(table, out / f"{name}.parquet")
        counts[name] = len(rows)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, default=TERM / "src")
    ap.add_argument("--out", type=Path, default=TERM)
    args = ap.parse_args(argv)
    for name, n in build(args.src, args.out).items():
        print(f"{name}: {n} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
