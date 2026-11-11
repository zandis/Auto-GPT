"""docs/plan/backlog.csv (TB-PLAN-06 T-679, LIFE-007): the deferred table stays visible, every row dated."""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKLOG = ROOT / "docs" / "plan" / "backlog.csv"
PLAN = ROOT / "docs" / "plan" / "28-master-plan-v6.md"


def _rows() -> list[dict[str, str]]:
    with BACKLOG.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _named_for_card() -> set[str]:
    """Every WS-18.n and D-nnn the plan lists against T-679 (the card row and the §6.2 source rows)."""
    named: set[str] = set()
    for line in PLAN.read_text(encoding="utf-8").splitlines():
        if "T-679" not in line:
            continue
        for lo, hi in re.findall(r"WS-18\.(\d) to WS-18\.(\d)", line):
            named |= {f"WS-18.{n}" for n in range(int(lo), int(hi) + 1)}
        named |= set(re.findall(r"\bD-\d{3}\b", line))
    return named


def test_every_row_has_an_earliest_date() -> None:
    rows = _rows()
    assert rows
    for row in rows:
        assert date.fromisoformat(row["earliest"]), row["id"]
        assert row["item"].strip() and row["basis"].strip(), row["id"]


def test_ids_unique() -> None:
    ids = [r["id"] for r in _rows()]
    assert len(ids) == len(set(ids))


def test_every_item_named_for_the_card_has_a_row() -> None:
    named = _named_for_card()
    assert {f"WS-18.{n}" for n in range(1, 8)} | {"D-141", "D-160"} <= named
    sources = {r["source"] for r in _rows()}
    assert named - sources == set()


def test_feasibility_filler_row_closes_life_007() -> None:
    rows = [r for r in _rows() if "feasibility questionnaire filler" in r["item"]]
    assert rows and rows[0]["closes"] == "LIFE-007"
