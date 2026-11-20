"""D-1253 review round 3, item 4: every entry point that reads a lake snapshot's NDJSON outside the night goes through
one place (``tb_common.id_rule.open_snapshot``), which refuses a snapshot of the earlier id rule and of a later one
before anything is read or written. The tester's case: ``python -m omop load --lake <old lake>`` into an empty OMOP
store loaded the earlier rule's records and stamped the store rule 2. Synthetic data only."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import AdapterConfig
from embed_service.embedder import HashEmbedder
from lake.store import Lake, LakeSchemaError, RebuildError
from tb_common import id_rule
from tb_common.db import Database

ROOT = Path(__file__).resolve().parents[2]
SNAP = "2026-10-04"
TZ = "Asia/Taipei"
RULES = ["earlier", "later"]


def _lake(tmp: Path, rule: str) -> Path:
    """A lake with one snapshot of another id rule: the earlier one (no record) or a later release's (rule 3)."""
    lake = tmp / "lake"
    nd = snapshot_dir(lake, SNAP)
    nd.mkdir(parents=True)
    rows: dict[str, list[dict[str, Any]]] = {
        "Patient": [{"resourceType": "Patient", "id": "a" * 64, "birthDate": "1960-01-01", "gender": "female"}],
        "Condition": [{"resourceType": "Condition", "id": "c1", "subject": {"reference": f"Patient/{'a' * 64}"},
                       "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.9"}]},
                       "onsetDateTime": "2024-07-01"}],
    }  # fmt: skip
    for rtype, items in rows.items():
        (nd / f"{rtype}.ndjson").write_text("".join(json.dumps(r) + "\n" for r in items), encoding="utf-8")
    if rule == "later":
        (nd / id_rule.SNAPSHOT_RECORD).write_text(json.dumps({"rule": id_rule.RULE + 1}), encoding="utf-8")
    (lake / "CURRENT").write_text(SNAP)
    return lake


def _words(rule: str) -> str:
    return "earlier rule" if rule == "earlier" else "(?i)update the box"


@pytest.mark.parametrize("rule", RULES)
def test_the_omop_load_command_refuses_a_snapshot_of_another_rule_and_loads_nothing(
    tmp_path: Path, db_url: str, rule: str, capsys: pytest.CaptureFixture[str]
) -> None:
    from omop import schema
    from omop.__main__ import main

    lake = _lake(tmp_path, rule)
    assert main(["load", "--lake", str(lake), "--snapshot", SNAP, "--tz", TZ]) == 2
    assert re.search(_words(rule), capsys.readouterr().err)
    db = schema.connect()  # the store the command loads into
    try:
        assert db.fetchval("SELECT count(*) FROM tb_record") == 0
        assert db.fetchval("SELECT count(*) FROM tb_id_rule") == 0  # never stamped rule 2 over nothing it may hold
    finally:
        db.close()


