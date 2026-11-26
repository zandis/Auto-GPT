"""M6-TW: a synthetic stand-in for a Taiwan hospital's read-only SQL views (CGRD style), built from a seed.

    python -m tools.standin_tw --out DIR [--seed 7] [--patients 60]

Base tables carry the synthetic hospital's rows with a change time (``updated_at``); the views the box reads
(``PATIENT_VIEW`` ...) are the site's own column names, written from the shipped site template's ``rename`` and
``values``, so the real template is what a night maps. Synthetic only: no value comes from a real source.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Column, MetaData, String, Table, case, create_engine, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql import Select

from tools.synth.generator import TABLES, generate

MAPPING = Path(__file__).resolve().parent.parent / "services/adapter/mapping"
TEMPLATE = MAPPING / "templates/cgrd_sql_site.yaml"
NO_CHANGE_TIME = {"patient", "practitioner", "appointment", "registry"}  # tables the template reads whole
TABLES_KEY = {"diagnosis": "diag_no", "lab": "lab_no", "medication": "rx_no", "encounter": "enc_no", "note": "note_no"}
LOCAL_CODE = "ZZ-LOCAL"  # a lab code no look-up knows
EDIT_VALUE = {
    "lab": ("result_value", "77.7"),
    "medication": ("daily_dose", "77.5"),
    "diagnosis": ("diag_date", "2026-09-09"),
}  # the clinical value a hospital edit changes, per table
UNLISTED_VIEW = "ALLERGY_VIEW"  # a view the mapping does not list (allergies: 10B-7, not read)


def _stamp(i: int) -> str:
    return f"2026-10-04 {i % 24:02d}:{i % 60:02d}:00"  # fixed, never the wall clock


def _table(meta: MetaData, name: str, cols: list[str]) -> Table:
    return Table(name, meta, *(Column(c, String) for c in cols))


def build(path: Path, *, seed: int = 7, patients: int = 60, ref_date: date = date(2026, 10, 5)) -> dict[str, int]:
    """Write the database at ``path``; return the rows per canonical table (the builder's own counts)."""
    spec = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))["tables"]
    data = generate(seed, "tw-a", ref_date, patients, "1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{path}")
    meta, counts = MetaData(), {}
    views: list[tuple[str, Table, dict[str, str], dict[str, dict[str, str]]]] = []
    inserts: list[tuple[Table, list[dict[str, str]]]] = []
    for name in TABLES:
        rows = [dict(r) for r in data.tables[name]]
        if name == "lab":  # one row with a local code the look-up lacks, so the night has something to count
            rows.append({**rows[0], "lab_no": "L-ZZ", "local_code": LOCAL_CODE})
        counts[name] = len(rows)
        if not rows:
            continue
        change = name not in NO_CHANGE_TIME
        cols = [*rows[0], *(["updated_at"] if change else [])]
        base = _table(meta, f"base_{name}", cols)
        stamped = [{c: "" if v is None else str(v) for c, v in r.items()} for r in rows]
        if change:
            for i, r in enumerate(stamped):
                r["updated_at"] = _stamp(i)
        inserts.append((base, stamped))
        tspec = spec[name]
        rename = {v: k for k, v in tspec.get("rename", {}).items()}  # canonical -> the site's column
        inv = {c: {v: k for k, v in m.items()} for c, m in tspec.get("values", {}).items()}  # canonical -> site value
        views.append((tspec["source"], base, rename, inv))
    allergy = _table(meta, "base_allergy", ["mrn", "substance"])
    inserts.append((allergy, [{"mrn": data.tables["patient"][0]["mrn"], "substance": f"x{i}"} for i in range(3)]))
    meta.create_all(engine)
    with engine.begin() as con:
        for table, rows in inserts:
            con.execute(table.insert(), rows)
        for view, base, rename, inv in views:
            sel = [
                (case(inv[c.name], value=c, else_=c) if c.name in inv else c).label(rename.get(c.name, c.name))
                for c in base.columns
            ]
            _create_view(con, view, select(*sel))
        _create_view(con, UNLISTED_VIEW, select(allergy.c.mrn.label("CHART_NO"), allergy.c.substance.label("ALLERGEN")))
    engine.dispose()
    return counts


def _create_view(con: Connection, name: str, query: Select[Any]) -> None:
    con.exec_driver_sql(f"CREATE VIEW {name} AS {query.compile(compile_kwargs={'literal_binds': True})}")


def site_mapping(folder: Path) -> Path:
    """The site's mapping as the template says to make it: a copy with its lab look-up beside it."""
    folder.mkdir(parents=True, exist_ok=True)
    text = TEMPLATE.read_text(encoding="utf-8").replace(
        "../tw_core/demo_his.yaml", str(MAPPING / "tw_core/demo_his.yaml")
    )
    (folder / "standin_tw.yaml").write_text(text, encoding="utf-8")
    (folder / "lab_local_to_loinc.csv").write_bytes((MAPPING / "tw_core/lab_local_to_loinc.csv").read_bytes())
    return folder / "standin_tw.yaml"


def touch(path: Path, table: str, keys: list[str], stamp: str) -> None:
    """The hospital edits rows ``keys`` of ``table`` at ``stamp``: their change time moves and one mapped clinical
    value changes (EDIT_VALUE), so a lost update shows in the data and not only in the row count."""
    engine: Engine = create_engine(f"sqlite:///{path}")
    base = Table(f"base_{table}", MetaData(), autoload_with=engine)
    with engine.begin() as con:
        col, val = EDIT_VALUE[table]
        con.execute(update(base).where(base.c[TABLES_KEY[table]].in_(keys)).values(updated_at=stamp, **{col: val}))
    engine.dispose()


def readonly_dsn(path: Path) -> str:
    """The DSN of an account that can read and cannot write (the door needs no more)."""
    return f"sqlite:///file:{path}?mode=ro&uri=true"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--patients", type=int, default=60)
    a = ap.parse_args(argv)
    counts = build(a.out / "standin_tw.sqlite", seed=a.seed, patients=a.patients)
    print(" ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
