"""Audit log after a torn write (D-127, review F-03): the next writer repairs it; the chain stays verifiable."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from tb_common.audit import AuditFull, AuditLog, verify

TZ = ZoneInfo("Asia/Taipei")


def _log(tmp_path: Path) -> tuple[AuditLog, Path]:
    log = AuditLog(tmp_path / "audit")
    t = datetime(2026, 11, 8, 10, 0, tzinfo=TZ)
    log.append("job.created", ts=t, job_id="J1")
    log.append("job.done", ts=t, job_id="J1")
    return log, tmp_path / "audit" / "2026-11-08.jsonl"


@pytest.mark.parametrize("tail", [b'{"event":"mark.saved","ts":"2026-11-08T10:', b"\x00\x00\x00", b"{broken}\n"])
def test_torn_or_unreadable_last_line_is_repaired_by_the_next_write(tmp_path: Path, tail: bytes) -> None:
    log, day = _log(tmp_path)
    with day.open("ab") as fh:  # power lost in the middle of a write, or a line of garbage
        fh.write(tail)
    assert not verify(tmp_path / "audit").ok
    log.append("mark.saved", ts=datetime(2026, 11, 8, 10, 5, tzinfo=TZ), actor="pi1")
    res = verify(tmp_path / "audit")
    assert res.ok, res.errors
    lines = [json.loads(x) for x in day.read_text().splitlines()]
    assert [x["event"] for x in lines] == ["job.created", "job.done", "audit.repaired", "mark.saved"]
    rep = lines[2]["detail"]
    kept = tmp_path / "audit" / rep["kept_as"]
    assert kept.read_bytes() == tail and rep["bytes"] == len(tail)  # the evidence is kept, not lost


def test_a_clean_log_is_not_touched(tmp_path: Path) -> None:
    log, day = _log(tmp_path)
    log.append("x", ts=datetime(2026, 11, 8, 11, 0, tzinfo=TZ))
    assert "audit.repaired" not in day.read_text() and not list((tmp_path / "audit").glob("*.torn-*"))


def test_full_disk_refuses_the_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log, day = _log(tmp_path)
    before = day.read_bytes()
    monkeypatch.setenv("TB_AUDIT_MIN_FREE_MB", str(10**12))
    with pytest.raises(AuditFull):
        log.append("x", ts=datetime(2026, 11, 8, 11, 0, tzinfo=TZ))
    assert day.read_bytes() == before
