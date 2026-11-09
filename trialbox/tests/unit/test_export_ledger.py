"""Export ledger v1 (dataflow review P0-8, D-149): every file that leaves the box is a ``flow.export`` row with its
identifier level, the approval it left under and its sha256, and the steward can list the last 30 days."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.core import Ctx
from tb_common.audit import AuditLog, verify
from tb_common.flowledger import exports, record_export
from tb_contracts import Job

from tools.trialbox.__main__ import main as trialbox_main


class _Store:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, ctype: str) -> None:
        self.objects[key] = data


class _Db:
    def put(self, job: Job) -> None:
        pass


def _ctx(audit: AuditLog, **job: Any) -> Ctx:
    j = Job.model_validate(
        {
            "job_id": "01JABCDEFGHJKMNPQRSTVWXYZ0",
            "type": "SCREEN",
            "requested_by": "pi@hosp.example",
            "received_at": datetime(2026, 11, 9, 9, tzinfo=UTC).isoformat(),
            "state": "reporting",
            **job,
        }
    )
    return Ctx(SimpleNamespace(store=_Store(), audit=audit, db=_Db()), j)  # type: ignore[arg-type]


def test_every_job_output_is_a_ledger_row_with_level_approval_and_sha(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit")
    ctx = _ctx(audit, ruleset="GOUT-COH", ruleset_version="1.2.0", snapshot_date="2026-11-08")
    ctx.publish("candidates.xlsx", b"PK patient list", "phi", ["pi@hosp.example", "crc@hosp.example"])
    ctx.publish("funnel.pdf", b"%PDF counts", "aggregate", ["pi@hosp.example"])
    rows = exports(tmp_path / "audit")
    assert [(r.filename, r.identifier_level, r.channel) for r in rows] == [
        ("candidates.xlsx", "identified", "job_output"),
        ("funnel.pdf", "aggregate", "job_output"),
    ]
    assert rows[0].sha256 == hashlib.sha256(b"PK patient list").hexdigest() and rows[0].bytes == 15
    assert rows[0].recipients == ["crc@hosp.example", "pi@hosp.example"]
    assert rows[0].approval == "ruleset GOUT-COH@1.2.0; job SCREEN requested by pi@hosp.example"
    assert rows[0].ruleset == "GOUT-COH" and rows[0].job_id == "01JABCDEFGHJKMNPQRSTVWXYZ0"
    assert verify(tmp_path / "audit").ok  # the rows are part of the hash chain


def test_an_export_without_approval_or_level_is_refused(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit")
    with pytest.raises(ValueError, match="approval"):
        record_export(audit, channel="job_output", filename="x", data=b"x", identifier_level="aggregate", approval=" ")
    with pytest.raises(ValueError, match="identifier_level"):
        record_export(audit, channel="job_output", filename="x", data=b"x", identifier_level="secret", approval="a")
    assert exports(tmp_path / "audit") == []


def test_the_steward_lists_what_left_in_the_last_30_days(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    audit = AuditLog(tmp_path / "audit")
    old = datetime.now(UTC) - timedelta(days=40)
    audit.append("flow.export", ts=old, output_sha="0" * 64, detail={"channel": "job_output", "filename": "old.xlsx",
                 "bytes": 1, "identifier_level": "identified", "approval": "ruleset A@1"})  # fmt: skip
    record_export(audit, channel="registry_export", filename="screening_log_A.xlsx", data=b"log",
                  identifier_level="identified", approval="study A screening log", actor="pi")  # fmt: skip
    assert trialbox_main(["exports", "--audit", str(tmp_path / "audit")]) == 0
    out = capsys.readouterr().out
    assert "screening_log_A.xlsx" in out and "old.xlsx" not in out and "1 exports in the last 30 days" in out
