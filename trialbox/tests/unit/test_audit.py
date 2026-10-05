from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from tb_common.audit import GENESIS, AuditLog, verify

TZ = ZoneInfo("Asia/Taipei")


def test_chain_appends_and_verifies(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    r1 = log.append("job.received", job_id="01J0000000000000000000000A", actor="crc1@hospa.test")
    r2 = log.append("job.state", job_id="01J0000000000000000000000A", detail={"state": "running"})
    assert r1["prev_hash"] == GENESIS
    assert r2["prev_hash"] == r1["hash"]
    res = verify(tmp_path)
    assert res.ok, res.errors
    assert res.lines == 2 and res.last_hash == r2["hash"]


def test_unknown_fields_go_to_detail(tmp_path: Path) -> None:
    rec = AuditLog(tmp_path).append("x", phi_guard_hit=True, recipients=["a@b"])
    assert rec["detail"] == {"phi_guard_hit": True}
    assert rec["recipients"] == ["a@b"]


def test_daily_files_are_chained(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    d0 = datetime(2026, 10, 1, 23, 59, tzinfo=TZ)
    a = log.append("a", ts=d0)
    b = log.append("b", ts=d0 + timedelta(minutes=2))
    files = sorted(p.name for p in tmp_path.glob("*.jsonl"))
    assert files == ["2026-10-01.jsonl", "2026-10-02.jsonl"]
    assert b["prev_hash"] == a["hash"]
    assert verify(tmp_path).ok


def test_tamper_detected(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    for i in range(5):
        log.append("e", job_id=f"J{i}")
    day = next(tmp_path.glob("*.jsonl"))
    lines = day.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[2])
    rec["job_id"] = "EVIL"
    lines[2] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    day.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = verify(tmp_path)
    assert not res.ok
    assert any(":3: hash mismatch" in e for e in res.errors)


def test_deleted_line_detected(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    for i in range(4):
        log.append("e", job_id=f"J{i}")
    day = next(tmp_path.glob("*.jsonl"))
    lines = day.read_text(encoding="utf-8").splitlines()
    del lines[1]
    day.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = verify(tmp_path)
    assert not res.ok and any("prev_hash" in e for e in res.errors)


def test_concurrent_writers_keep_one_chain(tmp_path: Path) -> None:
    def worker(n: int) -> None:
        log = AuditLog(tmp_path)
        for i in range(25):
            log.append("concurrent", job_id=f"{n}-{i}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    res = verify(tmp_path)
    assert res.ok, res.errors[:5]
    assert res.lines == 100


def test_naive_timestamp_rejected(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError):
        AuditLog(tmp_path).append("x", ts=datetime(2026, 1, 1))


def test_audit_verify_cli(tmp_path: Path, repo_root: Path) -> None:
    AuditLog(tmp_path).append("x")
    out = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "audit_verify.py"), str(tmp_path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["ok"] is True
