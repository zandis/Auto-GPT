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
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "services" / "criteria_compiler" / "terminology" / "src"
_RANGE = re.compile(r"^([A-Z][0-9A-Z]{2})-([A-Z][0-9A-Z]{2})$")


def _member(z: zipfile.ZipFile, suffix: str) -> bytes:
    names = [n for n in z.namelist() if n.lower().endswith(suffix)]
    if len(names) != 1:
        raise SystemExit(f"the zip holds {len(names)} files ending {suffix!r}: not a CMS code-tables zip")
    return z.read(names[0])


def blocks(tabular: bytes) -> list[tuple[str, str, str]]:
    """(name, first, last) of every block and chapter, in the tabular list's order."""
    root = ET.fromstring(tabular)
    out: list[tuple[str, str, str]] = []
    for ch in root.iter("chapter"):
        ranges = []
        for sec in ch.findall("section"):
            m = _RANGE.match(sec.get("id") or "")
            if m:
                name = re.sub(r"\s*\([A-Z0-9-]+\)\s*$", "", (sec.findtext("desc") or "").strip())
                out.append((name, m.group(1), m.group(2)))
                ranges.append((m.group(1), m.group(2)))
        if ranges:
            name = re.sub(r"\s*\([A-Z0-9-]+\)\s*$", "", (ch.findtext("desc") or "").strip())
            out.append((name, ranges[0][0], ranges[-1][1]))
    return out


def index_terms(index: bytes) -> list[tuple[str, str, str]]:
    """(term, code, see) of every main term and first-level subterm that leads to a code or to another term."""
    root = ET.fromstring(index)
    out: list[tuple[str, str, str]] = []
    for mt in root.iter("mainTerm"):
        title = " ".join((mt.findtext("title") or "").split())
        code, see = (mt.findtext("code") or "").strip(), " ".join((mt.findtext("see") or "").split())
        if title and (code or see):
            out.append((title, code, "" if code else see))
        for sub in mt.findall("term"):
            st, sc = " ".join((sub.findtext("title") or "").split()), (sub.findtext("code") or "").strip()
            if title and st and sc:
                out.append((f"{title}, {st}", sc, ""))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("zip", type=Path)
    ap.add_argument("--year", default="2026")
    ap.add_argument("--out", type=Path, default=SRC)
    args = ap.parse_args(argv)
    with zipfile.ZipFile(args.zip) as z:
        tab, idx = _member(z, f"icd10cm_tabular_{args.year}.xml"), _member(z, f"icd10cm_index_{args.year}.xml")
    b = blocks(tab)
    with (args.out / f"icd10cm_blocks_{args.year}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["name", "first", "last"])
        w.writerows(b)
    t = index_terms(idx)
    with gzip.open(args.out / f"icd10cm_index_{args.year}.csv.gz", "wt", encoding="utf-8", newline="") as gz:
        w = csv.writer(gz, lineterminator="\n")
        w.writerow(["term", "code", "see"])
        w.writerows(t)
    print(f"blocks: {len(b)}; index terms: {len(t)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
