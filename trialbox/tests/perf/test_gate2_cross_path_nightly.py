"""Gate 2's cross-path test, the bench's nightly version (review 2026-11-22 §3.5 step 6): hundreds of generated
synthetic people in generated collision groups (record numbers shared within and across two source systems, chart
numbers written four ways), through every road, judged by the same invariants as the unit tier's
``tests/unit/test_gate2_cross_path.py``.

Marker ``perf``: the unit tier leaves it out (``-m "not ... perf"``); the bench runs it::

    TB_G2_PEOPLE=400 TB_G2_SEED=20261122 .venv/bin/python -m pytest -q -n 3 -m perf \\
        tests/perf/test_gate2_cross_path_nightly.py

``TB_G2_SEED`` defaults to today's date, so each night draws other collisions; a failure names its seed, and the same
seed gives the same people again.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from tests import gate2_kit as kit
from tests import gate2_people as gp

pytestmark = pytest.mark.perf

PEOPLE = int(os.environ.get("TB_G2_PEOPLE", "300"))
SEED = int(os.environ.get("TB_G2_SEED", date.today().strftime("%Y%m%d")))


@pytest.fixture(autouse=True)
def _site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CHARTNO_RULE", gp.CHART_RULE)
    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    monkeypatch.setenv("TB_TZ", kit.TZ)
    monkeypatch.setenv("TB_SITE_ID", kit.SITE)


@pytest.mark.parametrize("order", gp.ORDERS)
@pytest.mark.parametrize("road", [r.name for r in kit.ROADS])
def test_generated_people_cross_every_road(road: str, order: str, tmp_path: Path, db_url: str) -> None:
    story = gp.generated_story(PEOPLE, SEED)
    d = kit.drive(kit.ROAD[road], story, order, tmp_path, db_url, edc=order == "as_written")
    assert d.kinds == set(kit.ROAD[road].kinds)
    findings = kit.judge(d)
    assert not findings, f"seed {SEED}, {PEOPLE} people, {road} / {order}: {len(findings)} findings\n" + kit.summary(
        findings[:200]
    )
