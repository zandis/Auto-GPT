"""TB-PLAN-04 step 8 (D-138): log retention per type. Service logs are collected on the host and pruned after
``logs_days``; the audit chain is never deleted, only archived (copied, compressed, verified); mail logs are pruned
by the daily RETENTION job after ``mail_log_days``; the defaults come from the site's country at install."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from mail_gateway.store import MailDB
from tb_common.audit import AuditLog
from tb_common.retention import DEFAULTS, defaults_for
from tb_contracts import JobCreate

from tests.inproc_box import make_box
from tools.trialbox import logs as tl

ROOT = Path(__file__).resolve().parents[2]


def test_the_retention_days_are_read_from_either_settings_form(tmp_path: Path) -> None:
    flow = tmp_path / "a.yaml"
    flow.write_text("site: {id: X}\nretention: {attachments_days: 90, logs_days: 400, audit_years: 10}\n")
    block = tmp_path / "b.yaml"
    block.write_text(yaml.safe_dump({"site": {"id": "X"}, "retention": {"logs_days": 730, "mail_log_days": 1825}}))
    assert tl.retention_days(flow, "logs_days", 1) == 400
    assert tl.retention_days(block, "logs_days", 1) == 730
    assert tl.retention_days(block, "outputs_days", 7) == 7
    assert tl.retention_days(tmp_path / "none.yaml", "logs_days", 365) == 365
    assert tl.retention_days(ROOT / "deploy/settings.example.yaml", "logs_days", 1) == 365


def test_collect_writes_one_compressed_file_per_service_and_prune_keeps_the_window(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(argv: Any) -> bytes:
        calls.append(list(argv))
        if "ps" in argv:
            return b"orchestrator\nmail-gateway\n"
        return f"log of {argv[-1]}\n".encode()

    files = tl.collect(tmp_path / "deploy", date(2026, 11, 8), tmp_path / "logs", run, tz="UTC")
    assert sorted(f.name for f in files) == ["mail-gateway.log.gz", "orchestrator.log.gz"]
    assert gzip.decompress(files[1].read_bytes()) == b"log of orchestrator\n"
    assert calls[1][-5:-1] == ["--since", "2026-11-08T00:00:00Z", "--until", "2026-11-09T00:00:00Z"]
    for d in ("2025-11-08", "2025-11-09", "2026-01-01"):
        (tmp_path / "logs/services" / d).mkdir(parents=True)
    gone = tl.prune(tmp_path / "logs", 365, date(2026, 11, 9))
    assert gone == ["2025-11-08"]
    assert {p.name for p in (tmp_path / "logs/services").iterdir()} == {"2025-11-09", "2026-01-01", "2026-11-08"}


def _chain(audit: Path, days: int) -> None:
    log = AuditLog(audit, "UTC")
    start = datetime(2026, 11, 9, 12, tzinfo=UTC) - timedelta(days=days - 1)
    for i in range(days):
        for j in range(3):
            log.append("test.event", ts=start + timedelta(days=i, minutes=j), actor="tester", detail={"n": j})


def test_the_audit_is_archived_never_deleted(tmp_path: Path) -> None:
    audit, archive = tmp_path / "audit", tmp_path / "nas" / "audit-archive"
    _chain(audit, 4)
    before = {p.name: p.read_bytes() for p in audit.iterdir() if p.suffix == ".jsonl"}
    done = tl.archive_audit(audit, archive, date(2026, 11, 9))
    assert done == ["2026-11-06.jsonl", "2026-11-07.jsonl", "2026-11-08.jsonl"]  # today's file is still open
    assert {p.name: p.read_bytes() for p in audit.iterdir() if p.suffix == ".jsonl"} == before  # untouched
    assert gzip.decompress((archive / "2026/2026-11-07.jsonl.gz").read_bytes()) == before["2026-11-07.jsonl"]
    assert len((archive / "MANIFEST.sha256").read_text().splitlines()) == 3
    assert tl.archive_audit(audit, archive, date(2026, 11, 9)) == []  # nothing new
    assert tl.archive_audit(audit, archive, date(2026, 11, 10)) == ["2026-11-09.jsonl"]
    # a chain that does not verify is not archived: someone must look at it first
    f = audit / "2026-11-07.jsonl"
    f.write_text(f.read_text().replace('"n":1', '"n":9'))
    with pytest.raises(RuntimeError, match="does not verify"):
        tl.archive_audit(audit, archive, date(2026, 11, 10))


def test_daily_runs_all_three(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    _chain(tmp_path / "audit", 2)
    (deploy / ".env").write_text(f"TB_LOG_DIR={tmp_path / 'logs'}\nTB_AUDIT_HOST_DIR={tmp_path / 'audit'}\n"
                                 f"TB_AUDIT_ARCHIVE_DIR={tmp_path / 'arch'}\nIMAP_PASS=never-printed\nTB_TZ=UTC\n")  # fmt: skip
    (deploy / "settings.yaml").write_text("retention: {logs_days: 30}\n")
    (tmp_path / "logs/services/2026-09-01").mkdir(parents=True)

    def run(argv: Any) -> bytes:
        return b"gateway\n" if "ps" in argv else b"x\n"

    assert tl.main_action("daily", deploy, None, run, today=date(2026, 11, 9)) == 0
    out = capsys.readouterr().out
    assert "collected 1 service logs of 2026-11-08" in out and "kept 30 days; deleted: 2026-09-01" in out
    assert "1 day files" in out and "never-printed" not in out
    assert (tmp_path / "arch/2026/2026-11-08.jsonl.gz").is_file()


def test_mail_logs_are_pruned_but_an_unfinished_send_stays() -> None:
    db = MailDB()
    old, new = "2020-01-01T00:00:00+00:00", "2026-11-08T00:00:00+00:00"
    for mid, at in (("m-old", old), ("m-new", new)):
        db.record_intake(mid, "crc1@hospa.test", at, "job", "J1")
        db.record_sent(mid, "J1", "subject", ["pi@hospa.test"], "N1", at)
    db.claim_send("k-old-done", "J1", old)
    db.finish_send("k-old-done", "m-old", "{}", old)
    db.claim_send("k-old-open", "J1", old)  # started, never finished: a person must resolve it
    assert db.prune("2025-01-01T00:00:00+00:00") == {"intake": 1, "sent": 1, "send_keys": 1}
    assert db.intake("m-new") and not db.intake("m-old") and db.sent("m-new")
    assert db.db.fetchval("SELECT count(*) FROM send_keys WHERE key = 'k-old-open'") == 1
    db.close()


def test_the_retention_job_prunes_the_mail_logs(tmp_path: Path) -> None:
    sec = tmp_path / "sec"
    sec.mkdir()
    box = make_box(tmp_path / "box", tmp_path / "lake", sec, date(2026, 10, 5))
    db = MailDB()
    db.record_intake("m-ancient", "crc1@hospa.test", "2015-01-01T00:00:00+00:00", "job", "J0")
    db.record_intake("m-recent", "crc1@hospa.test", datetime.now(UTC).isoformat(), "job", "J0")
    created = box.orch.create(JobCreate(type="RETENTION", requested_by="scheduler"))
    box.orch.drain()
    job = box.orch.db.get(created.job_id)
    assert job is not None and job.state == "done", job and job.error
    assert not db.intake("m-ancient") and db.intake("m-recent")
    events = [json.loads(x) for f in sorted(box.audit_dir.glob("*.jsonl")) for x in f.read_text().splitlines()]
    mail = [e for e in events if e["event"] == "retention.mail"]
    assert mail and mail[0]["detail"]["rows"]["intake"] == 1
    db.close()


def test_install_defaults_follow_the_country_and_can_be_changed() -> None:
    from tools.settings_wizard import build

    answers = yaml.safe_load((ROOT / "tests/fixtures/onboarding/site_c_answers.yaml").read_text(encoding="utf-8"))
    answers["mapping"] = "mapping/tw_core/demo_his.yaml"  # a mapping this checkout has
    ja, _, _ = build({**answers, "locale": "ja"})
    tw, _, _ = build({**answers, "locale": "zh-TW"})
    own, _, _ = build({**answers, "retention_rules": "jp", "logs_days": "730", "mail_log_days": "3650"})
    assert ja["retention"] == DEFAULTS["jp"] and ja["retention"]["mail_log_days"] == 1825
    assert tw["retention"] == DEFAULTS["tw"] and tw["retention"]["mail_log_days"] == 2555
    assert own["retention"]["logs_days"] == 730 and own["retention"]["mail_log_days"] == 3650
    assert all(d["logs_days"] >= 180 and d["audit_years"] == 10 for d in DEFAULTS.values())  # TW: at least 6 months
    with pytest.raises(ValueError):
        defaults_for("us")
    with pytest.raises(ValueError):
        defaults_for("jp", {"logs_days": "0"})


def test_the_log_day_is_the_site_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """OPS-036 (D-315): a Tokyo box collects 00:00 to 24:00 Tokyo time, as its audit day files; no default zone."""
    assert tl.site_day_bounds(date(2026, 11, 8), "Asia/Tokyo") == ("2026-11-07T15:00:00Z", "2026-11-08T15:00:00Z")
    assert tl.site_day_bounds(date(2026, 11, 8), "Asia/Taipei") == ("2026-11-07T16:00:00Z", "2026-11-08T16:00:00Z")
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text(f"TB_LOG_DIR={tmp_path / 'logs'}\n")
    calls: list[list[str]] = []

    def run(argv: Any) -> bytes:
        calls.append(list(argv))
        return b"gateway\n" if "ps" in argv else b"x\n"

    monkeypatch.delenv("TB_TZ", raising=False)
    assert tl.main_action("collect", deploy, "2026-11-08", run) == 1  # no TB_TZ: refused, nothing collected
    assert calls == []
    (deploy / ".env").write_text(f"TB_LOG_DIR={tmp_path / 'logs'}\nTB_TZ=Asia/Tokyo\n")
    assert tl.main_action("collect", deploy, "2026-11-08", run) == 0
    assert calls[1][-5:-1] == ["--since", "2026-11-07T15:00:00Z", "--until", "2026-11-08T15:00:00Z"]
