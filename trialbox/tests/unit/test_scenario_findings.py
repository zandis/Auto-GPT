"""Findings of the scenario-matrix run of 2026-11-09 (D-141), fixed in D-142's follow-up; each test failed before
its fix. The run's own probes are in ``tools/scenarios.py``; these are the small repros.

* XL-02: SCREEN on the hospital's own space after a site list was published spilled DuckDB temp files until the
  disk was full. The site's facts gave a second ``Patient`` for every pseudonym the feed already had, and each
  criterion of a compiled ruleset joins ``base`` (patients x index dates) again, so one duplicated patient became
  2^(criteria + 1) rows.
* FHIR-01: on the FHIR bulk path SCREEN had no one in scope: references to a Practitioner were hashed and the
  Practitioner's own id was kept, so no appointment found its doctor.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from embed_service.embedder import HashEmbedder
from lake.store import Lake, LakeLimitError
from tb_common.ruleset import Ruleset

ROOT = Path(__file__).resolve().parents[2]
SNAP = "2026-10-31"


def _ndjson(folder: Path, by_type: dict[str, list[dict[str, Any]]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for rtype, items in by_type.items():
        (folder / f"{rtype}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in items), "utf-8")
    return folder


def _hospital(n: int) -> dict[str, list[dict[str, Any]]]:
    pts, cond, enc = [], [], []
    for i in range(n):
        pid = f"p{i:04d}"
        pts.append({"resourceType": "Patient", "id": pid, "birthDate": f"19{50 + i % 40}-03-01", "gender": "male"})
        cond.append(
            {
                "resourceType": "Condition",
                "id": f"c{i}",
                "subject": {"reference": f"Patient/{pid}"},
                "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "M10.9"}]},
                "onsetDateTime": "2025-06-01",
            }
        )
        enc.append(
            {
                "resourceType": "Encounter",
                "id": f"e{i}",
                "status": "finished",
                "subject": {"reference": f"Patient/{pid}"},
                "period": {"start": "2026-09-01T09:00:00+09:00"},
                "class": {"code": "AMB"},
            }
        )
    return {"Patient": pts, "Condition": cond, "Encounter": enc}


def _site(n: int) -> dict[str, list[dict[str, Any]]]:
    """What ``sitesetup.publish`` gives for a PI's sheet over the same patients: a Patient per pseudonym (one of them
    with another sex: a disagreement is unknown, never a guess) and the sheet's facts."""
    pts = [
        {"resourceType": "Patient", "id": f"p{i:04d}", "birthDate": f"19{50 + i % 40}-03-01"}
        | ({"gender": "female"} if i == 0 else {})
        for i in range(n)
    ]
    return {"Patient": pts}


def test_xl02_published_site_facts_never_duplicate_a_patient(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    n = 40
    lake = Lake(tmp_path / "lake", tz="Asia/Tokyo")
    lake.put_site(_site(n))
    lake.rebuild(SNAP, HashEmbedder(), ndjson_dir=_ndjson(tmp_path / "feed", _hospital(n)))
    con = lake.connect()
    try:
        rows = con.execute("SELECT pid, birth_date, sex FROM patient ORDER BY pid").fetchall()
    finally:
        con.close()
    assert len(rows) == n  # one row per pseudonym
    assert rows[0][2] is None and rows[1][2] == "male"  # feed and sheet disagree: unknown; agree: kept
    # the GZQO SCREEN query (twelve month ends, as the cascade asks) at a size that filled the disk before the fix:
    # it now returns one row per patient and index date, inside a small spill budget
    monkeypatch.setenv("TB_LAKE_MEMORY_LIMIT", "512MB")
    monkeypatch.setenv("TB_LAKE_MAX_TEMP", "256MB")
    rs = Ruleset.load(ROOT / "rulesets" / "GZQO")
    idx = [date(2025 + (m + 10) // 12, (m + 10) % 12 + 1, 1).isoformat() for m in range(12)]
    t = time.perf_counter()
    out = lake.query(rs.sql, [idx, None], timeout_s=120)
    assert out.num_rows == n * len(idx)
    assert time.perf_counter() - t < 60


def test_xl02_a_query_over_its_spill_budget_fails_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake = Lake(tmp_path / "lake", tz="Asia/Tokyo")
    lake.rebuild(SNAP, HashEmbedder(), ndjson_dir=_ndjson(tmp_path / "feed", _hospital(300)))
    monkeypatch.setenv("TB_LAKE_MEMORY_LIMIT", "64MB")
    monkeypatch.setenv("TB_LAKE_MAX_TEMP", "32MB")
    monkeypatch.setenv("TB_LAKE_TEMP_DIR", str(tmp_path / "spill"))
    sql = (
        "SELECT count(*) FROM (SELECT DISTINCT a.eid || b.eid || c.eid AS k FROM encounter a, encounter b, encounter c)"
    )
    with pytest.raises(LakeLimitError) as e:
        lake.query(sql, timeout_s=120)
    assert str(e.value).startswith("LAKE-LIMIT:") and "TB_LAKE_MAX_TEMP" in str(e.value)
    assert (tmp_path / "spill").is_dir()  # the spill went where the configuration says
    assert not any(p.is_file() for p in (tmp_path / "spill").rglob("*"))  # and nothing was left behind


def test_fhir01_bulk_pseudonyms_map_ids_and_references_the_same_way() -> None:
    from adapter.pipeline import pseudonymise_bulk
    from lake.flatten import Flattener
    from tb_common.crypto import pid_for_mrn

    key = b"k" * 32
    export: list[dict[str, Any]] = [
        {"resourceType": "Practitioner", "id": "D001", "name": [{"text": "Dr A"}]},
        {"resourceType": "Patient", "id": "00012345", "name": [{"text": "X"}], "identifier": [{"value": "00012345"}]},
        {
            "resourceType": "Appointment",
            "id": "A1",
            "status": "booked",
            "start": "2026-11-12T09:00:00+09:00",
            "participant": [
                {"actor": {"reference": "Patient/00012345"}},
                {"actor": {"reference": "Practitioner/D001"}},
            ],
        },
        {
            "resourceType": "Encounter",
            "id": "E1",
            "subject": {"reference": "Patient/00012345"},
            "participant": [{"individual": {"reference": "Practitioner/D001"}}],
            "period": {"start": "2026-10-01T09:00:00+09:00"},
        },
    ]
    by: dict[str, list[dict[str, Any]]] = {}
    for r in pseudonymise_bulk(iter(export), key):
        by.setdefault(r["resourceType"], []).append(r)
    rows = Flattener("Asia/Tokyo").flatten(by)
    staff = {r["practitioner_id"] for r in rows["practitioner"]}
    assert staff == {"D001"}  # the hospital's staff id, as the CSV and SS-MIX2 paths key it (the study scope's ids)
    assert [r["practitioner_id"] for r in rows["appointment"]] == ["D001"]
    assert [r["practitioner_id"] for r in rows["encounter"]] == ["D001"]
    pid = pid_for_mrn(key, "00012345")
    assert [r["pid"] for r in rows["patient"]] == [pid] == [r["pid"] for r in rows["appointment"]]
    assert "00012345" not in json.dumps(by)  # the chart number is gone from ids, references and identifiers
