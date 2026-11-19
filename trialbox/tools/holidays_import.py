"""Write ``libs/tb_common/refdata_src/holidays_jp.csv`` from the Cabinet Office's holiday file (10C-14, JP-15).

The yearly update, one command (runbook: docs/runbook/01-install-a-new-site.md, "Working days"). The vendor
downloads the file as published (内閣府「国民の祝日について」, https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv,
Shift_JIS/CP932, ``国民の祝日・休日月日,国民の祝日・休日名称``), records its sha256 in the licence register row
``jp-holidays`` and runs::

    python3 -m tools.holidays_import syukujitsu.csv --sha256 <hex> --years 2026-2028
    python3 -m tools.holidays_import syukujitsu.csv --sha256 <hex> --years 2025-2027 --check   # exit 1 if different

The file is checked against the sha256 given (a different file is refused, never read), the dates and names are kept
as published, and the two kinds the source calls 休日 are told apart: a day between two holidays is a citizens'
holiday (国民の休日), any other 休日 a substitute holiday (振替休日). Nothing is fetched here. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "libs" / "tb_common" / "refdata_src" / "holidays_jp.csv"
HEADER = ("国民の祝日・休日月日", "国民の祝日・休日名称")
REST_DAY = "休日"


class SourceError(ValueError):
    """The source file is not the one recorded, or not in the published layout."""


def rows_of(data: bytes, sha256: str) -> dict[date, str]:
    """The published file's days and names, after its sha256 is checked."""
    got = hashlib.sha256(data).hexdigest()
    if got != sha256.strip().lower():
        raise SourceError(f"the file's sha256 is {got}, not the one recorded ({sha256}): not read")
    reader = csv.reader(io.StringIO(data.decode("cp932")))
    head = next(reader, None)
    if head is None or tuple(h.strip() for h in head) != HEADER:
        raise SourceError(f"the first line is not the Cabinet Office's header {','.join(HEADER)}")
    out: dict[date, str] = {}
    for row in reader:
        if not row:
            continue
        y, m, d = (int(x) for x in row[0].strip().split("/"))
        out[date(y, m, d)] = row[1].strip()
    return out


def render(days: dict[date, str], first: int, last: int) -> str:
    """``date,name,kind`` for the years ``first`` to ``last``, as ``tb_common.workdays`` reads it."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["date", "name", "kind"])
    for d in sorted(days):
        if not first <= d.year <= last:
            continue
        name = days[d]
        kind = "holiday"
        if name == REST_DAY:
            before, after = days.get(d - timedelta(days=1)), days.get(d + timedelta(days=1))
            kind = "citizens" if before not in (None, REST_DAY) and after not in (None, REST_DAY) else "substitute"
        w.writerow([d.isoformat(), name, kind])
    return out.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.holidays_import", description=__doc__.split("\n\n")[0])
    ap.add_argument("source", type=Path, help="syukujitsu.csv as downloaded")
    ap.add_argument("--sha256", required=True, help="the sha256 recorded in the licence register row jp-holidays")
    ap.add_argument("--years", required=True, help="FIRST-LAST, for example 2026-2028")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true", help="compare with --out instead of writing it")
    a = ap.parse_args(argv)
    first, _, last = a.years.partition("-")
    try:
        text = render(rows_of(a.source.read_bytes(), a.sha256), int(first), int(last or first))
    except (SourceError, ValueError, OSError) as exc:
        print(f"holidays_import: {exc}", file=sys.stderr)
        return 2
    if a.check:
        same = a.out.is_file() and a.out.read_text(encoding="utf-8") == text
        print(f"holidays_import: {a.out} {'matches' if same else 'differs from'} the source")
        return 0 if same else 1
    a.out.write_text(text, encoding="utf-8")
    print(f"holidays_import: wrote {a.out} ({text.count(chr(10)) - 1} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
