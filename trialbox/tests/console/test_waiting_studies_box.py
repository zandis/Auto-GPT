"""NEW-JRN-1b (D-545): the route and the console's reader of the studies waiting for approval, on the real
orchestrator in the production trust configuration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from console import studies as st
from console.backend import Unavailable
from tb_contracts import Job

from tests.orch_box import OrchBox

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def _wait(ob: OrchBox, n: int, ruleset: str) -> None:
    at = T0 + timedelta(minutes=n)
    ob.box.orch.db.put(Job(job_id=f"01JWA1T{n:019d}", type="FEAS", ruleset=ruleset, requested_by="crc@hospa.test",
                           received_at=at, updated_at=at, state="awaiting_approval", options={}, outputs=[]))  # fmt: skip


def test_the_route_names_every_waiting_study_and_only_the_console_and_the_operator_read_it(orch_box: OrchBox) -> None:
    _wait(orch_box, 0, "NEWSTUDY")
    for n in range(1, 505):
        _wait(orch_box, n, "BUSY")
    r = orch_box.client("console").get("/jobs/waiting-studies")
    assert r.status_code == 200 and r.json() == ["BUSY", "NEWSTUDY"]
    assert orch_box.client("operator").get("/jobs/waiting-studies").status_code == 200
    assert orch_box.client(None).get("/jobs/waiting-studies").status_code == 401
    assert orch_box.client("lake").get("/jobs/waiting-studies").status_code == 403
    assert orch_box.client("mail-gateway").get("/jobs/waiting-studies").status_code == 403
    # and the console's reader, through its own backend: upper case, each once
    assert st.waiting_studies(orch_box.backend()) == ["BUSY", "NEWSTUDY"]


def test_the_consoles_reader_asks_no_job_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    class Bk:
        def waiting_studies(self) -> list[str]:
            return ["gzqo", "GZQO", "", "  ", " new1 "]

        def list_jobs(self, *a: Any, **k: Any) -> list[Any]:
            raise AssertionError("the waiting studies are not read from a listing of jobs")

    assert st.waiting_studies(Bk()) == ["GZQO", "NEW1"]

    class Down(Bk):
        def waiting_studies(self) -> list[str]:
            raise Unavailable("orchestrator down")

    with pytest.raises(Unavailable):
        st.waiting_studies(Down())
