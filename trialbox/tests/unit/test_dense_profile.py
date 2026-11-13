"""T-687, the dense profile (plan v7, wave 1; PERF-002): about 500 records and 40 notes per patient.

The scale gate's hospital was the generator's own: about 30 records and under 2 notes per patient. A hospital's
chart is an order of magnitude thicker, and the parts of the night that are sized by records (the merge, the
Parquet build, the note index) never met that. ``densify`` thickens a generated feed: every clinical row again and
again, each copy a week earlier under its own key, until the feed has the profile's records and notes per
patient. Synthetic patients only."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import pytest
from tb_testkit.scale import DENSE_NOTES, DENSE_RECORDS, RECORD_TABLES, densify

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
N = 25  # patients of the fixture this test thickens


def _rows(folder: Path, name: str) -> list[dict[str, str]]:
    with (folder / f"{name}.csv").open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def thin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The first ``N`` patients of site A, every table."""
    out = tmp_path_factory.mktemp("thin")
    keep = {r["mrn"] for r in _rows(SITE_A, "patient")[:N]}
    for src in sorted(SITE_A.glob("*.csv")):
        with src.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = list(reader.fieldnames or [])
            rows = [r for r in reader if "mrn" not in r or r["mrn"] in keep]
        with (out / src.name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    return out


@pytest.fixture(scope="module")
def dense(thin: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, object]]:
    out = tmp_path_factory.mktemp("dense")
    return out, densify(thin, out)


@pytest.mark.nodb
def test_the_dense_feed_has_the_profiles_records_and_notes_per_patient(dense: tuple[Path, dict[str, object]]) -> None:
    out, facts = dense
    patients = len(_rows(out, "patient"))
    records = sum(len(_rows(out, t)) for t in RECORD_TABLES)
    notes = len(_rows(out, "note"))
    assert patients == N
    # the target is met from above and by less than one more copy of the thin feed
    assert DENSE_RECORDS <= records / patients < DENSE_RECORDS * 1.1, records / patients
    assert DENSE_NOTES <= notes / patients < DENSE_NOTES * 1.1, notes / patients
    assert facts["records_per_patient"] == round(records / patients, 1)
    assert facts["notes_per_patient"] == round(notes / patients, 1)


@pytest.mark.nodb
def test_every_copy_has_its_own_key_a_known_patient_a_known_encounter_and_a_day_the_patient_lived(
    thin: Path, dense: tuple[Path, dict[str, object]]
) -> None:
    out, _ = dense
    born = {r["mrn"]: date.fromisoformat(r["birth_date"]) for r in _rows(out, "patient")}
    encounters = {r["enc_no"] for r in _rows(out, "encounter")}
    for table in (*RECORD_TABLES, "note"):
        rows = _rows(out, table)
        if not rows:  # a table none of these patients has a row in
            assert not _rows(thin, table), table
            continue
        key = next(iter(rows[0]))
        assert len({r[key] for r in rows}) == len(rows), table  # no key twice
        for r in rows:
            assert r["mrn"] in born, (table, r[key])
            if r.get("enc_no"):
                assert r["enc_no"] in encounters, (table, r[key], r["enc_no"])
            for col, v in r.items():
                if v and (col.endswith("_date") or col.endswith("_datetime")):
                    assert datetime.fromisoformat(v).date() >= born[r["mrn"]], (table, r[key], col, v)
    # the tables that are not the chart are as they were: people, staff, consent, bookings, claims
    for table in ("patient", "practitioner", "registry", "appointment", "claim"):
        assert _rows(out, table) == _rows(thin, table), table
    # every original row is still there, unchanged
    for table in (*RECORD_TABLES, "note"):
        if not _rows(thin, table):
            continue
        key = next(iter(_rows(thin, table)[0]))
        got = {r[key]: r for r in _rows(out, table)}
        assert all(got[r[key]] == r for r in _rows(thin, table)), table


@pytest.mark.nodb
def test_the_same_feed_twice_is_the_same_bytes_and_copies_keep_their_weekday(
    thin: Path, dense: tuple[Path, dict[str, object]], tmp_path: Path
) -> None:
    out, _ = dense
    densify(thin, tmp_path / "again")
    for f in sorted(out.glob("*.csv")):
        assert f.read_bytes() == (tmp_path / "again" / f.name).read_bytes(), f.name
    days = Counter()
    for r in _rows(out, "encounter"):
        days[datetime.fromisoformat(r["visit_datetime"]).weekday()] += 1
    thin_days = {datetime.fromisoformat(r["visit_datetime"]).weekday() for r in _rows(thin, "encounter")}
    assert set(days) == thin_days  # a copy is whole weeks earlier: a clinic day stays a clinic day


def test_the_dense_feed_is_a_night_the_adapter_takes(dense: tuple[Path, dict[str, object]], tmp_path: Path) -> None:
    from adapter.ndjson import read_type, snapshot_dir
    from adapter.pipeline import run_ingest

    from tests.unit.test_dataflow_lake_p0 import _cfg

    out, _ = dense
    cfg = _cfg(tmp_path)
    rep = run_ingest(cfg, "csv", str(out), snapshot="2026-10-05", load_fhir=False, validate=False)
    assert rep.passed and not rep.held, rep.errors
    folder = snapshot_dir(cfg.lake_dir, "2026-10-05")
    assert len(list(read_type(folder, "Patient"))) == N
    assert len(list(read_type(folder, "Encounter"))) == len(_rows(out, "encounter"))
    assert len(list(read_type(folder, "DocumentReference"))) + len(list(read_type(folder, "Composition"))) > 0
