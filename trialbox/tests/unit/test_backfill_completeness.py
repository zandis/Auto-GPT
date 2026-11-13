"""NEW-B-13 (D-535): the first load says what the night says about its tables and its codes.

The back-fill, a hospital's first load, wrote no completeness record and no count of unknown codes. So (a) the
night after it had no baseline: a table that lost half its rows passed (D-583 covers only "missing or empty");
(b) the first-night rule itself (every table of the mapping must be there with rows) was never asked of the load
that IS the first night; (c) the codes no look-up knows were counted nowhere until the first delta."""

from __future__ import annotations

import csv
import dataclasses
import json
import shutil
from pathlib import Path

from adapter.backfill import backfill
from adapter.ndjson import snapshot_dir
from adapter.pipeline import COMPLETENESS, UNMAPPED_CODES, run_ingest

from tests.unit.test_backfill import SITE_A, SNAP, _cfg

NEXT = "2026-11-11"


def _feed(tmp: Path, name: str = "feed") -> Path:
    dst = tmp / name
    shutil.copytree(SITE_A, dst, ignore=shutil.ignore_patterns("*.json", "*.sqlite"))
    return dst


def _rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.DictReader(fh)
        return list(r.fieldnames or []), list(r)


def _write(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_the_first_load_leaves_a_baseline_and_the_next_night_is_held_to_it(tmp_path: Path, db_url: str) -> None:
    cfg = _cfg(tmp_path, "lake")
    feed = _feed(tmp_path)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "published", rep.errors
    comp = json.loads((snapshot_dir(cfg.lake_dir, SNAP) / COMPLETENESS).read_text(encoding="utf-8"))
    fields, labs = _rows(feed / "lab.csv")
    assert comp["full"] is True and comp["problems"] == []
    assert comp["tables"]["lab"]["present"] is True and comp["reference"]["lab"] == len(labs)
    # the next night, a full load in which the lab table lost half its rows: held against the first load's count
    _write(feed / "lab.csv", fields, labs[: len(labs) // 2])
    night = run_ingest(cfg, "csv", str(feed), snapshot=NEXT, load_fhir=False, rebuild_lake=False, validate=False)
    assert night.held, night.errors
    assert any(f"against snapshot {SNAP}" in e and "lab: " in e and "fewer than the last good night" in e
               for e in night.errors or []), night.errors  # fmt: skip


def test_a_first_load_without_a_table_of_the_mapping_is_held_before_anything_is_published(
    tmp_path: Path, db_url: str
) -> None:
    feed = _feed(tmp_path)
    (feed / "lab.csv").unlink()
    cfg = dataclasses.replace(_cfg(tmp_path, "lake"), first_night_all_tables=True)  # as the product's entry sets it
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "held" and any(e.startswith("lab: table missing") for e in rep.errors), rep.errors
    assert not snapshot_dir(cfg.lake_dir, SNAP).exists() and rep.published == []
    # the site says it has no such table: the load goes through
    cfg = dataclasses.replace(cfg, lake_dir=tmp_path / "lake2", optional_tables=("lab",))
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "published", rep.errors


def test_the_first_load_counts_the_codes_no_look_up_knows(tmp_path: Path, db_url: str) -> None:
    feed = _feed(tmp_path)
    fields, labs = _rows(feed / "lab.csv")
    for r in labs[:7]:
        r["local_code"] = "ZZ9"
    _write(feed / "lab.csv", fields, labs)
    cfg = _cfg(tmp_path, "lake")
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "published", rep.errors
    folder = snapshot_dir(cfg.lake_dir, SNAP)
    codes = json.loads((folder / UNMAPPED_CODES).read_text(encoding="utf-8"))
    assert codes["lab"]["lab"]["ZZ9"] == 7
    comp = json.loads((folder / COMPLETENESS).read_text(encoding="utf-8"))
    assert comp["tables"]["lab"]["unmapped"]["lab"]["rows"] >= 7
    assert rep.unmapped["lab"] >= 7  # and the load's own report says it
    # a run started again (the spool is reused) says the same: the counts are kept with the spool
    again = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert again.spool_reused and again.unmapped == rep.unmapped


# ------------------------------------------------------------------------------------------- the review of NEW-B-13
def test_a_held_load_goes_through_once_the_missing_table_is_supplied(tmp_path: Path, db_url: str) -> None:
    """Review HIGH: the load was held for a missing table; the site puts the table into the folder and runs the
    load again. The kept spool (same source, same mapping) said "missing" for ever: the source is read again."""
    feed = _feed(tmp_path)
    kept = tmp_path / "lab.csv.kept"
    (feed / "lab.csv").rename(kept)
    cfg = dataclasses.replace(_cfg(tmp_path, "lake"), first_night_all_tables=True)
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "held" and any(e.startswith("lab: table missing") for e in rep.errors)
    kept.rename(feed / "lab.csv")
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "published" and not rep.spool_reused, rep.errors
    comp = json.loads((snapshot_dir(cfg.lake_dir, SNAP) / COMPLETENESS).read_text(encoding="utf-8"))
    assert comp["tables"]["lab"]["present"] is True and comp["reference"]["lab"] > 0


def test_a_spool_of_an_older_version_is_read_again_not_published_without_the_gate(tmp_path: Path, db_url: str) -> None:
    """Review MED: a load begun before this card kept a spool without table facts. Reusing it skipped the gate and
    wrote no baseline, silently."""
    feed = _feed(tmp_path)
    cfg = _cfg(tmp_path, "lake")
    assert backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False).state == "published"
    marker = cfg.lake_dir / "backfill" / SNAP / "spool" / "done.json"
    old = json.loads(marker.read_text(encoding="utf-8"))
    for k in ("tables", "unmapped_codes"):
        old.pop(k)
    marker.write_text(json.dumps(old), encoding="utf-8")  # as the version before D-535 wrote it
    (snapshot_dir(cfg.lake_dir, SNAP) / COMPLETENESS).unlink()
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "published" and not rep.spool_reused
    assert (snapshot_dir(cfg.lake_dir, SNAP) / COMPLETENESS).is_file()


def test_a_required_table_is_asked_of_the_first_load_too(tmp_path: Path, db_url: str) -> None:
    feed = _feed(tmp_path)
    (feed / "claim.csv").unlink()
    cfg = dataclasses.replace(_cfg(tmp_path, "lake"), required_tables=("claim",))
    rep = backfill(cfg, "csv", str(feed), snapshot=SNAP, validate=False, rebuild_lake=False)
    assert rep.state == "held" and any(e.startswith("claim: required table missing") for e in rep.errors), rep.errors
