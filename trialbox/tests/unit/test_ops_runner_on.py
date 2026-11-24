"""NEW-OPS-8 (OPS-009, D-561): the installer turns the operations runner on; host health facts that are missing or
older than an hour are red, not a warning that never ends; ``doctor`` fails in PRODUCTION when the runner has not
written its record. Synthetic facts only."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_common import metrics

from tools.trialbox import doctor

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 12, 3, 0, tzinfo=UTC)
CANARY_OK = {"code": "ok", "ok": True}
TIMER = "trialbox-ops.timer"

pytestmark = pytest.mark.nodb


def _facts(at: datetime) -> dict[str, Any]:
    return {
        "at": at.isoformat(),
        "backup": {"level": "ok", "age_hours": 3.0, "problems": []},
        "verified": {"at": (at - timedelta(days=2)).isoformat()},
        "disks": [{"path": "/", "used_pct": 40.0}],
        "cert": {"mode": "internal"},
    }


# ------------------------------------------------------------------------------------------------ the installer
def test_the_installer_enables_and_starts_the_ops_timer() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    enable = text.split("systemctl enable ", 1)[1].split(">/dev/null", 1)[0]
    start = text.split("systemctl enable ", 1)[1].split("systemctl start ", 1)[1].split(">/dev/null", 1)[0]
    assert TIMER in enable and TIMER in start
    assert "trialbox-ops.timer is installed, not enabled" not in text


def test_the_unit_files_and_the_runbook_no_longer_say_off() -> None:
    for name in (TIMER, "trialbox-ops.service"):
        unit = (ROOT / "deploy" / "systemd" / name).read_text(encoding="utf-8")
        assert "not enabled" not in unit.lower() and "enable --now" not in unit
    page = (ROOT / "docs" / "runbook" / "15-operations-screens.md").read_text(encoding="utf-8")
    assert "leaves them off" not in page and "Turn the runner on once" not in page
    assert "enables" in page and TIMER in page


# ------------------------------------------------------------------------------------------------ the health facts
def test_fresh_facts_are_ok() -> None:
    h = metrics.evaluate(_facts(NOW - timedelta(minutes=2)), CANARY_OK, NOW)
    assert h.level == "ok" and all(c.level == "ok" for c in h.checks)


def test_facts_older_than_an_hour_are_red() -> None:
    h = metrics.evaluate(_facts(NOW - timedelta(minutes=61)), CANARY_OK, NOW)
    facts = next(c for c in h.checks if c.name == "facts")
    assert facts.level == "red" and h.level == "red"
    assert TIMER in facts.text


def test_facts_never_written_are_red() -> None:
    h = metrics.evaluate(None, CANARY_OK, NOW)
    facts = next(c for c in h.checks if c.name == "facts")
    assert facts.level == "red" and h.level == "red"
    assert TIMER in facts.text


def test_facts_dated_after_the_clock_are_not_fresh_for_ever() -> None:
    """A clock that was wrong when the runner last wrote: the facts would otherwise never be old."""
    h = metrics.evaluate(_facts(NOW + timedelta(days=30)), CANARY_OK, NOW)
    assert next(c for c in h.checks if c.name == "facts").level == "red"


def test_facts_within_the_hour_stay_out_of_the_way() -> None:
    h = metrics.evaluate(_facts(NOW - timedelta(minutes=59)), CANARY_OK, NOW)
    assert all(c.name != "facts" for c in h.checks) and h.level == "ok"


# ------------------------------------------------------------------------------------------------ doctor
def _deploy(tmp_path: Path, at: datetime | None) -> Path:
    deploy = tmp_path / "deploy"
    (deploy / "ops").mkdir(parents=True)
    if at is not None:
        (deploy / "ops" / "status.json").write_text(json.dumps({"health": _facts(at)}), encoding="utf-8")
    return deploy


def _check(deploy: Path | None, env: str, **kw: Any) -> doctor.Check:
    kw.setdefault("timer_state", lambda unit: None)  # H-115: a host of the test's own, never the machine's systemd
    inp = doctor.DoctorInputs(env={"TB_ENV": env}, deploy=deploy, **kw)
    return doctor.check_ops_runner(inp, now=NOW)


def test_doctor_passes_a_runner_that_wrote_its_record_this_hour(tmp_path: Path) -> None:
    c = _check(_deploy(tmp_path, NOW - timedelta(minutes=1)), "PRODUCTION")
    assert (c.name, c.status) == ("ops_runner", "PASS")


@pytest.mark.parametrize(("env", "status"), [("PRODUCTION", "FAIL"), ("VALIDATION", "FAIL"), ("DEV", "WARN"), ("TEST", "WARN")])  # fmt: skip
def test_doctor_fails_a_runner_that_never_ran(tmp_path: Path, env: str, status: str) -> None:
    # H-115: a host of the test's own whose systemd cannot be asked, not the machine's (a box running the tests has
    # the timer enabled, and doctor rightly says so instead)
    c = _check(_deploy(tmp_path, None), env, timer_state=lambda unit: None)
    assert c.status == status and "systemctl enable --now trialbox-ops.timer" in c.detail


def test_doctor_fails_an_old_record_and_says_the_timer_is_off(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path, NOW - timedelta(hours=5))
    c = _check(deploy, "PRODUCTION", timer_state=lambda unit: "disabled")
    assert c.status == "FAIL" and "5 h" in c.detail and "disabled" in c.detail
    c = _check(deploy, "PRODUCTION", timer_state=lambda unit: "enabled")
    assert c.status == "FAIL" and "enabled" in c.detail and "trialbox-ops.service" in c.detail


def test_doctor_fails_a_record_dated_after_the_clock(tmp_path: Path) -> None:
    c = _check(_deploy(tmp_path, NOW + timedelta(days=30)), "PRODUCTION")
    assert c.status == "FAIL" and "after this clock" in c.detail


def test_doctor_reads_the_folder_the_box_names(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "status.json").write_text(json.dumps({"health": _facts(NOW)}), encoding="utf-8")
    inp = doctor.DoctorInputs(env={"TB_ENV": "PRODUCTION", "TB_OPS_DIR": str(other)}, deploy=_deploy(tmp_path, None))
    assert doctor.check_ops_runner(inp, now=NOW).status == "PASS"


def test_doctor_does_not_ask_a_platform_for_a_host_timer(tmp_path: Path) -> None:
    c = _check(_deploy(tmp_path, None), "PRODUCTION", platform=True)
    assert c.status == "PASS" and "platform" in c.detail


def test_a_record_that_does_not_parse_is_not_a_pass(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path, None)
    (deploy / "ops" / "status.json").write_text("{not json", encoding="utf-8")
    assert _check(deploy, "PRODUCTION").status == "FAIL"


def test_the_check_is_one_of_doctors() -> None:
    assert doctor.check_ops_runner in doctor.CHECKS


def test_no_check_here_asks_the_machines_own_systemd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """H-115 (1462-8): every doctor check in this file is given a host of its own."""
    monkeypatch.setattr(doctor, "_timer_state", lambda unit: pytest.fail("asked the machine's systemd"))
    test_doctor_fails_a_record_dated_after_the_clock(tmp_path / "a")
    test_a_record_that_does_not_parse_is_not_a_pass(tmp_path / "b")
