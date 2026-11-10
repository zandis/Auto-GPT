"""T-612 (DATA-004): the site key is made only by the install ceremony; a night under a missing or changed key is
refused before anything is read or written; ``doctor`` reports it.

The deep review's ``trace_key.py`` run: an opt-out under key A, then a night with the key gone. Before T-612 the
adapter made a new key, the night passed, every patient got a new pseudonym and the opted-out patient was back.
Now the second night is refused (key missing, or another key in its place), no pseudonym changes, and the opt-out
still names the patient when the site's own key is put back.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from adapter.cli import keys_init
from adapter.ndjson import snapshot_dir
from adapter.pidmap import PidMap
from adapter.pipeline import SITE_KEY_RECORD, AdapterConfig, SiteKeyError, run_ingest
from tb_common.crypto import KeyMissingError, create_key, key_fingerprint, load_key
from tb_common.db import Database
from tb_common.optout import OptOutRegister
from tb_contracts import RebuildResult

from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
SITE_A = ROOT / "tests/fixtures/synthetic_patients/site-a"
MAPPING = ROOT / "services/adapter/mapping/tw_core/demo_his.yaml"
KEY_A = b"a" * 32
KEY_B = b"b" * 32
FIRST, SECOND = "2026-11-01", "2026-11-02"


def _rebuild(lake_dir: Path) -> Any:
    def go(snap: str, nd: Path) -> RebuildResult:
        (lake_dir / "CURRENT").write_text(snap)
        return RebuildResult(snapshot=snap, tables={}, chunks=0, embedded_new=0, seconds=0.0)

    return go


def _cfg(tmp: Path) -> AdapterConfig:
    sec = tmp / "secrets"
    sec.mkdir(exist_ok=True)
    return AdapterConfig(lake_dir=tmp / "lake", secrets_dir=sec, mapping_path=MAPPING, site_id="T",
                         audit_dir=tmp / "audit", rebuild=_rebuild(tmp / "lake"))  # fmt: skip


def _night(cfg: AdapterConfig, feed: Path, snap: str) -> Any:
    return run_ingest(cfg, "csv", str(feed), snapshot=snap, load_fhir=False, validate=False)


def _feed(tmp: Path) -> Path:
    dst = tmp / "feed"
    shutil.copytree(SITE_A, dst, ignore=shutil.ignore_patterns("*.json"))
    return dst


def _pids(cfg: AdapterConfig, snap: str) -> set[str]:
    path = snapshot_dir(cfg.lake_dir, snap) / "Patient.ndjson"
    return {json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _map_rows() -> list[tuple[str, str]]:
    with Database.connect(os.environ["TB_DB_URL"], "pidmap") as db:
        return [(str(k), str(p)) for k, p in db.fetchall("SELECT key_id, pid FROM pid_map ORDER BY key_id, pid")]


def _audit(tmp: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for f in sorted((tmp / "audit").glob("*.jsonl")) for x in f.read_text().splitlines()]


def _assert_refused_and_nothing_written(cfg: AdapterConfig, tmp: Path, rows: list[tuple[str, str]], why: str) -> None:
    feed = tmp / "feed"
    with pytest.raises(SiteKeyError, match=why):
        _night(cfg, feed, SECOND)
    assert not snapshot_dir(cfg.lake_dir, SECOND).exists()  # no NDJSON, no report, no held folder
    assert (cfg.lake_dir / "CURRENT").read_text().strip() == FIRST
    assert _map_rows() == rows  # no new pseudonym in the pid map
    ev = _audit(tmp)[-1]
    assert ev["event"] == "ingest.failed" and ev["detail"]["refused"] == "site_key"
    assert KEY_A.decode() not in json.dumps(ev) and KEY_B.decode() not in json.dumps(ev)


def test_a_lost_site_key_refuses_the_second_night_and_the_opt_out_survives(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    key = cfg.secrets_dir / "site_hmac.key"
    key.write_bytes(KEY_A)
    feed = _feed(tmp_path)
    assert _night(cfg, feed, FIRST).passed
    pids = _pids(cfg, FIRST)
    rows = _map_rows()
    assert len(rows) == len(pids) == 600 and len({k for k, _ in rows}) == 1
    out = sorted(pids)[0]
    reg = OptOutRegister()
    reg.add(out, "paper", "", "test:office", datetime(2026, 11, 1, 12, tzinfo=UTC).isoformat())

    key.unlink()  # a re-installed box, a wrong volume mount, a restore without the secrets
    _assert_refused_and_nothing_written(cfg, tmp_path, rows, "site key .* is missing")
    assert not key.exists()  # never made on first use

    key.write_bytes(KEY_B)  # a new key made by hand in its place
    _assert_refused_and_nothing_written(cfg, tmp_path, rows, "not the key this box's pseudonyms were made with")

    key.write_bytes(KEY_A)  # the site's own key back from the backup: the night runs, nobody's pseudonym changed
    rep = _night(cfg, feed, SECOND)
    assert rep.passed, rep.errors
    assert _pids(cfg, SECOND) == pids
    assert _map_rows() == rows
    assert out in reg.active() and out in _pids(cfg, SECOND)  # the opt-out still names the patient
    reg.close()


def test_a_box_from_before_the_record_is_checked_against_its_pid_map(tmp_path: Path) -> None:
    """No ``site_key.json`` and no stored fingerprint (a box that ran before T-612): the pid map's rows decide."""
    cfg = _cfg(tmp_path)
    key = cfg.secrets_dir / "site_hmac.key"
    key.write_bytes(KEY_A)
    assert _night(cfg, _feed(tmp_path), FIRST).passed
    rows = _map_rows()
    (cfg.lake_dir / SITE_KEY_RECORD).unlink()
    with Database.connect(os.environ["TB_DB_URL"], "pidmap") as db:
        db.execute("DELETE FROM site_key")
    key.write_bytes(KEY_B)
    _assert_refused_and_nothing_written(cfg, tmp_path, rows, "does not give the pseudonyms the pid map holds")
    key.write_bytes(KEY_A)
    assert _night(cfg, tmp_path / "feed", SECOND).passed  # and the record is written again
    assert json.loads((cfg.lake_dir / SITE_KEY_RECORD).read_text())["fingerprint"] == key_fingerprint(KEY_A)


