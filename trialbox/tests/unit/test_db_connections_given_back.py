"""PG-LEAK (D-635): a test gives its database connections back. A console app test left 8 connections open for the
rest of the worker's life; the whole tree in one run reached the cluster's max_connections."""

from __future__ import annotations

import time
from typing import Any

import psycopg
import pytest
from tb_common.db import Database, split_url

from tests import db_connections as dc

# what each leaking test leaves referenced, as an app's stores are. NIGHT-ORDER (D-733): the two tests are the same
# shape, so the nightly's random order cannot break the pair: each leaves four connections and checks that what the
# other one left is closed; whichever runs second proves that the harness closed them after the first
_HELD: dict[str, list[Any]] = {}


def _open(url: str) -> int:
    with psycopg.connect(split_url(url)[0], autocommit=True) as con:
        row = con.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()"
        ).fetchone()
    assert row is not None
    return int(row[0])


def _con(x: Any) -> Any:
    return x._con if isinstance(x, Database) else x


def _leak_and_check(me: str, db_url: str) -> None:
    for other, held in _HELD.items():
        if other != me:
            assert len(held) == 4 and all(_con(x).closed for x in held), other  # the harness closed them
    assert dc.TRACKER.open_from_tests() == 0  # and nothing of an earlier test is open now
    held = [Database.connect(db_url, f"leak_{me}_{n}") for n in ("a", "b", "c")]
    held.append(psycopg.connect(split_url(db_url)[0]))  # a raw connection too
    _HELD[me] = held
    assert all(not _con(x).closed for x in held)


def test_1_a_test_that_leaves_stores_open(db_url: str) -> None:
    _leak_and_check("1", db_url)


def test_2_the_next_test_finds_them_closed(db_url: str) -> None:
    _leak_and_check("2", db_url)


@pytest.fixture(scope="module")
def wide(pg_cluster_url: str) -> Any:
    con = psycopg.connect(split_url(pg_cluster_url)[0], autocommit=True)
    yield con
    con.close()


def test_3_a_wider_fixtures_connection_is_left_alone(wide: Any, db_url: str) -> None:
    assert wide.execute("SELECT 1").fetchone() == (1,)


def test_4_and_is_still_open_in_the_next_test(wide: Any, db_url: str) -> None:
    assert not wide.closed and wide.execute("SELECT 2").fetchone() == (2,)


def test_5_the_cluster_holds_no_more_after_many_leaking_tests_than_before(db_url: str) -> None:
    """The slope itself: the count after this file's leaks is what a fresh connection sees, not 4 more per test."""
    before = _open(db_url)
    mark = dc.TRACKER.mark()
    leaked = [Database.connect(db_url, f"again_{i}") for i in range(5)]
    assert _open(db_url) == before + 5
    assert dc.TRACKER.close_since(mark) == 5  # what the harness does when a test ends
    assert all(x._con.closed for x in leaked)
    for _ in range(50):  # the server ends a backend a moment after its client closed
        if _open(db_url) == before:
            break
        time.sleep(0.1)
    assert _open(db_url) == before


@pytest.mark.nodb
def test_the_cluster_keeps_its_limit_the_slope_is_what_was_removed() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "tools" / "pglocal.py").read_text(encoding="utf-8")
    assert "max_connections=300" in text
