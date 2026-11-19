# ruff: noqa: F811 - the fixture is imported and taken by name
"""D-1253: the one rebuild of a box whose lake ids were made under the earlier rule (``tools/id_rule_rebuild.py``,
runbook §5). A dry run changes nothing; ``--yes`` clears what was made from the old ids and stamps each store. EDC's
trail is never cleared: a study whose decided values cite the old ids stays frozen and is named. Synthetic data
only."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from adapter.ndjson import read_type, snapshot_dir
from adapter.pipeline import AdapterConfig, run_ingest
from tb_common import id_rule
from tb_common.db import Database

from tests.unit.test_db_roles import _as, roles_cluster  # noqa: F401 - the fixture is taken by name
from tools import id_rule_rebuild as rb

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
KEY = b"synthetic site key for D-1253 tests only"
ICD = "http://hl7.org/fhir/sid/icd-10-cm"


def _old_lake(tmp: Path, nights: tuple[str, ...] = ("2026-10-01",)) -> AdapterConfig:
    """A lake with its nights, each snapshot as the release before D-1253 wrote it (no id rule)."""
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
    for night in nights:
        run_ingest(cfg, "csv", str(feed), snapshot=night, load_fhir=False, validate=False)
    for night in nights:
        (snapshot_dir(cfg.lake_dir, night) / id_rule.SNAPSHOT_RECORD).unlink()
    (cfg.lake_dir / "CURRENT").write_text(nights[-1])
    (cfg.lake_dir / "db").mkdir(exist_ok=True)
    for night in nights:  # the served copies the release before left (their bytes do not matter here)
        (cfg.lake_dir / "db" / f"{night}.duckdb").write_bytes(b"")
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
    assert got["omop"]["rule"] == id_rule.OLD and got["omop"]["cleared"] == {"feed_records": 1}
    assert got["vec"]["cleared"] == {"note_chunk": 1} and got["edc"]["open_drafts"] == {"S1": 1}
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


# ------------------------------------------------------------------------------------------------ review G3, G4
TODAY = date(2026, 11, 19)
NIGHTS = ("2026-09-29", "2026-09-30", "2026-11-01")  # 2026-09-30: September's month-end, kept under retention


def test_it_refuses_while_a_night_runs_or_a_lake_build_runs_and_changes_nothing(tmp_path: Path, db_url: str) -> None:
    from adapter.runs import RunLock
    from lake.store import BuildLock

    cfg = _old_lake(tmp_path)
    run = RunLock(cfg.lake_dir)
    try:
        with pytest.raises(rb.Refused, match="a night runs"):
            rb.rebuild(cfg.lake_dir, db_url, TODAY)
    finally:
        run.release()
    build = BuildLock(cfg.lake_dir, "2026-10-01")
    try:
        with pytest.raises(rb.Refused, match="lake build of 2026-10-01 runs"):
            rb.rebuild(cfg.lake_dir, db_url, TODAY)
    finally:
        build.release()
    assert (cfg.lake_dir / "CURRENT").exists() and snapshot_dir(cfg.lake_dir, "2026-10-01").exists()
    assert not (cfg.lake_dir / rb.RECORD).exists()


def test_it_refuses_while_a_service_role_is_connected_to_the_database(
    roles_cluster: tuple[Path, str], tmp_path: Path
) -> None:
    """The box's own roles (``deploy/db-roles.sh``): while the adapter's role holds a session, the rebuild refuses."""
    import psycopg

    _root, url = roles_cluster
    with psycopg.connect(_as(url, "tb_adapter"), autocommit=True):  # a service still up
        assert rb.writers(tmp_path / "lake", url) == ["1 connection(s) of the database role tb_adapter"]
    assert rb.writers(tmp_path / "lake", url) == []


def test_month_ends_under_retention_are_moved_aside_kept_and_never_read(tmp_path: Path, db_url: str) -> None:
    from lake.store import Lake, LakeSchemaError

    cfg = _old_lake(tmp_path, NIGHTS)
    got = rb.plan(cfg.lake_dir, db_url, TODAY)
    assert got["lake"]["moved_aside"] == ["2026-09-30"] and rb.ASIDE in got["lake"]["kept"]
    # before: no reader opens the served snapshot of the earlier rule (review G1)
    with pytest.raises(LakeSchemaError, match="earlier rule"):
        Lake(cfg.lake_dir, "Asia/Taipei").db_path()
    rb.rebuild(cfg.lake_dir, db_url, TODAY)
    aside = cfg.lake_dir / rb.ASIDE
    assert sorted(p.name for p in (aside / "ndjson").iterdir()) == ["2026-09-30"]
    assert (aside / "db" / "2026-09-30.duckdb").exists()
    assert len(list(read_type(aside / "ndjson" / "2026-09-30", "Condition"))) == 1  # kept whole
    assert id_rule.snapshot_rule(aside / "ndjson" / "2026-09-30") == 1  # marked: the earlier rule
    assert json.loads((aside / "README.json").read_text())["rule"] == 1
    assert not (cfg.lake_dir / "ndjson").exists() and not (cfg.lake_dir / "CURRENT").exists()
    with pytest.raises(FileNotFoundError):  # nothing served; the aside is never a snapshot of the lake
        Lake(cfg.lake_dir, "Asia/Taipei").db_path()


def _state(lake: Path, url: str) -> dict[str, Any]:
    from omop.schema import schema_for

    out: dict[str, Any] = {"lake": sorted(p.name for p in lake.iterdir() if p.name not in (rb.RECORD, "locks"))}
    out["aside"] = sorted(str(p.relative_to(lake)) for p in (lake / rb.ASIDE).rglob("*") if p.is_file())
    for store, schema in [(id_rule.OMOP, schema_for(lake)), (id_rule.DERIVED, None), (id_rule.VEC, None),
                          (id_rule.TWIN, None), (id_rule.POOL, None)]:  # fmt: skip
        out[store.name] = id_rule.probe(url, store, schema)
    return out


@pytest.mark.parametrize("crash_after", rb.STEPS[:-1])
def test_a_crash_after_any_step_serves_nothing_old_and_a_second_run_finishes_the_same(
    tmp_path: Path, db_url: str, crash_after: str
) -> None:
    from lake.store import Lake

    clean = _old_lake(tmp_path / "clean", NIGHTS)
    _omop(db_url, clean.lake_dir).close()
    _tables(db_url)
    rb.rebuild(clean.lake_dir, db_url, TODAY)
    want = _state(clean.lake_dir, db_url)

    cfg = _old_lake(tmp_path / "crash", NIGHTS)
    _omop(db_url, cfg.lake_dir).close()

    def crash(step: str) -> None:
        if step == crash_after:
            raise RuntimeError(f"killed after {step}")

    with pytest.raises(RuntimeError, match="killed"):
        rb.rebuild(cfg.lake_dir, db_url, TODAY, after_step=crash)
    if rb.STEPS.index(crash_after) >= rb.STEPS.index("served"):
        assert not (cfg.lake_dir / "CURRENT").exists()  # nothing of the old rule is served any more
        with pytest.raises(FileNotFoundError):
            Lake(cfg.lake_dir, "Asia/Taipei").db_path()
    rb.rebuild(cfg.lake_dir, db_url, TODAY)
    assert _state(cfg.lake_dir, db_url) == {**want, "omop": want["omop"]}


def test_a_resolved_derived_conflict_is_kept_marked_and_never_read_and_built_is_reset(
    tmp_path: Path, db_url: str
) -> None:
    from datacore.dataops import DataOps
    from tb_common.derived_store import DerivedStore

    cfg = _old_lake(tmp_path)
    DerivedStore(db_url)  # the derived store as this release migrates it
    with Database.connect(db_url, "derived") as db:
        db.execute("DELETE FROM tb_id_rule")  # scores of the earlier rule
        db.execute("INSERT INTO definition VALUES ('d1', 's', 1, 'x', '{}', 't')")
        rows = [db.fetchval("INSERT INTO score_row (pid, score, def_version, def_sha, mapping_version, anchor_oid, "
                            "anchor_date, value, unit, inputs, fingerprint, computed_at) VALUES ('p1', 's', 'd1', "
                            f"'x', 'm', 'o{i}', '2026-01-0{i}', 1, 'u', '[]', 'f', 't') RETURNING id")
                for i in (1, 2)]  # fmt: skip
        for i, (row, resolution) in enumerate(zip(rows, ("keep_documented", None), strict=True)):
            db.execute("INSERT INTO conflict (kind, pid, score, row_id, documented_id, documented_status, "
                       "documented_value, documented_date, derived_value, tolerance, opened_at, resolution) VALUES "
                       "('k', 'p1', 's', ?, ?, 'signed', 2, '2026-01-01', 1, 0, 't', ?)",
                       (row, f"doc{i}", resolution))  # fmt: skip
    DataOps(db_url).close()
    with Database.connect(db_url, "dataops") as db:
        db.execute("INSERT INTO built (artefact, snapshot, seq, state, started_at) VALUES ('lake', '2026-10-01', 1, "
                   "'finished', 't')")  # fmt: skip
    got = rb.plan(cfg.lake_dir, db_url, TODAY)
    assert got["derived"]["kept"] == {"resolved_conflicts": 1} and got["derived"]["cleared"]["conflict"] == 1
    assert got["dataops"]["cleared"]["built"] == 1
    done = rb.rebuild(cfg.lake_dir, db_url, TODAY)
    assert done["derived"]["kept"] == {"resolved_conflicts": 1, "their_score_rows": 1}
    with Database.connect(db_url, "derived") as db:
        assert db.fetchall("SELECT resolution, id_rule FROM conflict") == [("keep_documented", 1)]
        (kept,) = db.fetchall("SELECT id, id_rule, superseded_at IS NOT NULL FROM score_row")
        assert kept == (rows[0], 1, True)  # superseded: no screening reads it as a score
        assert db.fetchval("SELECT rule FROM tb_id_rule") == id_rule.RULE
    with Database.connect(db_url, "dataops") as db:
        assert db.fetchval("SELECT count(*) FROM built") == 0


def test_the_rebuild_writes_one_audit_event_of_a_kind_the_box_has(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _old_lake(tmp_path)
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "rebuild-audit"))
    rb.rebuild(cfg.lake_dir, db_url, TODAY)
    events = [json.loads(x) for f in sorted((tmp_path / "rebuild-audit").rglob("*.jsonl")) for x in f.open()]
    (ev,) = events
    assert ev["event"] == "lake.rebuild.source" and ev["detail"]["source"] == "id_rule"
    from console.i18n_audit import EVENTS

    assert "lake.rebuild.source" in EVENTS  # an event the audit already names: no schema change


def test_with_tb_omop_db_url_set_the_omop_store_the_night_probes_is_the_one_cleared(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    omop_url = db_url.replace("tb_prefix=", "tb_prefix=omopdb_")
    monkeypatch.setenv("TB_OMOP_DB_URL", omop_url)
    cfg = _old_lake(tmp_path)
    _omop(omop_url, cfg.lake_dir).close()
    assert rb.plan(cfg.lake_dir, db_url, TODAY)["omop"]["cleared"] == {"feed_records": 1}
    done = rb.rebuild(cfg.lake_dir, db_url, TODAY)
    assert done["omop"]["tb_record"] == 1
    from omop.schema import schema_for

    assert id_rule.probe(omop_url, id_rule.OMOP, schema_for(cfg.lake_dir)) == id_rule.EMPTY
    with Database.connect(omop_url, schema_for(cfg.lake_dir)) as db:
        assert db.fetchval("SELECT rule FROM tb_id_rule") == id_rule.RULE


def test_a_month_end_kept_aside_goes_when_retention_no_longer_keeps_it(tmp_path: Path, db_url: str) -> None:
    from adapter.pipeline import prune_lake

    cfg = _old_lake(tmp_path, NIGHTS)
    rb.rebuild(cfg.lake_dir, db_url, TODAY)
    aside = cfg.lake_dir / rb.ASIDE / "ndjson"
    prune_lake(cfg, date(2027, 1, 5))  # within 36 months: kept
    assert [p.name for p in aside.iterdir()] == ["2026-09-30"]
    gone = prune_lake(cfg, date(2030, 1, 5))  # past retention: it goes, as any month-end does
    assert "2026-09-30" in gone.gone and list(aside.iterdir()) == []
    assert not (cfg.lake_dir / rb.ASIDE / "db" / "2026-09-30.duckdb").exists()
