"""M7 (EDC door): the withdrawal gate around other subjects (V15-06), the delegation log read by the EDC router
(V2-05), REDCap's own log line kept with each value sent (R1-E5), and the PRODUCTION write rule (R1-E6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from datacore.lifecycle import Lifecycle
from edc import copyassist
from edc.store import EdcError

from tests import edc_kit as k

AT = "2026-11-11T09:00:00"


def _signed(tmp_path: Path) -> Any:
    svc, _sim, _token = k.service(tmp_path)
    k.ready(svc)
    for r in svc.build(k.STUDY, k.RECORD, k.PID, "", k.VISIT_DATE, "crc"):
        if r["state"] == "drafted":
            svc.decide(k.STUDY, r["id"], "confirm", by="crc")
    svc.sign(k.STUDY, k.RECORD, "", signer="crc", printed_name="Chen Mei", role="coordinator", meaning="transcribed",
             meaning_text="I checked each value.", lang="en", seen=k.seen(svc))  # fmt: skip
    return svc


def _withdraw(svc: Any, record: str, pid: str, data_use: str) -> None:
    life = Lifecycle(svc.dc)
    life.ensure(k.STUDY, record, pid, "crc", AT)
    for to in ("approached", "consented", "enrolled", "on_study", "withdrawn"):
        life.step(k.STUDY, record, to, by="crc", at=AT, reason="3")
    svc.dc.write(k.STUDY, record, "withdrawal", "wd_data_use", data_use, "crc", AT, "manual")


def _audit(svc: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted(Path(svc.audit.directory).glob("*.jsonl")):
        out += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


# ------------------------------------------------------------------------------------------------- V15-06
def test_another_subjects_withdrawal_does_not_hold_this_subjects_send(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    _withdraw(svc, "S-002", "p-0002", "0")
    out = svc.send_redcap(k.STUDY, "crc")
    assert out["count"] > 0 and out["withdrawn"] == []


def test_a_withdrawal_that_allows_the_data_stops_nothing(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    _withdraw(svc, k.RECORD, k.PID, "1")
    assert svc.send_redcap(k.STUDY, "crc")["count"] > 0


def test_the_copy_sheet_of_a_withdrawn_subject_is_refused_and_the_study_sheet_omits_them(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    _withdraw(svc, k.RECORD, k.PID, "0")
    with pytest.raises(EdcError) as e:
        copyassist.sheet(svc, k.STUDY, k.RECORD, "crc")
    assert e.value.code == "edc.withdrawn"
    whole = copyassist.sheet(svc, k.STUDY, None, "crc")
    assert whole["values"] == 0 and whole["records"] == []


def test_a_send_of_only_withdrawn_values_ledgers_each_as_withdrawn(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    _withdraw(svc, k.RECORD, k.PID, "0")
    with pytest.raises(EdcError):
        svc.send_redcap(k.STUDY, "crc")
    rows = svc.store.sent_rows(k.STUDY)
    assert rows and {r["result"] for r in rows} == {"withdrawn"}


# ------------------------------------------------------------------------------------------------- V2-05
def _router_as(tmp_path: Path, username: str, pi: str | None) -> Any:
    from console.teamstore import TeamStore
    from fastapi import FastAPI
    from orchestrator.edc_api import router
    from tb_common import service_auth as sa

    from tests.actor3 import SignedClient

    svc, _, _ = k.service(tmp_path)
    if pi is not None:
        team = TeamStore()
        team.add_entry(k.STUDY, username=pi, name="Dr Log PI", role="pi", tasks=(), start="2026-01-01", end=None,
                       training_day="2026-01-01", training_ref=None, by="stw", at="2026-01-01T00:00:00+00:00")  # fmt: skip
        team.close()
    app = FastAPI()
    app.include_router(router(lambda: svc))
    return SignedClient(app, sub=f"console:{username}", role="investigator").get(f"/studies/{k.STUDY}/edc/copy",
                                                      headers=sa.actor_header(username, role="investigator"))  # fmt: skip


def test_the_pi_the_log_names_is_not_refused_the_copy_sheet(tmp_path: Path) -> None:
    r = _router_as(tmp_path, "drpi", "drpi")
    assert "edc.role" not in r.text, r.text


@pytest.mark.parametrize("pi", [None, "someoneelse"])
def test_an_investigator_the_log_does_not_name_is_refused(tmp_path: Path, pi: str | None) -> None:
    r = _router_as(tmp_path, "drpi", pi)
    assert r.status_code == 403 and "edc.role" in r.text


# ------------------------------------------------------------------------------------------------- R1-E5
def test_each_value_sent_keeps_redcaps_own_log_line(tmp_path: Path) -> None:
    svc = _signed(tmp_path)
    out = svc.send_redcap(k.STUDY, "crc")
    sent = [r for r in svc.store.sent_rows(k.STUDY) if r["result"] == "sent"]
    assert out["count"] == len(sent) > 0
    assert all(r["redcap_log"] for r in sent), sent
    line = next(e for e in reversed(_audit(svc)) if e.get("event") == "edc.sent")
    assert set(line["detail"]["redcap_log"]) == {r["redcap_log"] for r in sent}
    assert svc.store.trail(k.STUDY, k.RECORD)["sent"][-1]["redcap_log"]


# ------------------------------------------------------------------------------------------------- R1-E6
@pytest.mark.parametrize("state", [None, False])
def test_a_production_box_refuses_a_send_for_a_study_not_recorded_open(tmp_path: Path, state: bool | None,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    svc = _signed(tmp_path)
    svc.study_open = lambda _rs: state
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    with pytest.raises(EdcError) as e:
        svc.send_redcap(k.STUDY, "crc")
    assert e.value.code == "RC-RC1" and "study_open" in e.value.message
    line = next(e for e in reversed(_audit(svc)) if e.get("event") == "edc.sent")
    assert line["detail"]["refused"] == "RC-RC1" and line["detail"]["missing"] == "study_open"
    assert svc.store.sent_rows(k.STUDY) == []


def test_a_production_box_sends_a_signed_value_of_an_open_study_once(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    svc = _signed(tmp_path)
    svc.study_open = lambda _rs: True
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert svc.send_redcap(k.STUDY, "crc")["count"] > 0
    assert svc.send_redcap(k.STUDY, "crc")["count"] == 0
