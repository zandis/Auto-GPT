"""Deep review 2026-11-13 (data), DATA-004: two sources that agree a patient died and disagree on WHEN.

Before the fix both lakes (the legacy flattener's merge and the OMOP export) made the date unknown and kept
``deceased`` true. The base cohort of every compiled ruleset reads that as "dead, no date" and leaves the patient out
at every index date, even one before both claimed deaths. Now, while the conflict is open, the earliest claimed date
stands: the patient is in before any source says they died and out from the first claim on (a death fails closed,
D-400, in the window the sources dispute). A steward who keeps the date unknown is followed.
"""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from tests.unit.test_omop_core import _feed, _legacy, _load, _site, db, feed_dir  # noqa: F401 - fixtures by name

EARLY, LATE = "2026-10-01", "2026-10-05"


def _two_deaths(feed_dir: Path) -> tuple[str, dict[str, Any], dict[str, Any]]:  # noqa: F811
    feed, site = _feed(feed_dir), _site(feed_dir)
    in_feed = {p["id"] for p in feed["Patient"]}
    pid = next(p["id"] for p in site["Patient"] if p["id"] in in_feed)
    feed, site = copy.deepcopy(feed), copy.deepcopy(site)
    for p in feed["Patient"]:
        if p["id"] == pid:
            p["deceasedDateTime"] = EARLY
    for p in site["Patient"]:
        if p["id"] == pid:
            p["deceasedDateTime"] = LATE
    return pid, feed, site


def _in_base(row: dict[str, Any], index_date: str) -> bool:
    """The base cohort's death and birth test of ``compile_sql/generator.py`` on one patient row."""
    con = duckdb.connect()
    con.execute("CREATE TABLE patient (deceased_date DATE, deceased BOOLEAN)")
    con.execute("INSERT INTO patient VALUES (?, ?)", (row["deceased_date"], row["deceased"]))
    from criteria_compiler.compile_sql import generator

    src = Path(generator.__file__).read_text(encoding="utf-8")
    assert "(p.deceased_date IS NULL OR p.deceased_date > i.index_date)" in src  # the clause tested here
    assert "(p.deceased_date IS NOT NULL OR p.deceased IS NOT TRUE)" in src
    n = con.execute(
        "SELECT count(*) FROM patient p CROSS JOIN (SELECT CAST(? AS DATE) AS index_date) i "
        "WHERE (p.deceased_date IS NULL OR p.deceased_date > i.index_date) "
        "AND (p.deceased_date IS NOT NULL OR p.deceased IS NOT TRUE)",
        (index_date,),
    ).fetchone()
    return bool(n and n[0])


def test_the_legacy_merge_keeps_the_earliest_claimed_death(feed_dir: Path) -> None:  # noqa: F811
    pid, feed, site = _two_deaths(feed_dir)
    row = next(r for r in _legacy(feed, site)["patient"] if r["pid"] == pid)
    assert str(row["deceased_date"]) == EARLY and row["deceased"] is True  # before: None and True
    assert _in_base(row, "2026-06-30")  # before both deaths: in (before the fix: out)
    assert not _in_base(row, "2026-10-03")  # between: one source says dead; a death fails closed (D-400)
    assert not _in_base(row, "2026-10-06")  # after both: out


def test_the_omop_export_keeps_the_earliest_claimed_death(feed_dir: Path, db: Any) -> None:  # noqa: F811
    from omop import conflicts
    from omop.export import export_rows

    pid, feed, site = _two_deaths(feed_dir)
    _load(db, feed, site)
    assert conflicts.counts(db)["deceased_date"] == 1  # the disagreement is recorded for the steward
    row = {r["pid"]: r for r in export_rows(db)["patient"]}[pid]
    assert row["deceased_date"] == date.fromisoformat(EARLY) and row["deceased"] is True  # before: None and True
    assert _in_base(row, "2026-06-30")
    assert not _in_base(row, "2026-10-03")
    # the steward picks the later date: it stands
    c = next(c for c in conflicts.listing(db) if c.item == "deceased_date")
    conflicts.resolve(db, c.conflict_id, LATE, by="console:stw", reason="the death certificate")
    row = {r["pid"]: r for r in export_rows(db)["patient"]}[pid]
    assert row["deceased_date"] == date.fromisoformat(LATE)
    assert _in_base(row, "2026-10-03") and not _in_base(row, "2026-10-06")
