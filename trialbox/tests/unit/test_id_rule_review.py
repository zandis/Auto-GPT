"""D-1253 independent review. Synthetic source records only."""

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter import backfill as bf
from adapter.mapping import engine
from adapter.mapping.engine import Mapping, MappingError
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import HELD, PASSED
from lake.store import Lake, LakeSchemaError
from omop import schema
from omop.load import load_batch
from tb_common import id_rule

from tests.unit import test_lake_ids_per_patient as ids
from tools import id_rule_rebuild as rb

SNAP = "2026-10-01"
TODAY = date(2026, 11, 19)


def test_practitioner_survives_rebuild(tmp_path: Path, db_url: str) -> None:
    with schema.connect(db_url, schema.schema_for(tmp_path)) as db:
        load_batch(db, "feed", SNAP, {"Practitioner": [{"resourceType": "Practitioner", "id": "S1"}]}, tz="Asia/Taipei")
        db.execute("DELETE FROM tb_id_rule")
        before = db.fetchall("SELECT record_id, record_key FROM tb_record")
        assert len(before) == 1
        rb.rebuild(tmp_path, db_url, TODAY)
        assert db.fetchall("SELECT record_id, record_key FROM tb_record") == before
        assert db.fetchall("SELECT provider_id FROM provider") == [(before[0][0],)]


def test_resume_legacy_spool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ids._cfg(tmp_path, "csv")
    feed = tmp_path / "feed"
    ids.write_csv(ids.CSV_SITE, feed, {"medication": ids.both()["medication"]})

    def stop(bucket: str) -> None:
        raise bf.BackfillStop(bucket)

    with monkeypatch.context() as m:
        m.setattr(
            engine,
            "patient_resource_id",
            lambda key, typ, pid, num, suffix="": engine.resource_id(key, typ, suffix + num),
        )
        first = bf.backfill(cfg, "csv", str(feed), snapshot=SNAP, on_bucket=stop, rebuild_lake=False, validate=False)
    assert first.state == "running" and not first.published
    marker = cfg.lake_dir / "backfill" / SNAP / "spool" / bf.SPOOL_DONE
    old = json.loads(marker.read_text())
    # The exact fingerprint written by rule 1, which did not include the ID rule.
    fp = hashlib.sha256(json.dumps(["csv", str(feed), SNAP, cfg.site_id]).encode())
    fp.update(cfg.mapping_path.read_bytes())
    old["fingerprint"] = fp.hexdigest()
    marker.write_text(json.dumps(old))
    rep = bf.backfill(cfg, "csv", str(feed), snapshot=SNAP, rebuild_lake=False, validate=False)
    assert rep.state == "published", rep.errors
    rows = list(read_type(snapshot_dir(cfg.lake_dir, SNAP), "MedicationRequest"))
    assert len({r["id"] for r in rows}) == len({r["subject"]["reference"] for r in rows}) == 2


@pytest.mark.parametrize(
    ("typ", "form", "override"),
    [
        ("Condition", "pid", False),
        ("Device", "column", False),
        ("Condition", "hid", True),
    ],
)
def test_patient_id_bypass(tmp_path: Path, typ: str, form: str, override: bool) -> None:
    elements: dict[str, Any] = dict(ids.SUBJECT)
    if override:
        elements["id"] = {"column": "no"}
    path = ids._site(tmp_path, [{"type": typ, "table": "thing", "id": {form: "no"}, "elements": elements}])
    with pytest.raises(MappingError):
        Mapping.load(path)


def test_by_day_requires_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit import test_encounter_by_branch_patient_day as days

    link = days.BY_DAY["by_day"]
    assert isinstance(link, dict)
    monkeypatch.setitem(link, "keys", ["branch"])
    with pytest.raises(MappingError):
        days._mapping(tmp_path)


@pytest.mark.parametrize(("typ", "table"), [("Coverage", "patient"), ("Consent", "registry")])
def test_chart_key_spelling(typ: str, table: str) -> None:
    mapping, mapper = ids._mapper()
    spec = next(r for r in mapping.resources if r.type == typ)
    row = ids.canonical(ids.A)[table][0]
    wide = {**row, "mrn": "１００００００１"}
    expected = mapper.row_id(spec, row)
    assert mapper.row_id(spec, wide) == expected
    assert (typ, expected) in mapper.tombstones(table, iter([wide]))
    if typ == "Coverage":
        claim = next(r for r in mapping.resources if r.type == "Claim")
        assert mapper.ref({"type": typ, "hid": "mrn"}, wide, claim) == f"Coverage/{expected}"


def test_last_passed_month_end(tmp_path: Path) -> None:
    for day, marker in [("2026-10-30", PASSED), ("2026-10-31", HELD)]:
        folder = snapshot_dir(tmp_path, day)
        folder.mkdir(parents=True)
        (folder / marker).write_text("{}")
    done = rb.rebuild(tmp_path, None, TODAY)
    assert done["moved_aside"] == ["2026-10-30"]
    assert (snapshot_dir(tmp_path / rb.ASIDE, "2026-10-30") / PASSED).exists()


@pytest.mark.xfail(
    strict=True, raises=pytest.fail.Exception, reason="D-1253 review 9: unmarked DuckDB beside rule-2 NDJSON"
)
def test_duckdb_owns_its_rule(tmp_path: Path) -> None:
    db = tmp_path / "db" / f"{SNAP}.duckdb"
    db.parent.mkdir()
    db.touch()
    nd = snapshot_dir(tmp_path, SNAP)
    nd.mkdir(parents=True)
    id_rule.write_snapshot_record(nd)
    with pytest.raises(LakeSchemaError, match="earlier rule"):
        Lake(tmp_path, "UTC").db_path(SNAP)


@pytest.mark.parametrize("rule", ["3", "unreadable"])
def test_downgrade_checks_duckdb(tmp_path: Path, rule: str) -> None:
    db = tmp_path / "db" / "2026-11-18.duckdb"
    db.parent.mkdir()
    db.touch()
    db.with_suffix(".duckdb.id_rule").write_text(rule)
    with pytest.raises(rb.Refused, match="Update the box"):
        rb.rebuild(tmp_path, None, TODAY)
    assert db.exists()


def test_confirmed_odm_survives_rebuild(tmp_path: Path, db_url: str) -> None:
    from tests import edc_kit as k
    from tests.unit import test_odm_import as odm
    from tests.unit.test_edc_id_rule_freeze import _as_before_d1253
    from tests.unit.test_edc_t302b import _service

    svc, *_ = _service(tmp_path)
    odm._subject(svc)
    svc.import_odm(k.STUDY, odm._odm(odm._row('<ItemData ItemOID="weight" Value="80"/>')), "crc")
    (draft,) = odm._open(svc, odm.NEW).values()
    svc.decide(k.STUDY, draft["id"], "confirm", by="crc")
    _as_before_d1253(svc)
    assert not svc.status(k.STUDY)["id_rule_frozen"]
    done = rb.rebuild(tmp_path / "lake", db_url, TODAY)
    assert done["edc"]["studies_now_rule_2"] == [k.STUDY]
    kept = svc.store.draft(k.STUDY, draft["id"])
    assert kept is not None
    assert kept["fate"] == "confirmed" and kept["final_citation"] == draft["citation"]
