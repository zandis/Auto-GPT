"""D-684: the EDC prefill reads "this snapshot has no site facts" from the lake's own answer, never from the words
of an error. Until this card any failure whose text named ``site_fact`` gave no site facts, silently: a proposed
fact then no longer held a draft back (``only_proposed``), and a confirmed one no longer labelled its citation.
Synthetic data only."""

from __future__ import annotations

from typing import Any

import duckdb
import pytest
from edc.prefill import LakeFacts

PID = "a1b2c3d4e5f60001"


class Lake:
    """An in-process lake (DuckDB, as the lake runs it); ``fail`` makes every query of ``site_fact`` fail."""

    def __init__(self, ddl: str | None, fail: str | None = None) -> None:
        self.con = duckdb.connect()
        self.fail = fail
        self.asked: list[str] = []
        if ddl:
            self.con.execute(ddl)

    def snapshot(self) -> str:
        return "2026-11-02"

    def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
        self.asked.append(sql)
        if self.fail and " FROM site_fact " in sql:
            raise RuntimeError(self.fail)
        return self.con.execute(sql, params or []).to_arrow_table()


TABLE = "CREATE TABLE site_fact (fid VARCHAR, pid VARCHAR, domain VARCHAR, code VARCHAR, d DATE, basis VARCHAR)"


def test_a_snapshot_built_before_the_site_facts_holds_none() -> None:
    lake = Lake(None)
    assert LakeFacts(lake).site_facts(PID) == []
    assert any("duckdb_tables()" in sql for sql in lake.asked)  # the lake was asked; nothing was read from a text


def test_the_site_facts_are_read() -> None:
    lake = Lake(TABLE)
    lake.con.execute(
        "INSERT INTO site_fact VALUES ('f1', ?, 'condition', 'M10.9', DATE '2026-10-01', 'proposed')", [PID]
    )
    assert [(r["fid"], r["basis"]) for r in LakeFacts(lake).site_facts(PID)] == [("f1", "proposed")]


@pytest.mark.parametrize(
    "text",
    [
        "IO Error: cannot read the file of table site_fact",
        "Catalog Error: Table with name site_fact does not exist!",  # the words of a missing table, and it is there
        "connection reset while reading site_fact",
    ],
)
def test_a_failure_that_names_the_table_is_not_read_as_no_facts(text: str) -> None:
    lake = Lake(TABLE, fail=text)
    with pytest.raises(RuntimeError, match="site_fact"):
        LakeFacts(lake).site_facts(PID)


def test_a_table_that_lacks_a_column_stops_the_draft() -> None:
    """A real failure of the engine whose text names the table: a snapshot with an older shape of it."""
    lake = Lake("CREATE TABLE site_fact (fid VARCHAR, pid VARCHAR)")
    with pytest.raises(duckdb.Error):
        LakeFacts(lake).site_facts(PID)


def test_a_lake_that_cannot_say_whether_the_table_is_there_stops_the_draft() -> None:
    class Down(Lake):
        def query(self, sql: str, params: list[Any] | None = None, snapshot: str | None = None) -> Any:
            raise ConnectionError("the lake does not answer (site_fact)")

    with pytest.raises(ConnectionError):
        LakeFacts(Down(None)).site_facts(PID)
