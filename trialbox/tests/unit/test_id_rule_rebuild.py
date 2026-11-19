"""D-1253: the one rebuild of a box whose lake ids were made under the earlier rule (``tools/id_rule_rebuild.py``,
runbook §5). A dry run changes nothing; ``--yes`` clears what was made from the old ids and stamps each store. EDC's
trail is never cleared: a study whose decided values cite the old ids stays frozen and is named. Synthetic data
only."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import AdapterConfig, run_ingest
from tb_common import id_rule
from tb_common.db import Database

from tools import id_rule_rebuild as rb

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
KEY = b"synthetic site key for D-1253 tests only"
ICD = "http://hl7.org/fhir/sid/icd-10-cm"


def _old_lake(tmp: Path) -> AdapterConfig:
    """A lake with one night, its snapshot as the release before D-1253 wrote it (no id rule)."""
    sec = tmp / "secrets"
    sec.mkdir(parents=True)
    (sec / "site_hmac.key").write_bytes(KEY)
    (sec / "site_hmac.key").chmod(0o600)
    cfg = AdapterConfig(lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=BASE, site_id="T", tz="Asia/Taipei",
                        audit_dir=tmp / "audit", validation_max_pct=100.0)  # fmt: skip
    feed = tmp / "feed"
    feed.mkdir()
    with (feed / "diagnosis.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status"])
        w.writerow(["D1", "E1", "10000001", "M10.9", "2026-09-01", "2026-09-01", "A"])
    run_ingest(cfg, "csv", str(feed), snapshot="2026-10-01", load_fhir=False, validate=False)
    (snapshot_dir(cfg.lake_dir, "2026-10-01") / id_rule.SNAPSHOT_RECORD).unlink()
    return cfg


def _omop(url: str, lake: Path) -> Database:
    from omop import schema
    from omop.load import load_batch

    db = schema.connect(url, schema.schema_for(lake))
    feed: dict[str, list[dict[str, Any]]] = {
        "Patient": [{"resourceType": "Patient", "id": "P1", "birthDate": "1960-01-01", "gender": "female"}],
        "Condition": [{"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/P1"},
                       "code": {"coding": [{"system": ICD, "code": "E11.9"}]}, "onsetDateTime": "2024-07-01"}],
    }  # fmt: skip
    load_batch(db, "feed", "2026-10-01", feed, tz="Asia/Taipei")
    db.execute("DELETE FROM tb_id_rule")  # the store as the release before D-1253 left it
    return db


def _tables(url: str) -> None:
    """The other stores, as far as the rebuild reads them: their tables with a row each, and no id rule."""
    made = {
        "derived": ["score_row", "input_link", "conflict", "batch_run"],
        "vec": ["note_chunk"],
        "profile": ["tb_patient_profile"],
        "orch": ["pool"],
    }
    for schema, tables in made.items():
        with Database.connect(url, schema) as db:
            for t in tables:
                db.execute(f"CREATE TABLE {t} (x INTEGER DEFAULT 1)")
                db.execute(f"INSERT INTO {t} DEFAULT VALUES")
    with Database.connect(url, "edc") as db:
        db.execute("CREATE TABLE draft (id INTEGER PRIMARY KEY, study TEXT, citation TEXT, final_citation TEXT, "
                   "fate TEXT, signature_id BIGINT, sent_at TEXT)")  # fmt: skip
        db.execute("CREATE TABLE decision (id INTEGER PRIMARY KEY, draft_id INTEGER)")
        db.execute("INSERT INTO draft VALUES (1, 'S1', '{}', NULL, 'open', NULL, NULL)")


def test_the_plan_changes_nothing(tmp_path: Path, db_url: str) -> None:
    cfg = _old_lake(tmp_path)
    _omop(db_url, cfg.lake_dir).close()
    _tables(db_url)
    assert rb.main(["--lake", str(cfg.lake_dir), "--db-url", db_url]) == 0
    got = rb.plan(cfg.lake_dir, db_url)
    assert got["lake"]["old_snapshots"] == ["2026-10-01"]
    assert got["omop"]["rule"] == id_rule.OLD and got["omop"]["feed_records"] == 1
    assert got["vec"]["rows"] == {"note_chunk": 1} and got["edc"]["open_drafts"] == 1
    assert snapshot_dir(cfg.lake_dir, "2026-10-01").exists()


def test_the_rebuild_clears_what_the_old_ids_made_and_the_next_night_is_a_full_one(tmp_path: Path, db_url: str) -> None:
    cfg = _old_lake(tmp_path)
    with pytest.raises(id_rule.IdRuleError):  # before: the night refuses
        run_ingest(cfg, "csv", str(tmp_path / "feed"), snapshot="2026-10-02", load_fhir=False, validate=False)
    _omop(db_url, cfg.lake_dir).close()
    _tables(db_url)
    assert rb.main(["--lake", str(cfg.lake_dir), "--db-url", db_url, "--yes"]) == 0
    assert not (cfg.lake_dir / "ndjson").exists() and (cfg.lake_dir / "site_key.json").exists()
    done = json.loads((cfg.lake_dir / rb.RECORD).read_text(encoding="utf-8"))
    assert done["omop"]["tb_record"] == 1 and done["omop"]["condition_occurrence"] == 1
    from omop.schema import schema_for

    for store, schema in [(id_rule.OMOP, schema_for(cfg.lake_dir)), (id_rule.DERIVED, None), (id_rule.VEC, None),
                          (id_rule.TWIN, None), (id_rule.POOL, None)]:  # fmt: skip
        assert id_rule.probe(db_url, store, schema) == id_rule.EMPTY, store.name
        with Database.connect(db_url, schema or store.schema) as db:
            assert db.fetchval("SELECT rule FROM tb_id_rule") == id_rule.RULE, store.name
    with Database.connect(db_url, "edc") as db:  # the open draft (no trail) of a study of the earlier rule: gone
        assert db.fetchval("SELECT count(*) FROM draft") == 0
    with Database.connect(db_url, schema_for(cfg.lake_dir)) as db:  # the person stays: its pseudonym is the same
        assert db.fetchval("SELECT count(*) FROM tb_record WHERE resource_type = 'Patient'") == 1
    # the next night: no snapshot to merge over, so the night is whole, under rule 2
    run_ingest(cfg, "csv", str(tmp_path / "feed"), snapshot="2026-10-02", load_fhir=False, validate=False)
    folder = snapshot_dir(cfg.lake_dir, "2026-10-02")
    assert id_rule.snapshot_rule(folder) == id_rule.RULE and len(list(read_type(folder, "Condition"))) == 1


def test_edc_values_a_person_decided_are_kept_and_their_study_is_named_frozen(
    tmp_path: Path, db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing of EDC's trail is ever cleared: the decided draft and its decision stay; the open draft no trail names
    goes; the study is named frozen with its export; everything else is rebuilt."""
    cfg = _old_lake(tmp_path)
    _tables(db_url)
    with Database.connect(db_url, "edc") as db:
        db.execute("INSERT INTO draft VALUES (2, 'S2', '{}', '{}', 'confirmed', 7, NULL)")
        db.execute("INSERT INTO decision VALUES (1, 2)")
    assert rb.plan(cfg.lake_dir, db_url)["edc"]["frozen_studies"] == {"S2": 1}
    assert rb.main(["--lake", str(cfg.lake_dir), "--db-url", db_url, "--yes"]) == 0
    said = capsys.readouterr().out
    assert "EDC study S2: frozen for prefill (1 decided" in said and "/api/v1/studies/S2/edc/export/odm" in said
    assert not (cfg.lake_dir / "ndjson").exists()
    with Database.connect(db_url, "edc") as db:
        assert [r[0] for r in db.fetchall("SELECT id FROM draft ORDER BY id")] == [2]
        assert db.fetchval("SELECT count(*) FROM decision") == 1


