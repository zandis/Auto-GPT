"""P-20: the candidates API pages on the server, at 50,000 synthetic candidates. With ``page`` it answers one page and
the totals, within :data:`P95_BOUND_S` at the 95th percentile; without it, every row, as before. The candidate list is
synthetic: hex pseudonyms, two coded criteria, forty made-up practitioner codes."""

from __future__ import annotations

import gc
import json
import statistics
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common.crypto import sha256_bytes
from tb_contracts import Job, JobOutput

from tests.console import test_console_app as base

box = base.box
N = 50_000
LISTED = ("high", "review")
#: seconds, the 95th percentile of the page's requests
P95_BOUND_S = 2.5
REQUESTS = 7
T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)  # the console's fixed clock
TIMES: list[str] = []  # each measured page's request times, for a failure's message


def _rows(n: int) -> list[dict[str, Any]]:
    tiers = ("high", "review", "excluded")
    return [
        {
            "pid": f"{i:032x}",
            "tier": tiers[i % 3],
            "next_appointment": f"2026-10-{7 + i % 20:02d}T09:30:00+08:00" if i % 5 == 0 else None,
            "practitioner_id": f"DR-{i % 40}",
            "department": "RHEU",
            "criteria": [
                {"id": "GZQO-INC-01", "verdict": "pass", "evidence": {"resource_refs": [], "reason": "coded"}},
                {"id": "GZQO-INC-05", "verdict": "unknown" if i % 4 else "pass", "evidence": {"resource_refs": []}},
            ],
            "actions": [],
            "n_unknown": 1 if i % 4 else 0,
        }
        for i in range(n)
    ]


def _screen(backend: Any, n: int) -> int:
    """A done SCREEN run of study GZQO listing ``n`` synthetic candidates; returns how many are listed (high and
    review)."""
    rows = _rows(n)
    jid = base._ulid(951)
    summary = {"ruleset": "GZQO", "version": "1.0.0", "run_date": "2026-10-05", "snapshot": "2026-10-04",
               "practitioner_names": {f"DR-{k}": f"Dr {k}" for k in range(40)}, "tiers": {}, "listed": n}  # fmt: skip
    cl = {"ruleset": "GZQO", "version": "1.0.0", "snapshot": "2026-10-04", "scope": {}, "rows": rows, "summary": {}}
    files = (
        ("screen_candidates_GZQO_v1.0.0_2026-10-05.json", json.dumps(summary).encode()),
        ("candidate_list_GZQO_v1.0.0.json", json.dumps(cl).encode()),
    )
    outs = []
    for name, data in files:
        key = f"outputs/{jid}/{name}"
        backend.objects[key] = data
        out = JobOutput(filename=name, sha256=sha256_bytes(data), minio_key=key, recipients=[], tag="aggregate")
        outs.append(out if name.startswith("screen_") else out.model_copy(update={"tag": "phi"}))
    backend.add_job(
        Job(
            job_id=jid,
            type="SCREEN",
            ruleset="GZQO",
            requested_by="admin@hospa.test",
            received_at=T0,
            updated_at=T0,
            state="done",
            options={},
            outputs=outs,
        )
    )
    return sum(1 for r in rows if r["tier"] in LISTED)


@pytest.fixture
def big(box: dict[str, Any]) -> dict[str, Any]:
    box["app"].state.helpers.clock = lambda: T0
    listed = _screen(box["backend"], N)
    crc, _ = base.login_crc(box)
    api = TestClient(box["app"])
    token = api.post("/api/v1/session", json={"username": "crc", "password": base.CRC_PW}).json()["token"]
    api.headers["Authorization"] = f"Bearer {token}"
    return {**box, "crc": crc, "api": api, "listed": listed}


def _p95(client: Any, path: str) -> tuple[float, Any]:
    first = client.get(path)  # the first read of a run records its first appearances: not what a reader waits for
    assert first.status_code == 200, (path, first.status_code)
    gc.collect()  # what earlier tests in this process left is not this page's time
    times = []
    for _ in range(REQUESTS):
        t = time.perf_counter()
        r = client.get(path)
        times.append(time.perf_counter() - t)
        assert r.status_code == 200, (path, r.status_code)
    TIMES.append(" ".join(f"{t:.2f}" for t in times))
    return statistics.quantiles(times, n=20, method="inclusive")[18], r


def test_the_candidates_api_pages_on_the_server(big: dict[str, Any]) -> None:
    c = big["api"]
    p95, r = _p95(c, "/api/v1/studies/GZQO/candidates?page=2&size=50")
    assert p95 < P95_BOUND_S
    body = r.json()
    assert (body["total"], body["page"], body["size"], len(body["candidates"])) == (big["listed"], 2, 50, 50)
    assert body["pages"] == -(-big["listed"] // 50)
    whole = c.get("/api/v1/studies/GZQO/candidates").json()  # no page asked: every row, as before
    assert len(whole["candidates"]) == big["listed"] and "total" not in whole
    assert [x["pid"] for x in body["candidates"]] == [x["pid"] for x in whole["candidates"][50:100]]
    last = c.get(f"/api/v1/studies/GZQO/candidates?page={10**6}&size={10**6}").json()
    assert last["size"] == 1000 and last["page"] == last["pages"] and 0 < len(last["candidates"]) <= 1000
