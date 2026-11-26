"""Candidate registry (D-92): transitions, pseudonym resolution, promotion from the SCREEN pool, the screening-log
export with in-box chart numbers, and the audit records. No orchestrator run needed."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
    pm = PidMap(sec / "pid_map.key")
    pm.upsert_many([(pid_for_mrn(KEY, m), m) for m in ("10000001", "10000002", "10000003")])
    pm.close()
    db = JobDB()
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
    with pytest.raises(RegistryError, match="not a ruleset id"):  # D-555: the id that was sent is not repeated
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


def test_promote_leaves_a_pool_row_of_another_criteria_version(reg: CandidateRegistry) -> None:
    """D-476 (review of T-707, MED 2): a row stored before an amendment that MICROBATCH has not screened again is
    ``high`` on criteria it was never evaluated on; it is not promoted, and the audit counts it."""
    stored = {str(p["version"]) for p in reg.db.pool("GZQO")}
    assert len(stored) == 1
    assert reg.promote("GZQO", RegistryPromote(by="pi@hospa.test"), NOW, "9.9.9") == 0  # an amendment in force
    lines = [json.loads(x) for f in sorted(reg.audit.directory.glob("*.jsonl")) for x in f.read_text().splitlines()]
    last = [r for r in lines if r["event"] == "registry.promote"][-1]
    assert last["detail"]["added"] == 0 and last["detail"]["other_version"] == 2
    assert reg.promote("GZQO", RegistryPromote(by="pi@hospa.test"), NOW, stored.pop()) == 2  # the rows' own version


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


def test_a_typed_reason_is_text_in_the_export_never_a_formula(reg: CandidateRegistry) -> None:
    """NEW-CSV-1 (D-549): the coordinator's reason is typed; a spreadsheet must not run it."""
    typed = '=HYPERLINK("http://example.test","open")'
    reg.promote("GZQO", RegistryPromote(by="pi@hospa.test"), NOW)
    reg.update("GZQO", _upd(pid=pid_for_mrn(KEY, "10000001"), status="contacted", reason=typed), NOW)
    wb = load_workbook(io.BytesIO(reg.export_xlsx("GZQO", "DEMO-A")))
    cells = [c for ws in wb.worksheets for row in ws.iter_rows() for c in row]
    assert not [c.coordinate for c in cells if c.data_type == "f"]
    assert sum(1 for c in cells if c.value == typed) >= 2  # the row and its event, every character


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
    (reg.secrets_dir / "pid_map.key").unlink()
    wb2 = load_workbook(io.BytesIO(reg.export_xlsx("GZQO", "DEMO-A")))
    assert all(r[0] in ("", None) for r in list(wb2["screening_log"].iter_rows(values_only=True))[1:])


def test_registry_api_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The orchestrator's registry endpoints map errors to 400 and return the generated models."""
    from fastapi.testclient import TestClient
    from orchestrator import app as oapp

    reg = _reg_for_api(tmp_path)
    monkeypatch.setenv("TB_ENV", "TEST")  # a test box: no service token needed (D-114)
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)

    fake = SimpleNamespace(
        db=reg.db,  # T-103 (D-438): the export cap is counted in this store, at the box's clock
        _now=lambda: datetime.now(UTC),
        audit=reg.audit,
        rulesets_dir=tmp_path / "rulesets",  # no approved version here: nothing is in force (D-476)
        today=NOW.date,
        cfg=SimpleNamespace(
            env=SimpleNamespace(secrets_dir=str(reg.secrets_dir)),
            settings=SimpleNamespace(mrn_regex=r"^\d{8}$", site=SimpleNamespace(tz="Asia/Taipei", id="DEMO-A")),
        ),
    )
    monkeypatch.setattr(oapp, "orch", lambda: fake)
    c = TestClient(oapp.app)

    def send(body: dict[str, Any], path: str = "/registry/GZQO") -> Any:
        """T-715b (D-550): every registry change carries the acting person's assertion; no body field names one."""
        from tests.actor3 import signed

        return c.post(path, json=body, headers=signed("request.prepare", "GZQO", "POST", path, body))

    from tests.actor3 import signed

    def read(path: str, study: str = "GZQO") -> Any:
        """D-717: a read of the registry's patients carries the reading person's assertion too."""
        return c.get(path, headers=signed("phi.view", study, "GET", path))

    first = {"mrn": "10000001", "status": "candidate"}
    assert c.post("/registry/GZQO", json=first).status_code == 403  # nobody
    assert c.get("/registry/GZQO").status_code == 403  # D-717: nobody reads it either
    r = send(first)
    assert (
        r.status_code == 200 and r.json()["status"] == "candidate" and r.json()["pid"] == pid_for_mrn(KEY, "10000001")
    )
    assert r.json()["updated_by"] == "console:crc"  # the verified person, not a typed one
    assert send({"mrn": "x", "status": "candidate"}).status_code == 400
    assert send({"status": "candidate"}).status_code == 400
    assert send({"mrn": "10000001", "status": "nope"}).status_code == 422
    assert send({**first, "by": "a@b"}).status_code == 422  # a typed person is not a field of the request
    assert c.get("/registry").json()[0]["counts"] == {"candidate": 1}
    assert len(read("/registry/GZQO").json()) == 1 and len(read("/registry/GZQO/events").json()) == 1
    assert send({}, "/registry/GZQO/promote").json() == {"added": 0}
    assert c.get("/registry/GZQO/export.xlsx").status_code == 400  # S-09: a named user, always
    r = c.get("/registry/GZQO/export.xlsx?by=crc1@hospa.test")
    assert r.status_code == 200 and r.content.startswith(b"PK")
    # D-717: no assertion can name a study that is not one, so a bad id is refused by the person check now,
    # before the handler's own 400; one signed for a real study is refused as another study's
    with pytest.raises(ValueError, match="not one study"):
        read("/registry/bad%20id", "bad id")
    r = c.get("/registry/bad%20id", headers=signed("phi.view", "GZQO", "GET", "/registry/bad%20id"))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ACTOR"