def test_the_host_command_runs_the_rebuild_as_the_admin_in_a_one_off_adapter_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python3 -m tools.trialbox id-rule-rebuild [--yes]``: the admin's URL of deploy/.env reaches the container in
    its environment, never on a command line."""
    from collections.abc import Sequence

    from tools.trialbox import __main__ as tb
    from tools.trialbox import update as up

    word = "synthetic-admin"  # a test string, not a password of anything
    url = "postgresql://" + "trialbox:" + word + "@db:5432/trialbox_wf"
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(f"TB_DB_URL={url}\n")
    (deploy / ".env").chmod(0o600)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(argv: Sequence[str], env: dict[str, str] | None = None, **_: Any) -> str:
        calls.append((list(argv), dict(env or {})))
        return "{}"

    real = up.ComposeBox
    monkeypatch.setattr(up, "ComposeBox", lambda d: real(d, run=run))
    assert tb.main(["id-rule-rebuild", "--deploy", str(deploy)]) == 0
    assert tb.main(["id-rule-rebuild", "--deploy", str(deploy), "--yes"]) == 0
    (plan, _), (act, env) = calls
    want = ["-T", "-e", "TB_DB_URL", "adapter", "python", "-m", "tools.id_rule_rebuild", "--lake", "/data/lake"]
    assert plan[-len(want) :] == want and "run" in plan and "--rm" in plan
    assert act[-1] == "--yes" and env == {"TB_DB_URL": url} and not any(word in a for c, _e in calls for a in c)
    (tmp_path / "bare").mkdir()
    (tmp_path / "bare" / ".env").write_text("X=1\n")
    assert tb.main(["id-rule-rebuild", "--deploy", str(tmp_path / "bare")]) == 1
