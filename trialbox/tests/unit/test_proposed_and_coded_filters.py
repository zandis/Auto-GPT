"""The NEW-B-49 review's two test gaps: no test failed when ``proposed.SQL`` lost its NULL-means-everyone form, or
when the coded values lost a domain's record-id filter. Synthetic rows on a lake of every table."""

from __future__ import annotations

from typing import Any

import duckdb
import pytest

from tests.unit.test_patient_lists_are_joins import _lake


@pytest.fixture(scope="module")
def lake() -> duckdb.DuckDBPyConnection:
    con = _lake()
    con.execute("DELETE FROM site_fact")
    con.execute("DELETE FROM claim")
    for fid, pid, basis in (("F1", "P1", "proposed"), ("F2", "P2", "suspected"), ("F3", "P3", "confirmed")):
        con.execute(
            "INSERT INTO site_fact (fid, pid, domain, code, system, d, basis) VALUES (?, ?, 'condition', 'X', 's', "
            "DATE '2026-01-01', ?)",
            [fid, pid, basis],
        )
    for kid, pid in (("K1", "P1"), ("K2", "P1"), ("K3", "P2")):
        con.execute("INSERT INTO claim (kid, pid, created, product) VALUES (?, ?, DATE '2026-01-01', 'A')", [kid, pid])
    return con


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
    return con.execute(sql, params).fetchall()


def test_no_patient_list_means_every_patient_s_proposed_facts(lake: duckdb.DuckDBPyConnection) -> None:
    from matching import proposed

    everyone = {r[1] for r in _rows(lake, proposed.SQL, [None])}
    assert everyone == {"P1", "P2"}  # every proposed or suspected fact; a confirmed one is not proposed
    assert {r[1] for r in _rows(lake, proposed.SQL, [["P2"]])} == {"P2"}
    assert _rows(lake, proposed.SQL, [[]]) == []  # an empty list is nobody, never everybody


def test_each_domain_reads_only_the_record_ids_it_is_given(lake: duckdb.DuckDBPyConnection) -> None:
    from matching import coded_values

    got = _rows(lake, coded_values.SQL, [["P1", "P2"], ["K1"], "atc", "nhi", "dept"])
    claims = [r for r in got if r[0] == "claim"]
    assert [r[1] for r in claims] == ["K1"]  # K2 (the same patient) and K3 are not asked for
    got = _rows(lake, coded_values.SQL, [["P2"], ["K1", "K3"], "atc", "nhi", "dept"])
    assert [r[1] for r in got if r[0] == "claim"] == ["K3"]  # K1 is another patient's
