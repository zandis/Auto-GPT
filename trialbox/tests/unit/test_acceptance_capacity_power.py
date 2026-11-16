"""T-317a (D-730): go-live acceptance gains a capacity criterion and a power-cycle criterion.

* ``capacity``: one night's chain (its ingest, then screen, nav and retention, as the night runner starts them) ends
  ``done`` before the first morning notice that follows the night's start, with an hour to spare; a job that failed
  or never ended fails it.
* ``power-cycle``: after the power came back, ``trialbox doctor --json`` has no FAIL, and the audit chain verifies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import acceptance as acc

pytestmark = pytest.mark.nodb

TZ = "Asia/Taipei"  # +08:00


def _job(jtype: str, state: str, received: str, updated: str, **options: Any) -> dict[str, Any]:
    return {"job_id": f"{jtype}-{received}", "type": jtype, "requested_by": "scheduler", "state": state,
            "received_at": received, "updated_at": updated, "options": options}  # fmt: skip


def _night(end_screen: str = "2026-11-14T03:30:00+08:00", screen_state: str = "done") -> list[dict[str, Any]]:
    n = {"night": "2026-11-13", "night_day": "2026-11-13"}
    return [
        {
            **_job("INGEST", "done", "2026-11-14T01:00:00+08:00", "2026-11-14T01:40:00+08:00"),
            "snapshot_date": "2026-11-13",
        },
        _job("MICROBATCH", screen_state, "2026-11-14T01:41:00+08:00", end_screen, step="screen", **n),
        _job("RETENTION", "done", "2026-11-14T03:31:00+08:00", "2026-11-14T03:35:00+08:00", step="retention", **n),
        # another night's job is not this night's
        _job(
            "MICROBATCH",
            "failed",
            "2026-11-13T01:41:00+08:00",
            "2026-11-13T02:00:00+08:00",
            step="screen",
            night="2026-11-12",
            night_day="2026-11-12",
        ),
    ]


def test_a_night_that_ends_well_before_the_morning_passes() -> None:
    got = acc.check_capacity(_night(), tz=TZ, ready_by="07:00")
    assert got["passed"], got
    assert got["night"] == "2026-11-13" and got["jobs"] == 3
    assert got["ended_at"].startswith("2026-11-14T03:35") and got["spare_hours"] == pytest.approx(3.42, abs=0.01)


def test_a_night_with_less_than_an_hour_to_spare_fails() -> None:
    night = _night(end_screen="2026-11-14T06:10:00+08:00")
    night[2]["updated_at"] = "2026-11-14T06:20:00+08:00"
    got = acc.check_capacity(night, tz=TZ, ready_by="07:00")
    assert not got["passed"] and "spare" in got["summary"]


def test_a_night_that_ends_after_the_morning_fails() -> None:
    night = _night(end_screen="2026-11-14T07:30:00+08:00")
    night[2]["updated_at"] = "2026-11-14T07:40:00+08:00"
    assert not acc.check_capacity(night, tz=TZ, ready_by="07:00")["passed"]


@pytest.mark.parametrize("state", ["failed", "running", "queued"])
def test_a_job_that_did_not_end_done_fails_the_night(state: str) -> None:
    got = acc.check_capacity(_night(screen_state=state), tz=TZ, ready_by="07:00")
    assert not got["passed"] and state in got["summary"]


def test_the_night_can_be_named_and_an_unknown_one_fails() -> None:
    assert not acc.check_capacity(_night(), tz=TZ, ready_by="07:00", night="2026-11-12")["passed"]
    got = acc.check_capacity(_night(), tz=TZ, ready_by="07:00", night="2026-10-01")
    assert not got["passed"] and "no job" in got["summary"]


def test_a_night_that_starts_before_midnight_has_the_next_morning_as_its_deadline() -> None:
    night = _night()
    night[0]["received_at"] = "2026-11-13T23:30:00+08:00"
    assert acc.check_capacity(night, tz=TZ, ready_by="07:00")["passed"]


# ------------------------------------------------------------------------------------------------ power cycle
def _doctor(*statuses: str) -> list[dict[str, str]]:
    return [{"name": f"c{i}", "status": s, "detail": "x"} for i, s in enumerate(statuses)]


def test_a_box_back_with_no_fail_and_a_whole_chain_passes() -> None:
    got = acc.check_power_cycle(_doctor("PASS", "WARN", "PASS"), chain_ok=True)
    assert got["passed"] and "1 WARN" in got["summary"]


def test_a_fail_after_the_power_came_back_fails_and_is_named() -> None:
    got = acc.check_power_cycle(_doctor("PASS", "FAIL"), chain_ok=True)
    assert not got["passed"] and "c1" in got["summary"]


def test_a_broken_audit_chain_after_the_power_came_back_fails() -> None:
    assert not acc.check_power_cycle(_doctor("PASS"), chain_ok=False)["passed"]


def test_an_empty_doctor_answer_is_no_answer() -> None:
    assert not acc.check_power_cycle([], chain_ok=True)["passed"]


def test_both_are_in_the_report(tmp_path: Path) -> None:
    jobs = tmp_path / "night.json"
    jobs.write_text(json.dumps(_night()), encoding="utf-8")
    doctor = tmp_path / "doctor.json"
    doctor.write_text(json.dumps(_doctor("PASS")), encoding="utf-8")
    from tb_common.audit import AuditLog

    audit = tmp_path / "audit"
    AuditLog(audit).append("box.started")  # the chain the box wrote after the power came back
    out = tmp_path / "acc"
    assert acc.main(["--out", str(out), "capacity", "--jobs", str(jobs), "--tz", TZ]) == 0
    assert acc.main(["--out", str(out), "power-cycle", "--doctor", str(doctor), "--audit-dir", str(audit)]) == 0
    report = acc.report(out)
    assert "| capacity |" in report and "| power_cycle |" in report
    assert "capacity" in acc.TARGETS and "power_cycle" in acc.TARGETS
