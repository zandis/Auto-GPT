"""Gate 2's cross-path test (review 2026-11-22 §3.5, as the owner ruled): can two people ever share a record, or one
person's record split, by any road into the box?

Synthetic people who exist to collide (:mod:`tests.gate2_people`) are driven through every road the product has
(:mod:`tests.gate2_kit`), in three row orders and once more as a replay, and the six invariants are judged over what
the box published: the served NDJSON, the screening lake, the OMOP store and, for a held chart, the patient index.
Each case reports every finding at once (``<invariant> store=<store> person=<letters>: <what>``).

The randomised version with hundreds of generated people is ``tests/perf/test_gate2_cross_path_nightly.py`` (marker
``perf``: the bench's nightly). The planted-mistake harness that proves this test is ``tools/gate2_planted.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

from tests import gate2_kit as kit
from tests import gate2_people as gp

STORIES: dict[str, Callable[[], gp.Story]] = {
    "one_night": gp.one_night_story,
    "corrections": gp.corrections_story,
    "conflict_birth": partial(gp.conflict_story, ("J", "K")),
    "conflict_national": partial(gp.conflict_story, ("M", "N")),
}


@pytest.fixture(autouse=True)
def _site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_CHARTNO_RULE", gp.CHART_RULE)
    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    monkeypatch.setenv("TB_TZ", kit.TZ)
    monkeypatch.setenv("TB_SITE_ID", kit.SITE)


def test_every_source_kind_has_a_road() -> None:
    """The product's source kinds, read from its code, each have a road here: a new connector fails this test until
    the cross-path test drives it."""
    kinds = kit.product_source_kinds()
    assert {"csv", "cgrd_sql", "ssmix2", "fhir_bulk"} <= kinds, kinds  # the reader still reads the product
    covered = {k for road in kit.ROADS for k in road.kinds}
    assert kinds <= covered, f"source kinds with no road in the cross-path test: {sorted(kinds - covered)}"


#: every road with every story its input can say (a road's ``cannot`` names the stories its source format has no way
#: to write, and why), in every order
CASES = [(r.name, s, o) for r in kit.ROADS for s in STORIES if s not in r.cannot for o in gp.ORDERS]


@pytest.mark.parametrize(("road", "story", "order"), CASES)
def test_cross_path(road: str, story: str, order: str, tmp_path: Path, db_url: str) -> None:
    d = kit.drive(kit.ROAD[road], STORIES[story](), order, tmp_path, db_url, rebuild=(story == "corrections"))
    findings = kit.judge(d)
    assert not findings, f"{road} / {story} / {order}: {len(findings)} findings\n" + kit.summary(findings)
