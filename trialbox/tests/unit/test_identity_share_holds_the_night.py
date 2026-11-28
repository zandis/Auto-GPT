"""SAFE-1 A4: chart numbers that arrive as two people hold their records, and the night goes on (H34-06 with
PRODUCT-2, ``tests/unit/test_one_chart_two_people.py``). Many of them are not records but the mapping's chart-number
column: when at least ``IDENTITY_NIGHT_MIN`` chart numbers, and more than ``IDENTITY_NIGHT_SHARE`` of the night's,
arrive as two people, the night itself is held for the steward, its records still withheld and listed. Synthetic site
A (600 patients) only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adapter.ndjson import snapshot_dir
from adapter.pipeline import IDENTITY_CONFLICT, IDENTITY_NIGHT_MIN, IDENTITY_NIGHT_SHARE
from tb_common.crypto import pid_for_mrn

import tests.unit.test_one_chart_two_people as _two
from tests.unit.test_one_chart_two_people import (
    KEY,
    NEXT,
    SITE_A,
    _feed,
    _from_good,
    _night,
    _other_person,
    _rows,
    _write,
)

good = _two.good  # the fixture, found by name


def _two_people_on(good: Any, tmp_path: Path, n: int) -> tuple[Any, Any, list[str]]:
    cfg, _rb = _from_good(good, tmp_path)
    feed = _feed(tmp_path)
    rows = _rows(feed / "patient.csv")
    _write(feed / "patient.csv", [*rows, *(_other_person(r) for r in rows[:n])])
    return cfg, _night(cfg, feed, NEXT), [pid_for_mrn(KEY, r["mrn"]) for r in rows[:n]]


def test_the_values() -> None:
    assert (IDENTITY_NIGHT_SHARE, IDENTITY_NIGHT_MIN) == (0.01, 10)
    assert len(_rows(SITE_A / "patient.csv")) == 600  # 11 charts are 1.8 %, 7 are 1.2 %


def test_many_charts_with_two_people_hold_the_night(good: Any, tmp_path: Path) -> None:
    cfg, rep, pids = _two_people_on(good, tmp_path, 11)
    assert rep.held and not rep.passed
    assert any("chart-number column" in e and "11 of 600" in e for e in rep.errors), rep.errors
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    assert sorted(said["tonight"]) == sorted(pids)  # still listed for the steward, still withheld


def test_a_few_charts_over_the_share_but_under_the_floor_hold_only_their_records(good: Any, tmp_path: Path) -> None:
    cfg, rep, pids = _two_people_on(good, tmp_path, 7)
    assert rep.passed and not rep.held, rep.errors
    said = json.loads((snapshot_dir(cfg.lake_dir, NEXT) / IDENTITY_CONFLICT).read_text())
    assert sorted(said["held"]) == sorted(pids)