@pytest.mark.parametrize("rule", RULES)
def test_the_dual_write_refuses_a_snapshot_of_another_rule_and_writes_nothing(
    tmp_path: Path, db_url: str, rule: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.dual_write import load_night
    from omop import schema

    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    lake = _lake(tmp_path, rule)
    cfg = AdapterConfig(lake_dir=lake, secrets_dir=tmp_path, mapping_path=ROOT / "services/adapter/mapping/tw_core/"
                        "demo_his.yaml", site_id="T", tz=TZ, db_url=db_url)  # fmt: skip
    got = load_night(cfg, SNAP, snapshot_dir(lake, SNAP))
    assert got is not None and got.state == "refused" and re.search(_words(rule), got.error or "")
    with Database.connect(db_url, schema.schema_for(lake)) as db:
        assert db.fetchval("SELECT count(*) FROM tb_record") == 0


@pytest.mark.parametrize("rule", RULES)
def test_the_fhir_load_refuses_a_snapshot_of_another_rule_before_anything_is_sent(tmp_path: Path, rule: str) -> None:
    from adapter.load_fhir import load_snapshot

    lake = _lake(tmp_path, rule)
    with pytest.raises(id_rule.IdRuleError, match=_words(rule)):
        load_snapshot("http://127.0.0.1:9/fhir", snapshot_dir(lake, SNAP))  # nothing listens: nothing is sent


@pytest.mark.parametrize("rule", RULES)
def test_the_validation_refuses_a_snapshot_of_another_rule(tmp_path: Path, rule: str) -> None:
    from adapter.validate.jpcore import validate_snapshot

    lake = _lake(tmp_path, rule)
    with pytest.raises(id_rule.IdRuleError, match=_words(rule)):
        validate_snapshot(snapshot_dir(lake, SNAP))


@pytest.mark.parametrize("own_folder", [False, True], ids=["lake-folder", "folder-of-its-own"])
@pytest.mark.parametrize("rule", RULES)
def test_the_lake_build_refuses_a_snapshot_of_another_rule_and_builds_nothing(
    tmp_path: Path, rule: str, own_folder: bool
) -> None:
    lake = _lake(tmp_path, rule)
    src = snapshot_dir(lake, SNAP)
    if own_folder:  # a build from a folder outside the lake (``ndjson_dir``)
        src = src.rename(tmp_path / "elsewhere")
    with pytest.raises(RebuildError, match=_words(rule)):
        Lake(lake, TZ).rebuild(SNAP, HashEmbedder(), ndjson_dir=src if own_folder else None)
    assert not (lake / "db" / f"{SNAP}.duckdb").exists()


@pytest.mark.parametrize(("side", "served"), [(None, False), ("3", False), ("x", False), ("2", True)],
                         ids=["none-earlier", "later", "unreadable", "this-rule"])  # fmt: skip
def test_a_snapshot_served_without_its_ndjson_is_read_only_when_its_build_said_this_rule(
    tmp_path: Path, side: str | None, served: bool
) -> None:
    """The byte budget takes a snapshot's NDJSON first (NEW-B-38): the file is checked by the rule its build wrote
    beside it (``db/<s>.duckdb.id_rule``); none is a file built before D-1253, of the earlier rule."""
    lake = tmp_path / "lake"
    (lake / "db").mkdir(parents=True)
    (lake / "db" / f"{SNAP}.duckdb").write_bytes(b"")
    if side is not None:
        (lake / "db" / f"{SNAP}.duckdb.id_rule").write_text(side + "\n")
    if served:
        assert Lake(lake, TZ).db_path(SNAP) == lake / "db" / f"{SNAP}.duckdb"
        return
    with pytest.raises(LakeSchemaError):
        Lake(lake, TZ).db_path(SNAP)


def test_a_build_writes_the_rule_beside_its_file_and_the_snapshot_is_still_served_without_its_ndjson(
    tmp_path: Path,
) -> None:
    import shutil

    lake = _lake(tmp_path, "earlier")
    id_rule.write_snapshot_record(snapshot_dir(lake, SNAP))  # a snapshot of this rule
    Lake(lake, TZ).rebuild(SNAP, HashEmbedder())
    assert (lake / "db" / f"{SNAP}.duckdb.id_rule").read_text().strip() == str(id_rule.RULE)
    shutil.rmtree(snapshot_dir(lake, SNAP))  # the byte budget took the NDJSON
    assert Lake(lake, TZ).db_path(SNAP).exists()


@pytest.mark.parametrize("rule", RULES)
def test_the_fhir_sync_refuses_before_its_ledger_is_read_or_written(tmp_path: Path, rule: str) -> None:
    """D-1253 deep review (low): the night's FHIR step (``sync_snapshot``) hashed the snapshot and rewrote its ledger
    before ``load_snapshot`` refused. The real entry point now refuses first: no ledger is made."""
    from adapter.load_fhir import sync_snapshot

    lake = _lake(tmp_path, rule)
    ledger = tmp_path / "fhir_ledger"
    with pytest.raises(id_rule.IdRuleError, match=_words(rule)):
        sync_snapshot("http://127.0.0.1:9/fhir", snapshot_dir(lake, SNAP), ledger)
    assert not ledger.exists()
