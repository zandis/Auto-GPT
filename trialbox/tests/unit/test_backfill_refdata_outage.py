"""NEW-B-19 (D-660): a first load that met an outage of the reference data is held, not published.

A night is not held for an outage (D-530): its rows are read again (D-538). The history a first load brings is
read once. Published without its mapped codes it would stay so, and the first delta night would then write a clean
count over the only place that said it (the finding of D-538's review)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from adapter.backfill import backfill
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import UNMAPPED_CODES
from tb_common import refdata

from tests.unit.test_backfill import SNAP, _cfg
from tests.unit.test_backfill_completeness import _feed, _rows, _write

I9, I10 = "http://hl7.org/fhir/sid/icd-9-cm", "http://hl7.org/fhir/sid/icd-10-cm"


def _icd9_feed(tmp_path: Path) -> Path:
    """The synthetic site's feed with three diagnoses keyed in ICD-9-CM (the mapping asks the reference data)."""
    feed = _feed(tmp_path)
    fields, rows = _rows(feed / "diagnosis.csv")
    for r in rows:
        r["diag_code_system"] = ""
    for r in rows[:3]:
        r["icd10"], r["diag_code_system"] = "042", "icd9cm"
    _write(feed / "diagnosis.csv", [*fields, "diag_code_system"], rows)
    return feed


def _refdata(monkeypatch: pytest.MonkeyPatch, up: bool) -> None:
    def ask(system: str, code: str, url: str | None = None) -> list[dict[str, Any]] | None:
        if not up:
            return None
        return [{"target_system": I10, "target_code": "B20", "relation": "equivalent"}] if code == "042" else []

    monkeypatch.setattr(refdata, "map_targets_or_none", ask)


def _mapped(lake_dir: Path) -> int:
    """Diagnoses that hold the ICD-9-CM code AND its ICD-10-CM one."""
    n = 0
    for r in read_type(snapshot_dir(lake_dir, SNAP), "Condition"):
        codes = {(c.get("system"), c.get("code")) for c in r["code"]["coding"]}
        n += (I9, "042") in codes and (I10, "B20") in codes
    return n


def test_a_first_load_that_met_an_outage_is_held_and_nothing_is_published(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = _icd9_feed(tmp_path)
    cfg = _cfg(tmp_path, "lake")
    _refdata(monkeypatch, up=False)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "held" and not rep.published
    assert rep.errors == [
        "diagnosis: the reference data did not answer for 3 rows (map:icd9cm->icd10cm): the history would be "
        "published without their mapped codes and is read only once. Run the back-fill again when the reference "
        "data answers (D-660)"
    ]
    assert "042" not in " ".join(rep.errors).replace("icd9cm", "")  # a table, a map and a count; never a code
    assert not snapshot_dir(cfg.lake_dir, SNAP).exists()  # nothing of the history reached the lake


def test_the_held_load_run_again_reads_the_source_again_and_maps_the_history(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kept spool is of the same source and mapping, and holds the rows without their codes: run again it must
    not be reused (it would be held for ever), and it must not be published as it is."""
    feed = _icd9_feed(tmp_path)
    cfg = _cfg(tmp_path, "lake")
    _refdata(monkeypatch, up=False)
    assert backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False).state == "held"
    _refdata(monkeypatch, up=True)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "published" and not rep.spool_reused, rep.errors
    assert _mapped(cfg.lake_dir) == 3
    said = snapshot_dir(cfg.lake_dir, SNAP) / UNMAPPED_CODES
    assert not said.exists() or "unavailable" not in said.read_text(encoding="utf-8")


def _count_reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    from adapter import backfill as bf

    reads: list[int] = []
    real = bf._spool

    def spool(*a: Any, **kw: Any) -> Any:
        reads.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(bf, "_spool", spool)
    return reads


def test_an_outage_that_lasts_holds_again_and_reads_the_source_once_per_run(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = _icd9_feed(tmp_path)
    cfg = _cfg(tmp_path, "lake")
    _refdata(monkeypatch, up=False)
    reads = _count_reads(monkeypatch)
    backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "held" and not rep.spool_reused and len(rep.errors) == 1
    assert len(reads) == 2  # once per run, never twice in one


def test_a_missing_table_and_an_outage_together_read_the_source_once_and_say_both(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    feed = _icd9_feed(tmp_path)
    kept = tmp_path / "lab.csv.kept"
    (feed / "lab.csv").rename(kept)
    cfg = dataclasses.replace(_cfg(tmp_path, "lake"), first_night_all_tables=True)
    _refdata(monkeypatch, up=False)
    reads = _count_reads(monkeypatch)
    backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "held" and len(reads) == 2
    assert any(e.startswith("lab: table missing") for e in rep.errors)
    assert any(e.startswith("diagnosis: the reference data did not answer for 3 rows") for e in rep.errors)
    kept.rename(feed / "lab.csv")
    _refdata(monkeypatch, up=True)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "published" and len(reads) == 3 and _mapped(cfg.lake_dir) == 3, rep.errors


def test_newest_years_first_publishes_nothing_of_a_load_that_met_an_outage(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``first_years`` the newest years are served before the rest is sorted: not when the load is held."""
    feed = _icd9_feed(tmp_path)
    cfg = _cfg(tmp_path, "lake")
    _refdata(monkeypatch, up=False)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False, first_years=1)
    assert rep.state == "held" and not rep.published and not snapshot_dir(cfg.lake_dir, SNAP).exists()


def test_a_load_stopped_during_an_outage_and_started_again_is_not_published_from_its_spool(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interrupt test: the load is stopped after its first year (a kill), with the spool of the outage kept.
    Started again with the reference data answering, it reads the source again and publishes the mapped history."""
    from adapter.backfill import BackfillStop

    def stop(bucket: str) -> None:
        raise BackfillStop(bucket)

    feed = _icd9_feed(tmp_path)
    cfg = _cfg(tmp_path, "lake")
    _refdata(monkeypatch, up=False)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False, first_years=1,
                   on_bucket=stop)  # fmt: skip
    assert rep.state == "running" and not rep.published and not snapshot_dir(cfg.lake_dir, SNAP).exists()
    _refdata(monkeypatch, up=True)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False, first_years=1)
    assert rep.state == "published" and not rep.spool_reused and _mapped(cfg.lake_dir) == 3, rep.errors


def test_a_code_no_look_up_knows_is_not_an_outage(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The reference data answered "no entry": counted (D-580), published. Only "could not be asked" holds."""
    feed = _icd9_feed(tmp_path)
    fields, rows = _rows(feed / "diagnosis.csv")
    for r in rows[:3]:
        r["icd10"] = "7140"
    _write(feed / "diagnosis.csv", fields, rows)
    cfg = _cfg(tmp_path, "lake")
    _refdata(monkeypatch, up=True)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "published", rep.errors
    codes = json.loads((snapshot_dir(cfg.lake_dir, SNAP) / UNMAPPED_CODES).read_text(encoding="utf-8"))
    assert codes["diagnosis"] == {"map:icd9cm->icd10cm": {"7140": 3}}
