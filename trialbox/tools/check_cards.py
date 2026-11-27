"""check_cards v2 (RULES-ARCH item 4): every card fixture through the product's own SQL compiler, one oracle.

Each fixture's facts become a tiny in-memory lake (the flattened tables of ``lake.flatten.SCHEMAS``, plus the OMOP
``measurement`` / ``drug_exposure`` rows that carry a result's reference range and a medication's dose); the card is
instantiated with the fixture's params, compiled by ``SqlGenerator``, run in DuckDB, and the patient's ``C_<ID>``
(TRUE / FALSE / NULL) must equal the fixture's T / F / U.

A fact is ``{"table": <lake table>, <column>: value, ...}`` for patient ``p`` (the ``pid`` is filled in). Extras:
an ``observation`` with ``ref_high`` / ``ref_low`` gets its OMOP measurement row (its own reference range); a
``medication`` with ``quantity`` / ``dose_unit`` / ``days_supply`` gets its OMOP drug exposure. Without a
``patient`` fact the patient is born 1970-01-01, sex not recorded. The index date is the fixture's ``index_date``,
else 2026-10-05. Value sets are data: the caller passes them (never in a card).

    python -m tools.check_cards --valuesets DIR [--cards cards]    # exit 1 on any mismatch or broken fixture
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import duckdb
from criteria_compiler.cards import CARDS_DIR, Card, Fixture, instantiate, load
from criteria_compiler.compile_sql.generator import SqlGenerator
from criteria_compiler.semantics import SiteRefRanges
from criteria_compiler.terminology.mapper import Terminology, ValueSets
from lake.flatten import PROVENANCE_COLS, SCHEMAS

PID = "p"
INDEX_DATE = "2026-10-05"
VERDICT = {True: "T", False: "F", None: "U"}
_OMOP = """
CREATE TABLE measurement (measurement_id INTEGER, person_id INTEGER, measurement_source_value VARCHAR,
    value_as_number DOUBLE, range_high DOUBLE, range_low DOUBLE);
CREATE TABLE drug_exposure (drug_exposure_id INTEGER, person_id INTEGER, quantity DOUBLE,
    dose_unit_source_value VARCHAR, days_supply INTEGER, drug_exposure_start_date DATE, drug_exposure_end_date DATE);
CREATE TABLE tb_id_map (id_kind VARCHAR, omop_id INTEGER, source_id VARCHAR);
CREATE TABLE tb_record (cdm_table VARCHAR, record_id INTEGER, source_record_id VARCHAR, part INTEGER, status VARCHAR);
CREATE TABLE criterion_anchors (ruleset VARCHAR, pid VARCHAR, index_date DATE, screening_date DATE,
    randomization_date DATE);
INSERT INTO tb_id_map VALUES ('person', 1, 'p');
"""
_EXTRA = {"observation": ("ref_high", "ref_low"), "medication": ("quantity", "dose_unit", "days_supply")}


class FixtureError(ValueError):
    """A fixture the lake cannot hold (an unknown table or column, a note fact)."""


def lake(facts: list[dict[str, Any]]) -> duckdb.DuckDBPyConnection:
    """The in-memory lake of one fixture."""
    con = duckdb.connect()
    for name, cols in SCHEMAS.items():
        con.execute(f"CREATE TABLE {name} ({', '.join(f'"{c}" {t}' for c, t in cols)})")
    con.execute(_OMOP)
    if not any(f.get("table") == "patient" for f in facts):
        facts = [{"table": "patient", "birth_date": "1970-01-01"}, *facts]
    for n, fact in enumerate(facts, start=1):
        table = fact.get("table")
        if table == "note":
            raise FixtureError(f"fact {n}: a note fact has no lake relation the SQL compiler reads")
        if table not in SCHEMAS:
            raise FixtureError(f"fact {n}: no lake table {table!r}")
        row: dict[str, Any] = {k: v for k, v in fact.items() if k != "table" and k not in _EXTRA.get(table, ())}
        row["pid"] = PID
        known = {c for c, _ in SCHEMAS[table]} - set(PROVENANCE_COLS)
        if set(row) - known:
            raise FixtureError(f"fact {n}: {table} has no column {', '.join(sorted(set(row) - known))}")
        names = ", ".join(f'"{c}"' for c in row)
        con.execute(f"INSERT INTO {table} ({names}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        if table == "observation" and ("ref_high" in fact or "ref_low" in fact):
            con.execute("INSERT INTO tb_record VALUES ('measurement', ?, ?, 0, 'coded')", [n, row.get("oid")])
            con.execute(
                "INSERT INTO measurement VALUES (?, 1, ?, ?, ?, ?)",
                [n, row.get("code"), row.get("value_num"), fact.get("ref_high"), fact.get("ref_low")],
            )
        if table == "medication" and any(k in fact for k in _EXTRA["medication"]):
            con.execute("INSERT INTO tb_record VALUES ('drug_exposure', ?, ?, 0, 'coded')", [n, row.get("mid")])
            con.execute(
                "INSERT INTO drug_exposure VALUES (?, 1, ?, ?, ?, ?, ?)",
                [n, fact.get("quantity"), fact.get("dose_unit"), fact.get("days_supply"), row.get("start"),
                 row.get("end")],
            )  # fmt: skip
    return con


def run_fixture(
    card: Card, fixture: Fixture, valuesets: dict[str, Any], ref_ranges: SiteRefRanges | None = None
) -> str:
    """The verdict (T / F / U) the compiled card gives on the fixture's lake."""
    ir = instantiate(card, fixture.params)
    sql = SqlGenerator("CARD", card.version, ValueSets("CARD", valuesets, Terminology()), ref_ranges).render([ir])
    con = lake(fixture.facts)
    try:
        cur = con.execute(sql, [[fixture.index_date or INDEX_DATE], None])
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    finally:
        con.close()
    mine = [r for r in rows if r["pid"] == PID]
    if len(mine) != 1:
        raise FixtureError(f"{len(mine)} result rows for the fixture patient (not in the base cohort?)")
    return VERDICT[mine[0]["C_" + ir.id]]


def check(card: Card, valuesets: dict[str, Any]) -> list[dict[str, str]]:
    """One row per fixture: name, expect, got (or the error), ok."""
    out = []
    for fx in card.fixtures:
        try:
            got = run_fixture(card, fx, valuesets)
        except (ValueError, duckdb.Error) as exc:
            got = f"error: {exc}"
        out.append({"card": f"{card.card_id}@{card.version}", "fixture": fx.name, "expect": fx.expect, "got": got,
                    "ok": "yes" if got == fx.expect else "no"})  # fmt: skip
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools.check_cards", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--cards", type=Path, default=CARDS_DIR)
    ap.add_argument("--valuesets", type=Path, required=True, help="a directory of ValueSet JSON files, by name")
    args = ap.parse_args(argv)
    vs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.valuesets.glob("*.json"))}
    rows = []
    for path in sorted(args.cards.glob("*/*.json")):
        rows += check(load(path.parent.name, path.stem, args.cards), vs)
    for r in rows:
        print("\t".join(r.values()))
    bad = [r for r in rows if r["ok"] != "yes"]
    print(f"{len(rows) - len(bad)} of {len(rows)} fixtures agree with the compiler", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
