"""T-724 (D-490), the adversarial review of #318 after T-723 (build without promote) met it on master.

MED-1: after a restore the generations' files are gone and their numbers started again at 1, so a job's recorded
"date.g1" could name other bytes. MED-2: a build without promote of the date that is served was served at once.
MED-3: the promotion took "whatever the date names", not the generation the publish built."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from embed_service.embedder import HashEmbedder
from lake.store import Lake

from tests.unit.test_snapshot_holds import NIGHT, TZ, _night
from tests.unit.test_t724_generations import _publish, _rows

LATER = "2026-10-05"


def _restored(lake_dir: Path, records: bool) -> None:
    """What a restore gives: the dates' own files; of ``db/gen`` only the records (the backup keeps them now), or
    nothing (a backup made before this card). No holds: they are the old box's."""
    gdir = lake_dir / "db" / "gen"
    for f in gdir.iterdir():
        if not records or f.suffix != ".json":
            f.unlink()
    for h in (lake_dir / "holds").glob("*"):
        h.unlink()


def test_after_a_restore_a_generations_name_still_names_the_same_bytes(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    assert lake.hold(NIGHT, "01JOB1", pin=True) == f"{NIGHT}.g1"
    _publish(lake_dir)  # generation 2 is the date's; generation 1 is job 1's
    served = _rows(lake)
    _restored(lake_dir, records=True)
    # a job that pins now gets the name the served bytes had before the restore, never "g1" again
    assert lake.hold(NIGHT, "01JOB2", pin=True) == f"{NIGHT}.g2" and _rows(lake, f"{NIGHT}.g2") == served
    with pytest.raises(FileNotFoundError):
        lake.hold(f"{NIGHT}.g1", "01JOB1")  # job 1, started again: its generation is gone, and it is told so
    lake.release("01JOB2")
    assert _publish(lake_dir).generation == f"{NIGHT}.g3"  # and the numbers go on


def test_the_numbers_go_on_after_the_newest_generation_was_swept(tmp_path: Path) -> None:
    """The record of the highest number stays when its file goes, so a number is never given twice."""
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    _publish(lake_dir)
    _restored(lake_dir, records=True)
    names = sorted(p.name for p in (lake_dir / "db" / "gen").iterdir())
    assert names == [f"{NIGHT}.g2.json"], names
    assert _publish(lake_dir).generation == f"{NIGHT}.g3"
    assert sorted(p.name for p in (lake_dir / "db" / "gen").iterdir()) == [f"{NIGHT}.g3.duckdb", f"{NIGHT}.g3.json"]


def test_the_backup_keeps_the_generations_records_and_not_their_files(tmp_path: Path) -> None:
    from tools.trialbox.backup import select_files

    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    keep, _left = select_files("lake", lake_dir)
    gen = sorted(k for k in keep if k.startswith("db/gen/"))
    assert gen == [f"db/gen/{NIGHT}.g1.json"], gen
    assert "patient" not in (lake_dir / gen[0]).read_text(encoding="utf-8").lower()  # a record: names and a hash
    assert set(json.loads((lake_dir / gen[0]).read_text(encoding="utf-8"))) <= {
        "generation", "snapshot", "seq", "cause", "sha256", "built_at", "site",
    }  # fmt: skip


def test_a_build_without_promote_of_the_served_date_is_refused(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    before, gen = _rows(lake), lake.generation(NIGHT)
    lake.put_site({"Patient": [{"resourceType": "Patient", "id": "site-001", "gender": "male"}]})
    with pytest.raises(ValueError, match="is served"):
        lake.rebuild(NIGHT, HashEmbedder(), promote=False, check=True)
    assert _rows(lake) == before and lake.generation(NIGHT) == gen  # nothing built, nothing served
    job = lake.start_rebuild(NIGHT, HashEmbedder(), promote=False, check=True)
    assert job["state"] == "failed" and "is served" in str(job.get("detail"))
    assert lake.rebuild(NIGHT, HashEmbedder()).generation == f"{NIGHT}.g2"  # with promote: as before


def test_the_promotion_names_its_generation_and_is_refused_for_another(tmp_path: Path) -> None:
    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    nd = lake_dir / "ndjson" / LATER
    nd.mkdir(parents=True)
    (nd / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": "syn-900"}) + "\n")
    built = lake.rebuild(LATER, HashEmbedder(), promote=False, check=True)  # the publish's build
    assert built.generation == f"{LATER}.g1" and not built.promoted and lake.current() == NIGHT
    job = lake.start_rebuild(LATER, HashEmbedder(), promote=False, check=True)  # another build, before the promote
    assert job["result"]["generation"] == f"{LATER}.g2"  # the job's answer names what it built
    with pytest.raises(ValueError, match=r"g1.*g2|g2.*g1"):
        lake.promote_built(LATER, built.generation)
    assert lake.current() == NIGHT  # nothing was served
    assert lake.promote_built(LATER, f"{LATER}.g2") is True and lake.current() == LATER
    assert lake.promote_built(LATER) is True  # without a name: as before (T-723)


def test_the_generation_travels_with_the_promotion_over_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from lake import app as lake_app

    lake_dir = tmp_path / "lake"
    _night(lake_dir, NIGHT, 3)
    lake = Lake(lake_dir, TZ)
    nd = lake_dir / "ndjson" / LATER
    nd.mkdir(parents=True)
    (nd / "Patient.ndjson").write_text(json.dumps({"resourceType": "Patient", "id": "syn-900"}) + "\n")
    lake.rebuild(LATER, HashEmbedder(), promote=False, check=True)
    lake.rebuild(LATER, HashEmbedder(), promote=False, check=True)  # built again: generation 2
    monkeypatch.setattr(lake_app, "lake", lambda: lake)
    http = TestClient(lake_app.app)
    refused = http.post("/promote", json={"snapshot": LATER, "generation": f"{LATER}.g1"})
    assert refused.status_code == 409 and "built again" in refused.text and lake.current() == NIGHT
    done = http.post("/promote", json={"snapshot": LATER, "generation": f"{LATER}.g2"})
    assert done.status_code == 200 and done.json()["promoted"] is True and lake.current() == LATER
