"""NEW-B-24 (D-665): a load that runs before the reference pack is loaded does not leave a lasting gap.

A finding of D-660's review. With no pack loaded the reference data answers "no entry" for every code: counted,
published, and never asked again (a delta night reads only rows that changed; a first load reads its history once).
A map the mapping names that is not loaded is now treated as a map that could not be asked: the rows that needed it
are counted so, a night reads the table whole on the next delta night (D-538), and a first load is held (D-660)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from adapter.backfill import backfill
from adapter.ndjson import snapshot_dir
from adapter.pipeline import UNMAPPED_CODES, reference_maps
from tb_common import refdata

from tests.unit.test_backfill import SNAP
from tests.unit.test_backfill import _cfg as _bf_cfg
from tests.unit.test_backfill_completeness import _feed as _site_feed
from tests.unit.test_backfill_refdata_outage import _icd9_feed, _mapped
from tests.unit.test_full_reread_after_refdata_outage import DOWN, _codes, _diag, _feed, _night, _site

I9, I10 = "http://hl7.org/fhir/sid/icd-9-cm", "http://hl7.org/fhir/sid/icd-10-cm"


def _pack(monkeypatch: pytest.MonkeyPatch, loaded: bool | None) -> list[tuple[str, str]]:
    """The reference data with the ICD-9-CM map loaded, not loaded (``False``), or not reachable (``None``). With no
    pack every question about a code is answered "no entry", as the real store answers."""
    asked: list[tuple[str, str]] = []

    def targets(system: str, code: str, url: str | None = None) -> list[dict[str, Any]] | None:
        asked.append((system, code))
        if loaded is None:
            return None
        if not loaded:
            return []
        return [{"target_system": I10, "target_code": {"042": "B20", "585.3": "N18.3"}[code], "relation": "equivalent"}]

    monkeypatch.setattr(refdata, "map_targets_or_none", targets)
    monkeypatch.setattr(refdata, "has_map_or_none", lambda src, tgt, url=None: loaded)
    return asked


def test_a_night_before_the_pack_is_loaded_counts_its_rows_as_not_asked_and_the_next_night_maps_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = _site(tmp_path)
    feed = _feed(tmp_path / "feed", [_diag("D1", "042", "2026-09-30"), _diag("D2", "585.3", "2026-09-30")])
    asked = _pack(monkeypatch, loaded=False)
    with caplog.at_level(logging.WARNING):
        assert _night(cfg, feed, "2026-10-01").passed  # not held (D-530)
    said = json.loads((snapshot_dir(cfg.lake_dir, "2026-10-01") / UNMAPPED_CODES).read_text())
    assert said == {"diagnosis": {DOWN: {"042": 1, "585.3": 1}}}  # "could not be asked", not "no entry"
    assert asked == [(I9, "042")]  # the first "no entry" asks whether the map is there; after that no code is asked
    assert (
        f"the reference map from {I9} to {I10} is not loaded: the rows that need it are counted as not asked"
        in caplog.text
    )
    assert "042" not in caplog.text
    # the pack is loaded; the next night is a delta night and no diagnosis changed at the source
    _pack(monkeypatch, loaded=True)
    assert _night(cfg, feed, "2026-10-02", since="2026-10-01").passed
    assert _codes(cfg, "2026-10-02") == [["10:B20", "9:042"], ["10:N18.3", "9:585.3"]]


def test_a_first_load_before_the_pack_is_loaded_is_held_when_rows_need_the_map(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = _icd9_feed(tmp_path)
    cfg = _bf_cfg(tmp_path, "lake")
    _pack(monkeypatch, loaded=False)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "held" and not rep.published
    assert rep.errors and rep.errors[0].startswith("diagnosis: the reference data did not answer for 3 rows")
    _pack(monkeypatch, loaded=True)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "published" and _mapped(cfg.lake_dir) == 3, rep.errors


def test_a_first_load_whose_rows_do_not_need_the_map_is_not_held_for_a_pack_it_does_not_use(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mapping names the map for the sites that have such rows. A site without them must not be told to load a
    pack first."""
    feed = _site_feed(tmp_path)
    cfg = _bf_cfg(tmp_path, "lake")
    _pack(monkeypatch, loaded=False)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "published", rep.errors


def test_a_map_that_is_loaded_or_cannot_be_asked_about_is_asked_code_by_code_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.mapping.engine import Mapping

    mapping = Mapping.load(_site(tmp_path).mapping_path)
    assert mapping.concept_maps() == [(I9, I10)]
    for loaded in (True, None):
        asked = _pack(monkeypatch, loaded)
        ask = reference_maps(mapping, None)
        got = ask(I9, "042")
        assert asked == [(I9, "042")] and (got is None) == (loaded is None)
    asked = _pack(monkeypatch, loaded=False)
    monkeypatch.setenv("TB_DB_URL", "postgresql://box/db")  # a box: its reference data is its own database
    ask = reference_maps(mapping, None)
    assert ask(I9, "042") is None and ask(I9, "585.3") is None  # not loaded: "could not be asked"
    assert asked == [(I9, "042")]  # asked once, then known
    assert ask("http://loinc.org", "1-2") == [] and asked[-1] == ("http://loinc.org", "1-2")  # no map of the mapping's
    monkeypatch.delenv("TB_DB_URL")
    ask = reference_maps(mapping, None)
    assert ask(I9, "042") == []  # no database configured: nothing could be loaded; "no entry", as before (D-593)


# ------------------------------------------------------------------------------------------------ review fixes
def test_a_no_entry_that_cannot_be_checked_is_not_taken_for_an_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store answers "no entry", and the question "is the map loaded at all" then fails (the database went
    between two queries). Taken as "no entry" the code would be published so and never asked again: the row is
    counted as not asked, and the next code asks again."""
    from adapter.mapping.engine import Mapping

    mapping = Mapping.load(_site(tmp_path).mapping_path)
    answers: list[bool | None] = [None, False]
    monkeypatch.setenv("TB_DB_URL", "postgresql://box/db")
    monkeypatch.setattr(refdata, "map_targets_or_none", lambda system, code, url=None: [])
    monkeypatch.setattr(refdata, "has_map_or_none", lambda src, tgt, url=None: answers.pop(0))
    ask = reference_maps(mapping, None)
    assert ask(I9, "042") is None  # could not be checked: not asked, never "no entry"
    assert ask(I9, "585.3") is None and answers == []  # asked again; now known: not loaded
    assert ask(I9, "7140") is None


def test_a_first_load_held_for_a_pack_that_is_not_loaded_says_to_load_it(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = _icd9_feed(tmp_path)
    cfg = _bf_cfg(tmp_path, "lake")
    _pack(monkeypatch, loaded=False)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "held"
    assert rep.errors == [
        "diagnosis: the reference data did not answer for 3 rows (map:icd9cm->icd10cm): the history would be "
        f"published without their mapped codes and is read only once. The reference map from {I9} to {I10} is "
        "not loaded: load the reference pack, then run the back-fill again (D-665)"
    ]
    again = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert again.state == "held" and again.errors == rep.errors  # still not loaded: said again, the source read again
