# ruff: noqa: F811 - the feed fixture is imported from test_omop_core and taken by name
"""T-201 (D-426, DATA-011): a clinical conflict stays open when one source goes silent and is withdrawn only when the
sources agree again; ``omop.conflicts`` lists it with the pseudonym and the claims, counts it per item, and settles it
with a claimed value or "unknown" and a reason (anything else is refused); the lake reads the chosen value."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_omop_core import _feed, _load, _site, db, feed_dir  # noqa: F401 - fixtures used by name


def _open(db: Any) -> list[Any]:
    from omop import conflicts

    return conflicts.listing(db)


def test_a_source_that_goes_silent_keeps_the_conflict_open(
    feed_dir: Path, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omop.export import export_rows
    from tb_common import feedguard

    feed, site = _feed(feed_dir), _site(feed_dir)
    _load(db, feed, site)
    first = _open(db)
    assert len(first) == 8
    c = first[0]
    # the site's sheet no longer sends the patient: before T-201 this withdrew the conflict and the feed's value stood
    quiet = copy.deepcopy(site)
    quiet["Patient"] = [p for p in quiet["Patient"] if p["id"] != c.pid]
    _load(db, feed, quiet, snap="2026-10-05")
    assert db.fetchval("SELECT state FROM tb_conflict WHERE conflict_id = ?", (c.conflict_id,)) == "open"
    assert {r["pid"]: r for r in export_rows(db)["patient"]}[c.pid]["birth_date"] is None  # still unknown
    # the hospital feed goes silent for every patient (the empty-patient night of DATA-011): nothing is withdrawn
    empty = copy.deepcopy(feed)
    empty["Patient"] = []
    monkeypatch.setenv(feedguard.OVERRIDE_ENV, "2026-10-06: the test's empty-patient night")
    _load(db, empty, site, snap="2026-10-06")
    assert len(_open(db)) == 8
    # the sources agree again: withdrawn
    agree = copy.deepcopy(site)
    agree["Patient"] = [{**p, "birthDate": c.values[0]} if p["id"] == c.pid else p for p in agree["Patient"]]
    _load(db, feed, agree, snap="2026-10-07")
    assert db.fetchval("SELECT state FROM tb_conflict WHERE conflict_id = ?", (c.conflict_id,)) == "withdrawn"
    assert len(_open(db)) == 7


def test_listing_counts_and_resolution(feed_dir: Path, db: Any) -> None:
    from omop import conflicts
    from omop.export import export_rows
    from omop.schema import OmopError

    feed, site = _feed(feed_dir), _site(feed_dir)
    _load(db, feed, site)
    rows = conflicts.listing(db)
    assert conflicts.counts(db) == {"birth_date": 8, "sex": 0, "deceased_date": 0}
    a, b = rows[0], rows[1]
    assert a.kind == "source_vs_source" and a.item == "birth_date" and len(a.values) == 2
    assert [cl["source"][0] for cl in a.claims] == ["feed", "site"]  # the hospital's value first
    with pytest.raises(OmopError):
        conflicts.resolve(db, a.conflict_id, "1900-01-01", by="console:stw", reason="typed")  # nobody claimed it
    with pytest.raises(OmopError):
        conflicts.resolve(db, a.conflict_id, a.values[1], by="console:stw", reason=" ")  # no reason
    got = conflicts.resolve(db, a.conflict_id, a.values[1], by="console:stw", reason="the sheet holds the chart")
    assert got.state == "resolved" and got.resolution == "value" and got.resolved_value == a.values[1]
    assert got.authority == "steward" and got.resolved_by == "console:stw" and got.resolved_at is not None
    unk = conflicts.resolve(db, b.conflict_id, conflicts.UNKNOWN, by="console:stw", reason="ask the ward")
    assert unk.resolution == "unknown" and unk.resolved_value is None
    with pytest.raises(OmopError):
        conflicts.resolve(db, a.conflict_id, a.values[0], by="console:stw", reason="again")  # settled already
    lake = {r["pid"]: r for r in export_rows(db)["patient"]}
    assert lake[a.pid]["birth_date"].isoformat() == a.values[1] and lake[b.pid]["birth_date"] is None
    assert conflicts.counts(db)["birth_date"] == 6
    trail = conflicts.listing(db, everything=True)
    assert len(trail) == 8 and {r.state for r in trail} == {"open", "resolved"}
    _load(db, feed, site)  # the same disagreement next night does not reopen a resolved conflict
    assert conflicts.counts(db)["birth_date"] == 6
