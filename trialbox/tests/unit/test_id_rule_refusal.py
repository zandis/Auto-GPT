"""D-1253 product regressions using synthetic stores and snapshots."""

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


def test_refusal_probes_the_configured_omop_database(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adapter.pipeline import check_id_rule
    from omop.schema import schema_for

    cfg = _old_lake(tmp_path)
    id_rule.write_snapshot_record(snapshot_dir(cfg.lake_dir, "2026-10-01"))
    url = db_url.replace("tb_prefix=", "tb_prefix=omopdb_")
    monkeypatch.setenv("TB_OMOP_DB_URL", url)
    with Database.connect(url, schema_for(cfg.lake_dir)) as db:
        db.execute("CREATE TABLE tb_record (source_kind TEXT, resource_type TEXT)")
        db.execute("INSERT INTO tb_record VALUES ('feed', 'Condition')")
        with pytest.raises(id_rule.IdRuleError, match="full ingest from the source") as refused:
            check_id_rule(cfg)
        assert refused.value.stores == ["the omop store"]
        assert db.fetchall("SELECT source_kind, resource_type FROM tb_record") == [("feed", "Condition")]


NIGHTS = ("2026-09-29", "2026-09-30", "2026-11-01")  # 2026-09-30: September's month-end, kept under retention


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


def test_retention_and_ingest_refuse_an_archived_old_month_end(tmp_path: Path) -> None:
    from adapter.pipeline import check_id_rule, prune_lake

    cfg = _old_lake(tmp_path, ("2026-09-30",))
    _stage_aside(cfg)
    aside = cfg.lake_dir / "id_rule_1"
    before = {p: p.read_bytes() for p in aside.rglob("*") if p.is_file()}
    assert before
    for today in (date(2027, 1, 5), date(2030, 1, 5)):
        with pytest.raises(id_rule.IdRuleError, match="full ingest from the source"):
            prune_lake(cfg, today)
    with pytest.raises(id_rule.IdRuleError, match="full ingest from the source"):
        check_id_rule(cfg)
    assert {p: p.read_bytes() for p in aside.rglob("*") if p.is_file()} == before


def _stage_aside(cfg: AdapterConfig) -> None:
    """A retained month end archived before this release."""
    aside = cfg.lake_dir / "id_rule_1"
    for name in ("ndjson", "db", "parquet"):
        for path in sorted((cfg.lake_dir / name).rglob("*")):
            if path.exists() and "2026-09-30" in path.name:
                dest = aside / path.relative_to(cfg.lake_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                path.rename(dest)


@pytest.mark.parametrize("cut", ["", '{"ru', '{"rule": '], ids=["empty", "cut-key", "cut-value"])
def test_a_cut_id_rule_record_has_one_instruction_from_ingest_and_snapshot_read(tmp_path: Path, cut: str) -> None:
    """D-1253 deep review: both checks identify an unreadable record and leave the snapshot intact."""
    from adapter.pipeline import check_id_rule

    cfg = _old_lake(tmp_path, NIGHTS)
    for night in NIGHTS:
        id_rule.write_snapshot_record(snapshot_dir(cfg.lake_dir, night))  # a lake of this rule
    (snapshot_dir(cfg.lake_dir, "2026-11-01") / id_rule.SNAPSHOT_RECORD).write_text(cut)
    words = id_rule.unreadable_words(["the lake snapshot 2026-11-01"])
    with pytest.raises(id_rule.IdRuleError) as at_night:
        check_id_rule(cfg)
    assert str(at_night.value) == words and "rebuild" not in words.split("(")[0].lower()
    before = sorted(str(p.relative_to(cfg.lake_dir)) for p in cfg.lake_dir.rglob("*") if "locks" not in str(p))
    with pytest.raises(id_rule.IdRuleError) as refused:
        id_rule.open_snapshot(snapshot_dir(cfg.lake_dir, "2026-11-01"))
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
        taken = sorted(r.removeprefix("id_rule_1" + "/") for r in keep if "2026-09-30" in r)
        everything = sorted(str(p.relative_to(root)).removeprefix("id_rule_1" + "/") for p in root.rglob("*")
                            if p.is_file() and "2026-09-30" in str(p))  # fmt: skip
        return taken, sorted(set(everything) - set(taken))

    before = of_month_end(cfg.lake_dir)
    assert any(r.startswith("ndjson/2026-09-30/") and r.endswith(".ndjson") for r in before[1])  # left out before
    _stage_aside(cfg)
    after = of_month_end(cfg.lake_dir)
    assert after == before


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


def test_ssmix2_orders_keyed_another_way_are_rebuilt_under_the_readers_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-1253 review ruling 11: the SS-MIX2 order key is the reader's (#1238 keys ``<number>@<type>``). Each snapshot
    records the key form its ids were made from. A delta night cannot merge incompatible keys. A full night
    reads every order under the new key and preserves the earlier snapshot."""
    from adapter.sources.ssmix2 import source as ss

    from tests.unit import test_lake_ids_per_patient as ids

    old = ids.night(tmp_path, "ssmix2", ids.canonical(ids.A), "2026-10-01")
    assert old.passed, old.errors
    lake = tmp_path / "lake"
    assert id_rule.snapshot_keys(snapshot_dir(lake, "2026-10-01")) == {"ssmix2_order": "<number>@<day>"}
    monkeypatch.setitem(ss.ORDER_ID_FORMS, "per_day", "<number>@<type>@<day>")  # the reader's new key
    held = ids.night(tmp_path, "ssmix2", ids.canonical(ids.A), "2026-10-02", since="2026-10-01")
    assert not held.passed and any("keyed <number>@<day>" in e for e in held.errors), held.errors
    new = ids.night(tmp_path, "ssmix2", ids.canonical(ids.A), "2026-10-03")
    assert new.passed, new.errors
    assert id_rule.snapshot_keys(snapshot_dir(lake, "2026-10-03")) == {"ssmix2_order": "<number>@<type>@<day>"}


def test_a_stewards_rejection_of_a_number_two_charts_shared_is_kept_and_both_rebuilt_records_await_review(
    tmp_path: Path, db_url: str
) -> None:
    """D-1253 review ruling 1. Under the earlier rule two charts' diagnosis ``D1`` were one record, and a steward
    rejected it. Which chart the rejection meant cannot be told, so it is never carried over by guess and never
    deleted: the decision stays with its history, and both records the next full night makes from ``D1`` are proposed
    (never coded) and marked for a steward's review. ``D2`` (nobody decided it) is coded as before."""
    from adapter.mapping.engine import BASIS, resource_id
    from omop.load import load_batch, set_status
    from omop.schema import schema_for

    cfg = _old_lake(tmp_path)
    with (tmp_path / "feed" / "diagnosis.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["diag_no", "enc_no", "mrn", "icd10", "diag_date", "recorded_date", "status"])
        w.writerow(["D1", "E1", "10000001", "M10.9", "2026-09-01", "2026-09-01", "A"])
        w.writerow(["D1", "E7", "10000002", "J45.9", "2026-09-03", "2026-09-03", "A"])  # another chart, one number
        w.writerow(["D2", "E1", "10000001", "E11.9", "2026-09-01", "2026-09-01", "A"])
    earlier = resource_id(KEY, "Condition", "D1")  # the one id both charts' D1 had under the earlier rule
    key = ("feed", "Condition", earlier, 0)
    from omop import schema

    with schema.connect(db_url, schema_for(cfg.lake_dir)) as db:
        load_batch(db, "feed", "2026-10-01", {
            "Patient": [{"resourceType": "Patient", "id": "P1", "birthDate": "1960-01-01", "gender": "female"}],
            "Condition": [{"resourceType": "Condition", "id": earlier, "subject": {"reference": "Patient/P1"},
                           "code": {"coding": [{"system": ICD, "code": "M10.9"}]}, "onsetDateTime": "2026-09-01"}],
        }, tz="Asia/Taipei")  # fmt: skip
        set_status(db, key, "rejected", by="steward-1", reason="not this patient's diagnosis")
        db.execute("DELETE FROM tb_id_rule")  # the store as the release before D-1253 left it
        history = db.fetchall("SELECT event, actor, reason FROM tb_record_event e JOIN tb_record r USING (record_key) "
                              "WHERE r.source_record_id = ? ORDER BY event_id", (earlier,))  # fmt: skip
    old_lake = cfg.lake_dir
    with pytest.raises(id_rule.IdRuleError, match="full ingest from the source"):
        run_ingest(cfg, "csv", str(tmp_path / "feed"), snapshot="2026-10-02", load_fhir=False, validate=False)
    with schema.connect(db_url, schema_for(cfg.lake_dir)) as db:
        row = db.fetchone("SELECT source_kind, status, record_id FROM tb_record WHERE source_record_id = ?", (earlier,))
        assert row is not None and row[:2] == ("feed", "rejected")
        after = db.fetchall("SELECT event, actor, reason FROM tb_record_event e JOIN tb_record r USING (record_key) "
                            "WHERE r.source_record_id = ? ORDER BY event_id", (earlier,))  # fmt: skip
    assert after[: len(history)] == history and ("status", "steward-1", "not this patient's diagnosis") in after
    assert after == history
    cfg.lake_dir = tmp_path / "fresh"
    cfg.lake_dir.mkdir()
    id_rule.write_review(cfg.lake_dir / id_rule.REVIEW, [("Condition", earlier, "rejected")])
    assert id_rule.read_review(cfg.lake_dir) == {("Condition", earlier)}

    rep = run_ingest(cfg, "csv", str(tmp_path / "feed"), snapshot="2026-10-02", load_fhir=False, validate=False)
    assert rep.passed, rep.errors
    conds = list(read_type(snapshot_dir(cfg.lake_dir, "2026-10-02"), "Condition"))
    by_code = {r["code"]["coding"][0]["code"]: r for r in conds}
    assert len(conds) == 3
    for code in ("M10.9", "J45.9"):  # both charts' D1: proposed, marked for review
        tags = by_code[code]["meta"]["tag"]
        assert {"system": BASIS, "code": "proposed"} in tags and id_rule.REVIEW_TAG in tags, code
    assert not any(t.get("system") in (BASIS, id_rule.REVIEW_TAG["system"]) for t in by_code["E11.9"]["meta"]["tag"])
    events = [json.loads(line) for f in sorted((tmp_path / "audit").rglob("*.jsonl")) for line in f.open()]
    night = [e for e in events if str(e.get("event", "")).startswith("ingest.")][-1]
    assert night["detail"]["steward_review_needed"] == {"diagnosis": 2}  # the batch row keeps it (DETAIL_KEYS)

    # what the lake and the OMOP store read from them: a proposed fact, never coded (D-135), until a steward reviews
    from lake.flatten import basis_of
    from omop.load import status_for

    assert sorted(status_for(basis_of(r)) for r in conds) == ["coded", "proposed", "proposed"]
    with schema.connect(db_url, schema_for(old_lake)) as db:  # the kept decision is untouched by the night
        assert db.fetchone("SELECT source_kind, status FROM tb_record WHERE source_record_id = ?", (earlier,)) == (
            "feed",
            "rejected",
        )
