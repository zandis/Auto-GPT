"""NEW-DIN-3, the console's half (DIN-003, D-544): the box says whether a pseudonym is one of its patients.

The opt-out desk types a chart number and the box turns it into the pseudonym (``POST /setup/pseudonym``). Since
D-591 a number wider than the rule keeps its zeros, so a mistyped number is a new pseudonym no record carries, and
the desk registered it as if it were a patient. The route now also answers ``known``: the pid map holds a row for
that pseudonym (true), holds none (false), or cannot be asked (null)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from adapter.pidmap import PidMap
from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator import identifiers
from orchestrator.setup_api import router as setup_router
from sitesetup.ocr import NoOcr
from sitesetup.service import SiteSetup
from sitesetup.store import SetupStore
from tb_common.audit import AuditLog
from tb_common.crypto import pid_for_mrn

KEY = b"din3-known-test-key-0123456789abcdef"
NOW = datetime(2026, 11, 12, 0, 30, tzinfo=UTC)
CHART, OTHER = "00123456", "00999999"  # synthetic


def _map(secrets: Path, db_url: str, charts: list[str]) -> None:
    secrets.mkdir(parents=True, exist_ok=True)
    pm = PidMap(secrets / "pid_map.key", db_url)
    try:
        pm.upsert_many([(pid_for_mrn(KEY, c), c) for c in charts])
    finally:
        pm.close()


def test_the_pid_map_answers_known_unknown_or_cannot_say(tmp_path: Path, db_url: str) -> None:
    secrets = tmp_path / "secrets"
    assert identifiers.known_pid(secrets, db_url, pid_for_mrn(KEY, CHART)) is None  # no map yet: it cannot say
    _map(secrets, db_url, [CHART])
    assert identifiers.known_pid(secrets, db_url, pid_for_mrn(KEY, CHART)) is True
    assert identifiers.known_pid(secrets, db_url, pid_for_mrn(KEY, OTHER)) is False
    assert identifiers.known_pid(secrets, "postgresql://trialbox@127.0.0.1:1/none", pid_for_mrn(KEY, CHART)) is None


def _client(tmp_path: Path, known: Any) -> TestClient:
    svc = SiteSetup(SetupStore(), tmp_path / "setup", None, None, AuditLog(tmp_path / "audit"), lambda: NOW,
                    lambda: date(2026, 11, 12), lambda: KEY, ocr=NoOcr(), mrn_regex=r"^\d{8}$", known=known)  # fmt: skip
    app = FastAPI()
    # the door (T-719, D-487) has its own tests; here every caller is let in and its record is dropped
    door = lambda request, actions, service=False: SimpleNamespace(record=lambda *a, **k: None)  # noqa: E731
    app.include_router(setup_router(lambda: svc, lambda rs: {}, lambda rs: {}, lambda rs: None, lambda: False, door))
    return TestClient(app)


def test_the_route_says_whether_the_box_knows_the_pseudonym(tmp_path: Path, db_url: str) -> None:
    secrets = tmp_path / "secrets"
    _map(secrets, db_url, [CHART])
    c = _client(tmp_path, lambda pid: identifiers.known_pid(secrets, db_url, pid))
    assert c.post("/setup/pseudonym", json={"chart_no": CHART, "ask_known": True}).json() == {
        "pid": pid_for_mrn(KEY, CHART),
        "known": True,
    }
    assert c.post("/setup/pseudonym", json={"chart_no": OTHER, "ask_known": True}).json() == {
        "pid": pid_for_mrn(KEY, OTHER),
        "known": False,
    }


def test_a_service_with_no_way_to_ask_says_null_never_true(tmp_path: Path) -> None:
    c = _client(tmp_path, None)
    assert c.post("/setup/pseudonym", json={"chart_no": CHART, "ask_known": True}).json() == {
        "pid": pid_for_mrn(KEY, CHART),
        "known": None,
    }

    def broken(pid: str) -> bool:
        raise RuntimeError("the map is away")

    c = _client(tmp_path / "b", broken)
    assert c.post("/setup/pseudonym", json={"chart_no": CHART, "ask_known": True}).json()["known"] is None


def test_a_chart_number_merged_into_another_is_a_patient_of_this_box(tmp_path: Path, db_url: str) -> None:
    """The review's M1: the register hides the surviving patient for an opt-out under the old number
    (``tb_common.optout.with_survivors``), so the old number is a patient here although it has no row of its own."""
    secrets = tmp_path / "secrets"
    _map(secrets, db_url, [CHART])
    pm = PidMap(secrets / "pid_map.key", db_url)
    try:
        pm.merge(KEY, OTHER, CHART, "the same person, two numbers (synthetic)", "T-0001")
    finally:
        pm.close()
    assert identifiers.known_pid(secrets, db_url, pid_for_mrn(KEY, OTHER)) is True
    assert identifiers.known_pid(secrets, db_url, pid_for_mrn(KEY, "00777777")) is False


def test_the_map_is_asked_only_when_the_caller_asks(tmp_path: Path) -> None:
    """The review's L5: the route's other caller (a CASE job's page) reads the pseudonym only."""
    asked: list[str] = []

    def known(pid: str) -> bool:
        asked.append(pid)
        return True

    c = _client(tmp_path, known)
    assert c.post("/setup/pseudonym", json={"chart_no": CHART}).json() == {"pid": pid_for_mrn(KEY, CHART)}
    assert asked == []
    assert c.post("/setup/pseudonym", json={"chart_no": CHART, "ask_known": True}).json()["known"] is True
