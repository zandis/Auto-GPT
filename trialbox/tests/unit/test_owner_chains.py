"""tools/owner_chains.py (T-663): every chain of TB-PLAN-06 §3.1 has a row, and late steps are printed."""

from __future__ import annotations

import datetime as dt

import pytest

from tools import owner_chains

CHAINS = (
    "CGMH-A",
    "CGMH-A′",
    "CGMH-B",
    "CGMH-C",
    "CGMH-D",
    "CGMH-E",
    "Japan-A",
    "Japan-B",
    "Japan-C",
    "Japan-D",
    "Japan-E",
    "People",
    "Code to G3",
    "Sponsor ack",
    "The PoC",
)


def test_every_chain_of_the_plan_has_a_row() -> None:
    rows = owner_chains.rows(owner_chains.TRACKER.read_text(encoding="utf-8"))
    names = {r["Chain"] for r in rows}
    assert set(CHAINS) <= names
    for r in rows:
        assert r["Owner role"] and r["Need by"]
        dt.date.fromisoformat(r["Latest start"])
        dt.date.fromisoformat(r["Need by"])


TABLE = """# T

## Chains

| Chain | Step | Owner role | Started | Evidence | Need by | Latest start | Float P50 / P90 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| X | sent | owner | | | 2027-01-01 | 2026-11-13 | 0 |
| Y | filed | owner | 2026-11-10 | receipt | 2027-01-01 | 2026-11-10 | 0 |
| Z | later | owner | | | 2027-01-01 | 2026-12-18 | 0 |

## Other

| Chain | Step | Owner role | Started | Evidence | Need by | Latest start | Float P50 / P90 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| W | not a chain | owner | | | 2027-01-01 | 2026-01-01 | 0 |
"""


def test_late_steps_are_those_past_the_latest_start_with_no_start() -> None:
    assert owner_chains.late(TABLE, dt.date(2026, 11, 13)) == []
    assert [r["Chain"] for r in owner_chains.late(TABLE, dt.date(2026, 11, 14))] == ["X"]
    assert [r["Chain"] for r in owner_chains.late(TABLE, dt.date(2026, 12, 19))] == ["X", "Z"]


def test_main_prints_and_strict_fails(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "chains.md"
    f.write_text(TABLE, encoding="utf-8")
    assert owner_chains.main(["--file", str(f), "--today", "2026-11-20"]) == 0
    out = capsys.readouterr().out
    assert "LATE X: sent" in out and "Y" not in out.split("owner_chains:")[0]
    assert owner_chains.main(["--file", str(f), "--today", "2026-11-20", "--strict"]) == 1
    assert owner_chains.main(["--file", str(f), "--today", "2026-11-01", "--strict"]) == 0
