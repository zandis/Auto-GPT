"""Candidate registry (D-92): transitions, pseudonym resolution, promotion from the SCREEN pool, the screening-log
export with in-box chart numbers, and the audit records. No orchestrator run needed."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from adapter.pidmap import PidMap
from console.backend import read_audit
from openpyxl import load_workbook
from orchestrator.candidates import FORWARD, STATUSES, CandidateRegistry, RegistryError, counts
from orchestrator.db import JobDB
from tb_common.audit import AuditLog, verify
from tb_common.crypto import pid_for_mrn
from tb_contracts import RegistryPromote, RegistryUpdate

KEY = b"trialbox-test-site-key-0123456789abcdef"
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


@pytest.fixture
def reg(tmp_path: Path) -> CandidateRegistry:
    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    pm = PidMap(sec / "pid_map.sqlite", sec / "pid_map.key")
    pm.upsert_many([(pid_for_mrn(KEY, m), m) for m in ("10000001", "10000002", "10000003")])
    pm.close()
    db = JobDB(tmp_path / "jobs.sqlite")
    db.pool_upsert(
        "GZQO",
        "1.0.0",
        [
            {"pid": pid_for_mrn(KEY, "10000001"), "tier": "high", "verdicts": []},
            {"pid": pid_for_mrn(KEY, "10000002"), "tier": "review", "verdicts": []},
            {"pid": pid_for_mrn(KEY, "10000003"), "tier": "low", "verdicts": []},
        ],
        "01JOBSCREEN",
        NOW.isoformat(),
    )
    return CandidateRegistry(db, AuditLog(tmp_path / "audit"), sec, r"^\d{8}$")


def _upd(**kw: object) -> RegistryUpdate:
    base: dict[str, object] = {"status": "candidate", "by": "crc1@hospa.test", "source": "manual"}
    return RegistryUpdate.model_validate({**base, **kw})


def test_add_by_chart_number_stores_only_the_pseudonym(reg: CandidateRegistry) -> None:
    row = reg.update("gzqo", _upd(mrn="10000001", reason="referred"), NOW)
    assert row.pid == pid_for_mrn(KEY, "10000001") and row.ruleset == "GZQO" and row.events == 1
    assert "10000001" not in str(reg.db.candidates("GZQO"))
    assert reg.summaries()[0].counts == {"candidate": 1}
    with pytest.raises(RegistryError, match="chart number of this site"):
        reg.update("GZQO", _upd(mrn="abc"), NOW)
    with pytest.raises(RegistryError, match="not both"):
        reg.update("GZQO", _upd(mrn="10000001", pid="ab" * 16), NOW)
    with pytest.raises(RegistryError, match="hex"):
        reg.update("GZQO", _upd(pid="zz"), NOW)
    with pytest.raises(RegistryError, match="invalid ruleset"):
        reg.update("bad id!", _upd(mrn="10000001"), NOW)


def test_transitions_are_recorded_and_checked(reg: CandidateRegistry) -> None:
    pid = pid_for_mrn(KEY, "10000001")
    reg.update("GZQO", _upd(mrn="10000001"), NOW)
    with pytest.raises(RegistryError, match="add a reason"):
        reg.update("GZQO", _upd(pid=pid), NOW)  # same status, no note
    reg.update("GZQO", _upd(pid=pid, reason="called twice"), NOW)  # same status with a note is a recorded note
    with pytest.raises(RegistryError, match="not a recorded transition"):
        reg.update("GZQO", _upd(pid=pid, status="enrolled"), NOW)  # candidate -> enrolled skips consent
    for st in ("contacted", "consented", "enrolled"):
        reg.update("GZQO", _upd(pid=pid, status=st), NOW)
    with pytest.raises(RegistryError):
        reg.update("GZQO", _upd(pid=pid, status="declined"), NOW)  # enrolled is final unless withdrawn
    reg.update("GZQO", _upd(pid=pid, status="withdrawn", reason="moved away"), NOW)
    ev = reg.events("GZQO", pid)
    assert [e.status for e in ev] == ["candidate", "candidate", "contacted", "consented", "enrolled", "withdrawn"]
    assert ev[-1].previous == "enrolled" and ev[-1].reason == "moved away"
    assert reg.rows("GZQO")[0].events == 6
    assert set(FORWARD) == set(STATUSES)
    audit = [r for r in read_audit(reg.audit.directory, limit=50) if r.event == "registry.update"]
    assert len(audit) == 6
    assert verify(reg.audit.directory).ok


def test_promote_takes_high_and_review_tiers_once(reg: CandidateRegistry) -> None:
    assert reg.promote("GZQO", RegistryPromote(by="pi@hospa.test", tiers=["high"]), NOW) == 1
    assert reg.promote("GZQO", RegistryPromote(by="pi@hospa.test"), NOW) == 1  # the review tier joins; high once
    rows = {r.pid: r for r in reg.rows("GZQO")}
    assert {r.tier for r in rows.values()} == {"high", "review"}  # the low tier is never promoted (schema)
    assert all(
        r.source == "screen" and r.source_job == "01JOBSCREEN" and r.status == "candidate" for r in rows.values()
    )
    assert reg.promote("GZQO", RegistryPromote(by="pi@hospa.test"), NOW) == 0  # idempotent
    with pytest.raises(ValueError):
        RegistryPromote(by="pi@hospa.test", tiers=["low"])  # type: ignore[list-item]
    assert counts(reg.rows("GZQO")) == {**dict.fromkeys(STATUSES, 0), "candidate": 2}
    assert reg.promote("OTHER", RegistryPromote(by="pi@hospa.test"), NOW) == 0  # no pool, nothing to add


def test_export_resolves_chart_numbers_in_box_and_is_deterministic(reg: CandidateRegistry) -> None:
    reg.promote("GZQO", RegistryPromote(by="pi@hospa.test"), NOW)
    reg.update("GZQO", _upd(pid=pid_for_mrn(KEY, "10000001"), status="contacted", reason="phone"), NOW)
    data = reg.export_xlsx("GZQO", "DEMO-A")
    assert data == reg.export_xlsx("GZQO", "DEMO-A")
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["screening_log", "events", "about"]
    log = list(wb["screening_log"].iter_rows(values_only=True))
    assert log[0][:3] == ("MRN", "pid", "status")
    by_mrn = {r[0]: r for r in log[1:]}
    assert set(by_mrn) == {"10000001", "10000002"}
    assert by_mrn["10000001"][2] == "contacted" and by_mrn["10000001"][3] == "phone"
    events = list(wb["events"].iter_rows(values_only=True))
    assert len(events) == 4 and events[0][0] == "at"
    # without a pid map the export still works, with blank chart numbers
    (reg.secrets_dir / "pid_map.sqlite").unlink()
    wb2 = load_workbook(io.BytesIO(reg.export_xlsx("GZQO", "DEMO-A")))
    assert all(r[0] in ("", None) for r in list(wb2["screening_log"].iter_rows(values_only=True))[1:])


def test_registry_api_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The orchestrator's registry endpoints map errors to 400 and return the generated models."""
    from fastapi.testclient import TestClient
    from orchestrator import app as oapp

    reg = _reg_for_api(tmp_path)

    fake = SimpleNamespace(
        db=reg.db,
        audit=reg.audit,
        cfg=SimpleNamespace(
            env=SimpleNamespace(secrets_dir=str(reg.secrets_dir)),
            settings=SimpleNamespace(mrn_regex=r"^\d{8}$", site=SimpleNamespace(tz="Asia/Taipei", id="DEMO-A")),
        ),
    )
    monkeypatch.setattr(oapp, "orch", lambda: fake)
    c = TestClient(oapp.app)
    r = c.post("/registry/GZQO", json={"mrn": "10000001", "status": "candidate", "by": "crc1@hospa.test"})
    assert (
        r.status_code == 200 and r.json()["status"] == "candidate" and r.json()["pid"] == pid_for_mrn(KEY, "10000001")
    )
    assert c.post("/registry/GZQO", json={"mrn": "x", "status": "candidate", "by": "a@b"}).status_code == 400
    assert c.post("/registry/GZQO", json={"status": "candidate", "by": "a@b"}).status_code == 400
    assert c.post("/registry/GZQO", json={"mrn": "10000001", "status": "nope", "by": "a@b"}).status_code == 422
    assert c.get("/registry").json()[0]["counts"] == {"candidate": 1}
    assert len(c.get("/registry/GZQO").json()) == 1 and len(c.get("/registry/GZQO/events").json()) == 1
    assert c.post("/registry/GZQO/promote", json={"by": "pi@hospa.test"}).json() == {"added": 0}
    r = c.get("/registry/GZQO/export.xlsx")
    assert r.status_code == 200 and r.content.startswith(b"PK")
    assert c.get("/registry/bad%20id").status_code == 400


def _reg_for_api(tmp_path: Path) -> CandidateRegistry:
    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    return CandidateRegistry(JobDB(tmp_path / "jobs.sqlite"), AuditLog(tmp_path / "audit"), sec, r"^\d{8}$")
