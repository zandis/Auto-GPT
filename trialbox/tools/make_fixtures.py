"""Generate the synthetic hospitals used by every test layer (SPEC §11.1).

Writes, per site, HIS-like exports in two source formats the adapter supports:
``<out>/<site>/*.csv`` (source ``csv``) and ``<out>/<site>/cgrd.sqlite`` (source ``cgrd_sql``), plus ground truth:
``note_truth.json`` (note criteria), ``human_truth.json``, ``needles.json`` (20 seeded retrieval queries) and
``states.json`` (planted per-patient states, for coverage checks).

Usage::

    python tools/make_fixtures.py --out tests/fixtures/synthetic_patients            # site-a (600) + site-b (520)
    python tools/make_fixtures.py --out /tmp/x --sites a --patients 1000 --seed 7
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import date
from pathlib import Path

from tools.synth.generator import TABLES, SiteData, generate

SITES = {"a": ("DEMO-A", "1", 42, 600), "b": ("DEMO-B", "2", 4242, 520)}


def write_site(data: SiteData, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        rows = data.tables[name]
        cols = list(rows[0]) if rows else []
        with (out / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    db = out / "cgrd.sqlite"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    for name in TABLES:
        rows = data.tables[name]
        if not rows:
            continue
        cols = list(rows[0])
        con.execute(f'CREATE TABLE "{name}" ({", ".join(f"{c} TEXT" for c in cols)})')
        con.executemany(
            f'INSERT INTO "{name}" VALUES ({", ".join("?" for _ in cols)})',
            [tuple("" if r[c] is None else str(r[c]) for c in cols) for r in rows],
        )
    con.commit()
    con.close()
    meta = {
        "site_id": data.site_id,
        "ref_date": data.ref_date.isoformat(),
        "counts": {k: len(v) for k, v in data.tables.items()},
    }
    for fname, obj in (
        ("note_truth.json", data.note_truth),
        ("human_truth.json", data.human_truth),
        ("needles.json", data.needles),
        ("states.json", data.states),
        ("meta.json", meta),
    ):
        (out / fname).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("tests/fixtures/synthetic_patients"))
    ap.add_argument("--sites", default="ab")
    ap.add_argument("--patients", type=int, default=0, help="override patient count")
    ap.add_argument("--seed", type=int, default=0, help="override seed")
    ap.add_argument("--ref-date", default="2026-10-05", help="run date the data is relative to")
    args = ap.parse_args(argv)
    for key in args.sites:
        site_id, prefix, seed, n = SITES[key]
        data = generate(args.seed or seed, site_id, date.fromisoformat(args.ref_date), args.patients or n, prefix)
        write_site(data, args.out / f"site-{key}")
        print(
            f"site-{key}: {len(data.tables['patient'])} patients, "
            + ", ".join(f"{k}={len(v)}" for k, v in data.tables.items() if k != "patient")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