def test_the_lake_record_alone_refuses_another_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a trial database (a ``fhir_bulk`` night needs none) the lake's record still refuses another key."""
    cfg = _cfg(tmp_path)
    cfg.lake_dir.mkdir(parents=True)
    (cfg.lake_dir / SITE_KEY_RECORD).write_text(json.dumps({"fingerprint": key_fingerprint(KEY_A)}))
    (cfg.secrets_dir / "site_hmac.key").write_bytes(KEY_B)
    monkeypatch.delenv("TB_DB_URL")
    with pytest.raises(SiteKeyError, match="the lake's snapshots were written under key"):
        run_ingest(cfg, "fhir_bulk", str(tmp_path / "none"), snapshot=SECOND, load_fhir=False, validate=False)
    assert list(cfg.lake_dir.iterdir()) == [cfg.lake_dir / SITE_KEY_RECORD]


def test_pid_map_records_the_first_key_and_never_replaces_it(tmp_path: Path) -> None:
    pm = PidMap(tmp_path / "pid_map.key")
    assert pm.stored_site_key("T") is None and pm.site_key_problem("T", KEY_A) is None
    pm.record_site_key("T", KEY_A)
    pm.record_site_key("T", KEY_B)
    assert pm.stored_site_key("T") == key_fingerprint(KEY_A)
    assert "differs from the stored one" in (pm.site_key_problem("T", KEY_B) or "")
    assert pm.site_key_problem("U", KEY_B) is None  # another site in the same database
    pm.close()


def test_keys_init_makes_each_key_once_and_prints_no_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sec = tmp_path / "secrets"
    assert keys_init(sec) == 0
    first = (sec / "site_hmac.key").read_bytes(), (sec / "pid_map.key").read_bytes()
    assert len(first[0]) == 32 and first[0] != first[1]
    assert (sec / "site_hmac.key").stat().st_mode & 0o777 == 0o600
    out = capsys.readouterr().out
    assert out.count("made") == 2 and key_fingerprint(first[0]) in out and first[0].hex() not in out
    assert keys_init(sec) == 0  # the ceremony run again keeps both
    assert ((sec / "site_hmac.key").read_bytes(), (sec / "pid_map.key").read_bytes()) == first
    assert capsys.readouterr().out.count("kept") == 2
    (sec / "pid_map.key").write_bytes(b"")
    assert keys_init(sec) == 1 and (sec / "pid_map.key").read_bytes() == b""  # an empty key is never overwritten


def test_load_key_never_makes_a_key(tmp_path: Path) -> None:
    with pytest.raises(KeyMissingError):
        load_key(tmp_path / "site_hmac.key")
    assert not (tmp_path / "site_hmac.key").exists()
    assert create_key(tmp_path / "site_hmac.key") and not create_key(tmp_path / "site_hmac.key")


def _doctor(tmp: Path, **env: str) -> doctor.Check:
    base = {"TB_ENV": "DEV", "TB_SECRETS_DIR": str(tmp / "secrets"), "TB_LAKE_DIR": str(tmp / "lake")}
    inp = doctor.DoctorInputs(env={**base, **env}, settings={"site": {"id": "T"}}, host_tz="Asia/Taipei")
    return next(c for c in doctor.run(inp, (doctor.check_site_key,)))


def test_doctor_reports_the_site_key(tmp_path: Path) -> None:
    assert _doctor(tmp_path).status == "WARN"  # no secrets folder on this host
    (tmp_path / "secrets").mkdir()
    c = _doctor(tmp_path)
    assert c.status == "FAIL" and "refuses every night" in c.detail
    (tmp_path / "secrets" / "site_hmac.key").write_bytes(KEY_A)
    c = _doctor(tmp_path)
    assert c.status == "PASS" and key_fingerprint(KEY_A) in c.detail and "no night" in c.detail
    (tmp_path / "lake").mkdir()
    (tmp_path / "lake" / SITE_KEY_RECORD).write_text(json.dumps({"fingerprint": key_fingerprint(KEY_A)}))
    pm = PidMap(tmp_path / "secrets" / "pid_map.key")
    pm.record_site_key("T", KEY_A)
    pm.close()
    c = _doctor(tmp_path, TB_DB_URL=os.environ["TB_DB_URL"])
    assert c.status == "PASS" and "the lake and the pid map" in c.detail
    assert KEY_A.decode() not in c.detail
    (tmp_path / "secrets" / "site_hmac.key").write_bytes(KEY_B)
    c = _doctor(tmp_path, TB_DB_URL=os.environ["TB_DB_URL"])
    assert c.status == "FAIL" and "is not the lake's" in c.detail
    (tmp_path / "lake" / SITE_KEY_RECORD).unlink()
    c = _doctor(tmp_path, TB_DB_URL=os.environ["TB_DB_URL"])
    assert c.status == "FAIL" and "is not the pid map's" in c.detail
