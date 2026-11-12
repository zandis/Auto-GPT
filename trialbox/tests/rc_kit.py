"""Test kit for build step 3: a REDCap simulator, a study service over a real candidate registry, and the two
fixture projects' links (ICD-04 §4.1a conformance)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient
from orchestrator.candidates import CandidateRegistry
from orchestrator.db import JobDB
from orchestrator.study_api import StudyService
from orchestrator.studystore import StudyStore
from rc_bridge.client import register_local
from rc_sim.app import create_app
from tb_common.audit import AuditLog

TOKEN_A = "A1B2C3D4E5F60718293A4B5C6D7E8F90"
TOKEN_B = "0F1E2D3C4B5A69788796A5B4C3D2E1F0"
TZ = ZoneInfo("Asia/Tokyo")
PIDS = {n: f"{i:02x}" * 16 for i, n in enumerate(("GZQO-0901", "GZQO-0902", "GZQO-0903", "RB0901", "RB0902"), 1)}

LINK_A: dict[str, Any] = {
    "project_id": 101,
    "token_ref": "proj-a",
    "link_field": "tb_screening_no",
    "consent_field": "consent_date",
    "enrol_field": "enrolled",
    "enrol_value": "1",
    "screenfail_field": "sf_reason",
    "screenfail_choice_map": {"1": "inclusion", "2": "exclusion", "3": "consent_withdrawn", "9": "other"},
    "subject_no_field": "subject_no",
}
LINK_B: dict[str, Any] = {
    "project_id": 202,
    "token_ref": "proj-b",
    "dag": "cgmh_linkou",
    "link_field": "tb_screening_no",
    "consent_field": "icf_dt",
    "consent_event": "screening_arm_1",
    "enrol_field": "rand_yn",
    "enrol_value": "1",
    "withdraw_field": "withdrawn",
    "withdraw_value": "1",
}


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@contextmanager
def study_service(tmp: Path, sim: FastAPI | None = None, url: str = "inproc://rc-sim-test") -> Iterator[Any]:
    """A study service over a fresh registry, with tokens for both fixture projects pointing at ``sim``."""
    sim = sim or create_app()
    register_local(url, lambda: TestClient(sim, base_url="http://rc-sim"))
    db = JobDB()
    audit = AuditLog(tmp / "audit", "Asia/Tokyo")
    (tmp / "sec").mkdir(exist_ok=True)
    store = StudyStore(tmp / "sec")
    reg = CandidateRegistry(db, audit, tmp / "sec")
    clock = Clock(datetime(2026, 11, 7, 21, 0, tzinfo=TZ))
    svc = StudyService(store, reg, audit, clock)
    for ref, tok in (("proj-a", TOKEN_A), ("proj-b", TOKEN_B)):
        store.save_connection(ref, url, "admin", "2026-11-07T20:00:00+09:00")
        store.put_token(ref, tok)
    try:
        yield svc, sim, clock
    finally:
        store.close()


def sim_edit(sim: FastAPI, project_id: int, records: list[dict[str, Any]], at: str | None = None) -> None:
    body: dict[str, Any] = {"project_id": project_id, "records": records}
    if at:
        body["at"] = at
    r = TestClient(sim).post("/sim/records", json=body)
    assert r.status_code == 200, r.text
