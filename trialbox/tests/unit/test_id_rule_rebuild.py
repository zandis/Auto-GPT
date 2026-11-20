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
        # as EDC's migration (SCHEMA_V9) leaves it: every study with drafts stamped rule 1
        db.execute(
            "CREATE TABLE tb_id_rule_study (study TEXT PRIMARY KEY, rule INTEGER NOT NULL, "
            "recorded_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        db.execute("INSERT INTO tb_id_rule_study VALUES ('S1', 1)")


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
        db.execute("INSERT INTO tb_id_rule_study (study, rule) VALUES ('S2', 1)")  # as the migration stamps it
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


def _served_month_end(cfg: AdapterConfig, s: str = "2026-09-30", ndjson: bool = True) -> list[str]:
    """The month-end ``s`` with every part a box has: the DuckDB file, its sidecar and its generation's file and
    record, the Parquet folder; without its NDJSON when the byte budget took it (NEW-B-38). Returns its files, as
    paths under the lake."""
    lake = cfg.lake_dir
    (lake / "db" / f"{s}.duckdb").write_bytes(b"served " + s.encode())
    (lake / "db" / f"{s}.duckdb.sha256").write_text(f"x  {s}.duckdb\n")
    (lake / "db" / "gen").mkdir(parents=True, exist_ok=True)
    (lake / "db" / "gen" / f"{s}.g1.duckdb").write_bytes(b"served " + s.encode())
    (lake / "db" / "gen" / f"{s}.g1.json").write_text(json.dumps({"generation": f"{s}.g1", "snapshot": s}))
    pq = lake / "parquet" / f"snapshot={s}"
    pq.mkdir(parents=True, exist_ok=True)
    (pq / "condition.parquet").write_bytes(b"PAR1")
    (pq / "condition.parquet.sha256").write_text("x  condition.parquet\n")
    if not ndjson:
        import shutil

        shutil.rmtree(lake / "ndjson" / s)
    return sorted(str(p.relative_to(lake)) for d in ("ndjson", "db", "parquet") for p in (lake / d).rglob("*")
                  if p.is_file() and s in p.name + str(p.parent.name))  # fmt: skip


def _aside_files(lake: Path) -> dict[str, bytes]:
    root = lake / rb.ASIDE
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_month_end_served_without_its_ndjson_is_moved_aside_whole_with_its_sidecars(tmp_path: Path) -> None:
    """Review round 3, item 2: the byte budget may have taken a month-end's NDJSON and left it served. It is still a
    month-end: its DuckDB file, sidecar, generation and Parquet go aside, none is cleared as a served copy."""
    cfg = _old_lake(tmp_path, NIGHTS)
    files = _served_month_end(cfg, ndjson=False)
    assert rb.plan(cfg.lake_dir, None, TODAY)["lake"]["moved_aside"] == ["2026-09-30"]
    rb.rebuild(cfg.lake_dir, None, TODAY)
    kept = _aside_files(cfg.lake_dir)
    assert sorted(f for f in kept if f != "README.json") == files  # each file where it was, under id_rule_1
    assert kept["db/2026-09-30.duckdb"] == b"served 2026-09-30"
    assert json.loads(kept["README.json"])["snapshots"] == ["2026-09-30"]


def test_a_crash_between_any_two_moves_aside_loses_nothing_and_a_second_run_finishes_the_same(
    tmp_path: Path,
) -> None:
    """Review round 3, item 2: the rebuild is killed after each single file or folder it moves aside, in turn. The
    second run sees what is aside already and what is left, takes the month-end as one, and ends with the same
    aside folder as a run never killed: no served copy, sidecar or generation of a kept month-end is cleared."""
    clean = _old_lake(tmp_path / "clean", NIGHTS)
    _served_month_end(clean)
    moves: list[Path] = []
    rb.rebuild(clean.lake_dir, None, TODAY, after_move=moves.append)
    want = _aside_files(clean.lake_dir)
    assert len(moves) == 6 and "ndjson/2026-09-30/Condition.ndjson" in want and "db/gen/2026-09-30.g1.json" in want
    for k in range(len(moves)):
        cfg = _old_lake(tmp_path / f"crash{k}", NIGHTS)
        _served_month_end(cfg)
        seen: list[Path] = []

        def crash(dst: Path, n: int = k, seen: list[Path] = seen) -> None:
            seen.append(dst)
            if len(seen) == n + 1:
                raise RuntimeError(f"killed after move {n + 1}")

        with pytest.raises(RuntimeError, match="killed"):
            rb.rebuild(cfg.lake_dir, None, TODAY, after_move=crash)
        rb.rebuild(cfg.lake_dir, None, TODAY)
        got = _aside_files(cfg.lake_dir)  # the same files (a night's own records hold its times and paths)
        assert sorted(got) == sorted(want), f"killed after move {k + 1} of {len(moves)}"
        assert got["db/2026-09-30.duckdb"] == got["db/gen/2026-09-30.g1.duckdb"] == b"served 2026-09-30"
        assert not (cfg.lake_dir / "db").exists() and not (cfg.lake_dir / "parquet").exists()


def test_a_lake_a_later_release_wrote_is_never_rebuilt_as_rule_1(tmp_path: Path) -> None:
    """Review round 3, item 3: a snapshot whose record says a rule above this release's is a later release's. The
    plan names it; the rebuild refuses and changes nothing: nothing is moved aside under a README that says rule 1,
    nothing served is cleared. The words say: update the box."""
    cfg = _old_lake(tmp_path, NIGHTS)
    (snapshot_dir(cfg.lake_dir, "2026-11-01") / id_rule.SNAPSHOT_RECORD).write_text('{"rule": 3}')
    before = sorted(str(p.relative_to(cfg.lake_dir)) for p in cfg.lake_dir.rglob("*") if "locks" not in str(p))
    assert rb.plan(cfg.lake_dir, None, TODAY)["newer"] == ["the lake snapshot ndjson/2026-11-01 is of id rule 3"]
    with pytest.raises(rb.Refused, match="Update the box"):
        rb.rebuild(cfg.lake_dir, None, TODAY)
    assert rb.main(["--lake", str(cfg.lake_dir), "--yes"]) == 2
    after = sorted(str(p.relative_to(cfg.lake_dir)) for p in cfg.lake_dir.rglob("*") if "locks" not in str(p))
    assert after == before and not (cfg.lake_dir / rb.ASIDE).exists()


@pytest.mark.parametrize("where", ["derived", "edc"])
def test_a_store_or_a_study_a_later_release_stamped_refuses_the_rebuild(
    tmp_path: Path, db_url: str, where: str
) -> None:
    """Review round 3, item 3: a store stamped by a later release, or an EDC study of a later rule, refuses the
    rebuild before any step; the lake and every store are as they were."""
    cfg = _old_lake(tmp_path, NIGHTS)
    _tables(db_url)
    with Database.connect(db_url, where) as db:
        if where == "edc":
            db.execute("INSERT INTO tb_id_rule_study VALUES ('S9', 3)")
        else:
            db.execute(id_rule.DDL)
            db.execute("INSERT INTO tb_id_rule (rule) VALUES (3)")
    with pytest.raises(rb.Refused, match="later release"):
        rb.rebuild(cfg.lake_dir, db_url, TODAY)
    assert (cfg.lake_dir / "CURRENT").exists() and not (cfg.lake_dir / rb.ASIDE).exists()
    with Database.connect(db_url, "derived") as db:
        assert db.fetchval("SELECT count(*) FROM score_row") == 1


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


@pytest.mark.parametrize("cut", ["", '{"ru', '{"rule": '], ids=["empty", "cut-key", "cut-value"])
def test_a_cut_id_rule_record_has_one_instruction_from_the_night_and_the_rebuild(tmp_path: Path, cut: str) -> None:
    """D-1253 deep review, finding 2: a record that cannot be read (a write cut short) was read as rule 0, so the night
    said "earlier rule, rebuild" and the rebuild "a later release, update the box". Now the record is written
    atomically, and one that cannot be read is its own state: the night and the rebuild both refuse, changing
    nothing, with the same one instruction (move the unfinished snapshot out, run the night again)."""
    from adapter.pipeline import check_id_rule

    cfg = _old_lake(tmp_path, NIGHTS)
    for night in NIGHTS:
        id_rule.write_snapshot_record(snapshot_dir(cfg.lake_dir, night))  # a lake of this rule
    (snapshot_dir(cfg.lake_dir, "2026-11-01") / id_rule.SNAPSHOT_RECORD).write_text(cut)
    words = id_rule.unreadable_words(["the lake snapshot 2026-11-01"])
    with pytest.raises(id_rule.IdRuleError) as at_night:
        check_id_rule(cfg)
    assert str(at_night.value) == words and "rebuild" not in words.split("(")[0].lower()
    assert rb.plan(cfg.lake_dir, None, TODAY)["unreadable"] == ["the lake snapshot ndjson/2026-11-01"]
    before = sorted(str(p.relative_to(cfg.lake_dir)) for p in cfg.lake_dir.rglob("*") if "locks" not in str(p))
    with pytest.raises(rb.Refused) as refused:
        rb.rebuild(cfg.lake_dir, None, TODAY)
    assert "cannot be read" in str(refused.value) and "Move that folder out of the lake" in str(refused.value)
    after = sorted(str(p.relative_to(cfg.lake_dir)) for p in cfg.lake_dir.rglob("*") if "locks" not in str(p))
    assert after == before


def test_the_id_rule_record_is_written_whole_or_not_at_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D-1253 deep review, finding 2: the record goes to a temporary file renamed into place: a write that fails
    leaves no record at all (never a cut one), and no temporary file is left after a good write."""
    folder = tmp_path / "snap"
    folder.mkdir()
    real = Path.write_text

    def full_disk(self: Path, *a: Any, **k: Any) -> int:
        real(self, '{"ru', encoding="utf-8")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_text", full_disk)
    with pytest.raises(OSError):
        id_rule.write_snapshot_record(folder)
    monkeypatch.undo()
    assert not (folder / id_rule.SNAPSHOT_RECORD).exists()
    id_rule.write_snapshot_record(folder)
    assert sorted(p.name for p in folder.iterdir() if p.name != f".{id_rule.SNAPSHOT_RECORD}.tmp") == [
        id_rule.SNAPSHOT_RECORD
    ]
    assert id_rule.snapshot_rule(folder) == id_rule.RULE and not (folder / f".{id_rule.SNAPSHOT_RECORD}.tmp").exists()


def _at(monkeypatch: pytest.MonkeyPatch, utc: str) -> None:
    """The rebuild's clock at the instant ``utc``, whatever the zone it is asked in."""
    from datetime import datetime as real

    class Clock(real):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            at = real.fromisoformat(utc)
            return at.astimezone(tz) if tz is not None else at

    monkeypatch.setattr(rb, "datetime", Clock)


def test_a_rebuild_early_on_the_first_keeps_last_months_month_end_by_the_sites_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-1253 deep review, finding 3a: at 08:00 on 1 November in Tokyo it is still 31 October at UTC. The rebuild
    reckons the month by the site's date (``TB_TZ``), as the night and retention do: October is complete, and its
    month-end is moved aside, never cleared. No ``today`` is passed."""
    from adapter.pipeline import PASSED

    cfg = _old_lake(tmp_path, ("2026-10-30", "2026-10-31"))
    for night in ("2026-10-30", "2026-10-31"):
        (snapshot_dir(cfg.lake_dir, night) / PASSED).write_text("{}")
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    _at(monkeypatch, "2026-10-31T23:00:00+00:00")
    assert rb.site_today() == date(2026, 11, 1)
    assert rb.plan(cfg.lake_dir, None)["lake"]["moved_aside"] == ["2026-10-31"]
    rb.rebuild(cfg.lake_dir, None)
    assert (cfg.lake_dir / rb.ASIDE / "ndjson" / "2026-10-31").is_dir()


def test_a_held_last_night_is_not_the_month_end_retention_keeps_the_last_passed_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-1253 deep review, finding 3b: 30 October passed, 31 October was held, 1 November passed. Retention keeps 30
    October as October's month-end (it counts passed nights only); the rebuild moves that one aside, the same one,
    and clears the held night. No ``today`` is passed."""
    from adapter.pipeline import PASSED

    nights = ("2026-10-30", "2026-10-31", "2026-11-01")
    cfg = _old_lake(tmp_path, nights)
    for night in ("2026-10-30", "2026-11-01"):
        (snapshot_dir(cfg.lake_dir, night) / PASSED).write_text("{}")
    (snapshot_dir(cfg.lake_dir, "2026-10-31") / PASSED).unlink(missing_ok=True)
    (cfg.lake_dir / "db" / "2026-10-31.duckdb").unlink()  # a held night has no DuckDB
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    _at(monkeypatch, "2026-11-19T03:00:00+00:00")
    assert rb.plan(cfg.lake_dir, None)["lake"]["moved_aside"] == ["2026-10-30"]
    rb.rebuild(cfg.lake_dir, None)
    assert sorted(p.name for p in (cfg.lake_dir / rb.ASIDE / "ndjson").iterdir()) == ["2026-10-30"]


def test_a_backup_takes_a_month_end_moved_aside_by_the_same_rules_as_before(tmp_path: Path) -> None:
    """D-1253 deep review, finding 4: the backup's lake rules matched only the top-level ``ndjson/``, ``db/`` and
    ``parquet/``, so after the rebuild every NDJSON and generation file under ``id_rule_1/`` was copied. A month-end
    moved aside is taken by the same rules as it was before the move: its NDJSON and older generations left out, its
    DuckDB file, generation records and Parquet kept."""
    from tools.trialbox import backup as bk

    cfg = _old_lake(tmp_path, ("2026-09-30", "2026-11-01", "2026-11-02", "2026-11-03"))  # 09-30: an older snapshot
    _served_month_end(cfg)

    def of_month_end(root: Path) -> tuple[list[str], list[str]]:
        keep, _ = bk.select_files("lake", root)
        taken = sorted(r.removeprefix(rb.ASIDE + "/") for r in keep if "2026-09-30" in r)
        everything = sorted(str(p.relative_to(root)).removeprefix(rb.ASIDE + "/") for p in root.rglob("*")
                            if p.is_file() and "2026-09-30" in str(p))  # fmt: skip
        return taken, sorted(set(everything) - set(taken))

    before = of_month_end(cfg.lake_dir)
    assert any(r.startswith("ndjson/2026-09-30/") and r.endswith(".ndjson") for r in before[1])  # left out before
    rb.rebuild(cfg.lake_dir, None, TODAY)
    after = of_month_end(cfg.lake_dir)
    assert after == before


def test_a_box_of_this_rule_throughout_has_nothing_to_do_and_nothing_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D-1253 deep review, finding 5: ``--yes`` on a healthy rule-2 lake cleared what was served and moved rule-2
    month-ends aside under a README saying rule 1. When no snapshot, store or EDC study is of the earlier rule, the
    plan and the rebuild say "nothing to do" and change nothing (exit 0)."""
    cfg = _old_lake(tmp_path, NIGHTS)
    for night in NIGHTS:
        id_rule.write_snapshot_record(snapshot_dir(cfg.lake_dir, night))  # a lake of this rule
        (cfg.lake_dir / "db" / f"{night}.duckdb.id_rule").write_text("2\n")
    before = sorted(str(p.relative_to(cfg.lake_dir)) for p in cfg.lake_dir.rglob("*") if "locks" not in str(p))
    assert rb.plan(cfg.lake_dir, None, TODAY)["earlier"] == []
    assert rb.rebuild(cfg.lake_dir, None, TODAY) == {"nothing_to_do": True, "rule": id_rule.RULE}
    assert rb.main(["--lake", str(cfg.lake_dir), "--yes"]) == 0
    assert "nothing to do" in capsys.readouterr().out
    after = sorted(str(p.relative_to(cfg.lake_dir)) for p in cfg.lake_dir.rglob("*") if "locks" not in str(p))
    assert after == before and not (cfg.lake_dir / rb.ASIDE).exists()


def test_an_edc_store_not_yet_migrated_refuses_the_rebuild(tmp_path: Path, db_url: str) -> None:
    """D-1253 deep review (low): without ``tb_id_rule_study`` the rebuild would take every study for the earlier rule
    and stamp none, and EDC's later migration would stamp them rule 1 again. It refuses, as for the derived store:
    start the services once after the update."""
    cfg = _old_lake(tmp_path, NIGHTS)
    _tables(db_url)
    with Database.connect(db_url, "edc") as db:
        db.execute("DROP TABLE tb_id_rule_study")
    with pytest.raises(rb.Refused, match="EDC store is not migrated"):
        rb.rebuild(cfg.lake_dir, db_url, TODAY)
    assert (cfg.lake_dir / "CURRENT").exists() and snapshot_dir(cfg.lake_dir, "2026-11-01").is_dir()


@pytest.mark.parametrize("cmd", ["run", "backfill"])
def test_a_night_or_back_fill_from_the_command_line_is_kept_out_by_the_run_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], cmd: str
) -> None:
    """D-1253 deep review (low): ``adapter run`` and ``adapter backfill`` in a one-off container took no run lock, so
    the rebuild (which holds it) could not keep them out. They take it now: while it is held they refuse, reading
    and writing nothing."""
    from adapter import cli
    from adapter.runs import RunLock

    cfg = _old_lake(tmp_path, ("2026-10-01",))
    monkeypatch.setattr(cli, "build_config", lambda: (cfg, "csv", str(tmp_path / "feed")))
    ran: list[str] = []
    monkeypatch.setattr(cli, "run_ingest", lambda *a, **k: ran.append("run"))
    monkeypatch.setattr("adapter.backfill.backfill", lambda *a, **k: ran.append("backfill"))
    held = RunLock(cfg.lake_dir)
    try:
        assert cli.main([cmd]) == 2
    finally:
        held.release()
    assert ran == [] and "already running" in capsys.readouterr().err


def test_the_id_rule_record_is_synced_before_and_after_its_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-1253 deep review, finding 2: the record's bytes are synced to disk before the rename points the name at
    them, and the folder is synced after it, so a power cut leaves the whole record or none, never an empty one."""
    import os

    folder = tmp_path / "snap"
    folder.mkdir()
    seen: list[str] = []
    real_fsync, real_replace = os.fsync, Path.replace

    def fsync(fd: int) -> None:
        target = os.readlink(f"/proc/self/fd/{fd}")
        seen.append("folder" if Path(target) == folder else Path(target).name)
        real_fsync(fd)

    def replace(self: Path, target: Any) -> Any:
        seen.append("rename")
        return real_replace(self, target)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(Path, "replace", replace)
    id_rule.write_snapshot_record(folder)
    assert seen == [f".{id_rule.SNAPSHOT_RECORD}.tmp", "rename", "folder"]
    assert id_rule.snapshot_rule(folder) == id_rule.RULE