def _reg_for_api(tmp_path: Path) -> CandidateRegistry:
    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "site_hmac.key").write_bytes(KEY)
    return CandidateRegistry(JobDB(), AuditLog(tmp_path / "audit"), sec, r"^\d{8}$")


def test_pid_maps_of_different_keys_do_not_mix(tmp_path: Path, db_url: str) -> None:
    """One trial database holds the map of each key file (one per secrets dir): rows of another key are invisible,
    and MRNs are stored encrypted (D-126, D-10)."""
    from tb_common.db import Database

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    pa, pb = PidMap(a / "pid_map.key"), PidMap(b / "pid_map.key", db_url)
    assert pa.upsert_many([("p1", "10000001")]) == 1
    assert pa.upsert_many([("p1", "10000001"), ("p2", "10000002")]) == 1  # p1 is known: last_seen only
    assert pb.upsert_many([("p1", "20000001")]) == 1
    pa.upsert_identity([("p1", {"name": "A"})])
    assert (pa.resolve("p1"), pb.resolve("p1"), pb.resolve("p2")) == ("10000001", "20000001", None)
    assert pa.identity("p1") == {"name": "A"} and pb.identity("p1") is None
    pa.close()
    again = PidMap(a / "pid_map.key")  # a new connection, the same key: the same map
    assert again.resolve_many(["p1", "p2", "p3"]) == {"p1": "10000001", "p2": "10000002"}
    again.close()
    pb.close()
    with Database.connect(db_url, "pidmap") as db:
        raw = repr(db.fetchall("SELECT * FROM pid_map") + db.fetchall("SELECT * FROM identity")).encode()
    assert b"10000001" not in raw and b"20000001" not in raw and b"'A'" not in raw


def test_registry_promote_reports_a_damaged_approved_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of #1547 R1: an approved copy that cannot be read whole (INT-R3A) is not "no version in force"; the
    promotion is refused and promotes nothing, never a quiet ``{"added": 0}``."""
    from fastapi.testclient import TestClient
    from orchestrator import app as oapp
    from tb_common import ruleset as rsmod

    from tests.actor3 import signed

    monkeypatch.setenv("TB_ENV", "TEST")
    monkeypatch.delenv("TB_SERVICE_TOKEN", raising=False)
    called: list[Any] = []

    def promote(*a: Any) -> int:
        called.append(a)
        return 0

    reg = SimpleNamespace(promote=promote)
    site = SimpleNamespace(settings=SimpleNamespace(site=SimpleNamespace(tz="Asia/Taipei")))
    fake = SimpleNamespace(rulesets_dir=tmp_path / "rulesets", today=NOW.date, cfg=site)
    monkeypatch.setattr(oapp, "orch", lambda: fake)
    monkeypatch.setattr(oapp, "registry_of", lambda _o: reg)

    def damaged(*_a: Any, **_k: Any) -> Any:
        raise rsmod.RulesetReadIncomplete("GZQO: the working copy differs from its approval tag")

    monkeypatch.setattr(rsmod, "load_approved", damaged)
    path = "/registry/GZQO/promote"
    r = TestClient(oapp.app).post(path, json={}, headers=signed("request.prepare", "GZQO", "POST", path, {}))
    assert r.status_code == 409 and "nothing was promoted" in r.json()["detail"]
    assert called == []
