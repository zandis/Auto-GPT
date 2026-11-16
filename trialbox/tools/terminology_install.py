"""Load code systems onto the box (D-528; TERM-1, D-858): ``python -m tools.terminology_install``.

No standard code system beyond the repository's present tables is committed; the site or the vendor supplies the
official files and this command loads them into ``TB_TERMINOLOGY_DIR`` (default ``/data/terminology``), each table
with its manifest line (source, version, licence note, sha256). ``trialbox doctor`` reports what is loaded.

    python -m tools.terminology_install icd10cm <CMS code-tables zip> [--year 2026] [--dir DIR]
    python -m tools.terminology_install status [--dir DIR]

``icd10cm``: CMS's ``<year>-code-tables-tabular-and-index.zip`` (US public domain; cms.gov, "ICD-10-CM" files),
read without unpacking: its tabular list's blocks and its Alphabetic Index.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("libs", "services"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))

from criteria_compiler.terminology import installed  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    icd = sub.add_parser("icd10cm", help="ICD-10-CM's blocks and Alphabetic Index from CMS's code-tables zip")
    icd.add_argument("zip", type=Path)
    icd.add_argument("--year", default="2026")
    icd.add_argument("--dir", type=Path, default=None)
    st = sub.add_parser("status", help="what is loaded, and what is refused")
    st.add_argument("--dir", type=Path, default=None)
    args = ap.parse_args(argv)
    where = args.dir or installed.installed_dir()
    if args.cmd == "icd10cm":
        for name, n in installed.install_icd10cm(args.zip, where, args.year).items():
            print(f"{name}: {n} rows loaded into {where}")
        return 0
    bad = 0
    for t in installed.status(where):
        print(f"{t.name}: {'REFUSED: ' + t.problem if t.problem else f'{t.rows} rows, {t.version}'}")
        bad += bool(t.problem)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
