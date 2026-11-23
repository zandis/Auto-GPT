"""Build the compiler's terminology tables (Parquet) from CSV sources (SPEC §4.3.1).

Default sources are the curated demo tables in ``services/criteria_compiler/terminology/src``. On site, point
``--src`` at a directory holding the official NHI drug file, ICD-10-CM (NHI edition), NHI order codes, the LOINC
TW subset and the local-lab -> LOINC map, converted to the same column layout.
"""

from __future__ import annotations

import argparse
import csv
import gzip
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

TERM = Path(__file__).resolve().parents[1] / "services" / "criteria_compiler" / "terminology"
FILES = ["icd10cm_tw", "nhi_drug", "loinc_tw", "nhi_order", "department", "synonyms"]
# full code lists (D-122): gzipped CSV source -> <name>.parquet; the mapper uses them for code lookups and prefix
# groupers only. ICD-10-CM 2026 (CMS / CDC NCHS order file, public domain), every header and billable code.
FULL = {"icd10cm_full": "icd10cm_2026.csv.gz"}
# TERM-1 (D-858): ICD-10-CM's blocks and its Alphabetic Index (CMS, public domain; ``tools/icd10cm_cms.py``), for
# matching a concept's name: a block is a family of categories, an index term leads to a code
EXTRA = {"icd10cm_blocks": ("icd10cm_blocks_2026.csv", ("name", "first", "last")),
         "icd10cm_index": ("icd10cm_index_2026.csv.gz", ("term", "code", "see"))}  # fmt: skip


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
    for name, fname in FULL.items():
        path = src / fname
        if not path.exists():
            continue
        with gzip.open(path, "rt", encoding="utf-8", newline="") as gz:
            full = list(csv.DictReader(gz))
        table = pa.table({c: pa.array([r[c] for r in full], pa.string()) for c in ("code", "display")})
        pq.write_table(table, out / f"{name}.parquet", compression="zstd")
        counts[name] = len(full)
    for name, (fname, wanted) in EXTRA.items():
        path = src / fname
        if not path.exists():
            continue
        if fname.endswith(".gz"):
            with gzip.open(path, "rt", encoding="utf-8", newline="") as gz:
                extra = list(csv.DictReader(gz))
        else:
            with path.open(encoding="utf-8", newline="") as fh:
                extra = list(csv.DictReader(fh))
        table = pa.table({c: pa.array([r[c] for r in extra], pa.string()) for c in wanted})
        pq.write_table(table, out / f"{name}.parquet", compression="zstd")
        counts[name] = len(extra)
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
