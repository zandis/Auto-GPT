"""ICD-10-CM's block hierarchy and Alphabetic Index, extracted from CMS's code tables (TERM-1, D-858).

CMS publishes ICD-10-CM each year as public domain (US government work): the tabular list (chapters, blocks and
codes) and the Alphabetic Index (terms and the codes they lead to). This tool reads the release zip, as CMS ships it
(``<year>-code-tables-tabular-and-index.zip``), never unpacking it, and writes two CSV sources beside the code list:

* ``icd10cm_blocks_<year>.csv``: ``name, first, last``, one row per block and per chapter (``Ischemic heart
  diseases, I20, I25``);
* ``icd10cm_index_<year>.csv.gz``: ``term, code, see``, one row per main term and per first-level subterm
  (``Epilepsy, G40.909``; ``Attack, heart`` sees ``Infarct, myocardial``).

``tools/build_terminology.py`` turns them into Parquet for ``criteria_compiler.terminology``.

    python -m tools.icd10cm_cms <zip> [--year 2026] [--out services/criteria_compiler/terminology/src]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "services" / "criteria_compiler" / "terminology" / "src"
for _p in ("libs", "services"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from criteria_compiler.terminology import installed  # noqa: E402  (one reader of the release: install and build)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("zip", type=Path)
    ap.add_argument("--year", default="2026")
    ap.add_argument("--out", type=Path, default=SRC)
    args = ap.parse_args(argv)
    with zipfile.ZipFile(args.zip) as z:
        tab = installed.zip_member(z, f"icd10cm_tabular_{args.year}.xml")
        idx = installed.zip_member(z, f"icd10cm_index_{args.year}.xml")
    b = [(r["name"], r["first"], r["last"]) for r in installed.icd10cm_blocks(tab)]
    with (args.out / f"icd10cm_blocks_{args.year}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["name", "first", "last"])
        w.writerows(b)
    t = [(r["term"], r["code"], r["see"]) for r in installed.icd10cm_index(idx)]
    with gzip.open(args.out / f"icd10cm_index_{args.year}.csv.gz", "wt", encoding="utf-8", newline="") as gz:
        w = csv.writer(gz, lineterminator="\n")
        w.writerow(["term", "code", "see"])
        w.writerows(t)
    print(f"blocks: {len(b)}; index terms: {len(t)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
