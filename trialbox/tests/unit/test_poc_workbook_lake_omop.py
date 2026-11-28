"""PoC workbook door (lane H item 1), the lake and OMOP half.

* A birth of year and month reaches the lake as ``birth_ym`` with ``birth_date`` NULL (no day is invented, the patient
  is kept) and OMOP ``person`` as year and month with day and birth datetime NULL.
* A finding's text reaches the lake's ``observation.value_text`` and OMOP ``observation`` (``value_as_string``,
  ``value_source_value``, the finding code as ``observation_source_value``); numeric observations and demographic
  facts keep their route.
* A lake built before these columns still loads (the columns read as unknown).
* The finding text is patient text: it is in no log line and in no night report file.

All data is synthetic.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import duckdb
import pytest
from embed_service.embedder import HashEmbedder
from lake.flatten import DEMOGRAPHIC
from lake.source import lake_rows
from lake.store import LAKE_SCHEMA_VERSION, Lake

TEXT = "合成の例: 両側の海馬に軽度の萎縮"
SNAP = "2026-11-01"


def _patient(birth: str) -> dict[str, Any]:
    return {"resourceType": "Patient", "id": "P1", "birthDate": birth, "gender": "male"}


def _obs(oid: str, code: str, **value: Any) -> dict[str, Any]:
    return {
        "resourceType": "Observation", "id": oid, "status": "final",
        "subject": {"reference": "Patient/P1"}, "effectiveDateTime": "2026-03-02",
        "code": {"coding": [{"system": "urn:test:finding", "code": code}]}, **value,
    }  # fmt: skip


FEED: dict[str, list[dict[str, Any]]] = {
    "Patient": [_patient("1948-05")],
    "Observation": [
        _obs("o-find", "FIND-HIPPO-ATROPHY", valueString=TEXT),
        _obs("o-num", "MMSE", valueQuantity={"value": 24, "code": "{score}"}),
        {
            **_obs("o-demo", "sex"),
            "code": {"coding": [{"system": DEMOGRAPHIC, "code": "sex"}]},
            "valueString": "male",
        },
    ],
}


def _rows() -> dict[str, list[dict[str, Any]]]:
    return lake_rows(FEED, {}, tz="Asia/Tokyo", snapshot=SNAP, source="legacy")


def test_a_birth_of_year_and_month_is_kept_without_a_day() -> None:
    (p,) = _rows()["patient"]
    assert p["birth_date"] is None and p["birth_ym"] == "1948-05"


def test_a_whole_birth_date_keeps_its_route() -> None:
    feed = {"Patient": [_patient("1948-05-15")]}
    (p,) = lake_rows(feed, {}, tz="Asia/Tokyo", snapshot=SNAP, source="legacy")["patient"]
    assert str(p["birth_date"]) == "1948-05-15" and p["birth_ym"] is None


def test_a_finding_text_is_kept_and_a_number_is_not_text() -> None:
    by = {r["code"]: r for r in _rows()["observation"]}
    assert by["FIND-HIPPO-ATROPHY"]["value_text"] == TEXT and by["FIND-HIPPO-ATROPHY"]["value_num"] is None
    assert by["MMSE"]["value_text"] is None and by["MMSE"]["value_num"] == 24.0


def test_an_older_lake_without_the_new_columns_still_loads(tmp_path: Path) -> None:
    nd = tmp_path / "nd"
    nd.mkdir()
    for rtype, items in FEED.items():
        (nd / f"{rtype}.ndjson").write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n")
    lake = Lake(tmp_path / "lake")
    lake.rebuild(SNAP, HashEmbedder(), nd)
    con = duckdb.connect(str(lake.db_path()))
    con.execute("ALTER TABLE patient DROP COLUMN birth_ym")
    con.execute("ALTER TABLE observation DROP COLUMN value_text")
    con.execute("UPDATE lake_meta SET schema_version = 4")
    con.close()
    read = lake.connect()
    try:
        assert read.execute("SELECT birth_ym FROM patient").fetchall() == [(None,)]
        assert read.execute("SELECT count(*) FROM observation WHERE value_text IS NOT NULL").fetchone() == (0,)
    finally:
        read.close()
    assert LAKE_SCHEMA_VERSION >= 5


def test_omop_holds_year_and_month_and_routes_a_finding_to_observation(db_url: str) -> None:
    from omop import schema
    from omop.load import load_batch

    db = schema.connect(db_url)
    try:
        load_batch(db, "feed", SNAP, FEED, tz="Asia/Tokyo")
        assert db.fetchall("SELECT year_of_birth, month_of_birth, day_of_birth, birth_datetime FROM person") == [
            (1948, 5, None, None)
        ]
        obs = db.fetchall("SELECT observation_source_value, value_as_string, value_source_value FROM observation")
        assert ("FIND-HIPPO-ATROPHY", TEXT, TEXT) in [tuple(r) for r in obs]
        meas = [r[0] for r in db.fetchall("SELECT measurement_source_value FROM measurement")]
        assert meas == ["MMSE"]  # a number stays a measurement; the finding is not one
        assert any(r[0] == "sex" for r in obs)  # a demographic fact keeps its route
    finally:
        db.close()


def test_omop_export_returns_the_birth_month_and_the_finding_text(db_url: str) -> None:
    from omop import schema
    from omop.load import load_batch

    db = schema.connect(db_url)
    try:
        load_batch(db, "feed", SNAP, FEED, tz="Asia/Tokyo")
        from omop.export import export_rows

        got = export_rows(db)
    finally:
        db.close()
    (p,) = got["patient"]
    assert p["birth_date"] is None and p["birth_ym"] == "1948-05"
    assert any(r["code"] == "FIND-HIPPO-ATROPHY" and r["value_text"] == TEXT for r in got["observation"])


def test_the_finding_text_is_in_no_log_line_and_no_report_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from adapter.pipeline import AdapterConfig, run_ingest

    from tests.unit import test_poc_workbook_door as door

    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(b"k" * 32)
    cfg = AdapterConfig(
        lake_dir=tmp_path / "lake", secrets_dir=sec, mapping_path=door.MAPPING, site_id="T",
        audit_dir=tmp_path / "audit", tz="Asia/Tokyo",
    )  # fmt: skip
    with caplog.at_level(logging.DEBUG):
        run_ingest(cfg, "xlsx", str(door.TEMPLATE), snapshot=SNAP, load_fhir=False, rebuild_lake=False, validate=False)
    assert "海馬" not in caplog.text
    snap = tmp_path / "lake" / "ndjson" / SNAP
    reports = [p for p in snap.iterdir() if p.suffix == ".json"] + list((tmp_path / "audit").glob("*.jsonl"))
    assert reports and not [p.name for p in reports if "海馬" in p.read_text(encoding="utf-8")]
