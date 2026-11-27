"""P-20: the heavy pages at 50,000 synthetic candidates. The week list, the candidates page and its API and the
coordinator's home read a run's list of 50k candidates; each request stays under :data:`P95_BOUND_S` at the 95th
percentile, and the API serves one page on request (server-side paging). The candidate list is synthetic: hex
pseudonyms, two coded criteria, forty made-up practitioner codes. The bound and the machine it was measured on are in
``docs/handover/heavy-pages-at-50k-p20-2026-11-27.md``."""

from __future__ import annotations

import json
import statistics
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from console.sitestore import SiteStore
from fastapi.testclient import TestClient
from tb_common.crypto import sha256_bytes
from tb_contracts import JobOutput

from tests.console import test_console_app as base

box = base.box
N = 50_000
LISTED = ("high", "review")
#: seconds, the 95th percentile of each page's requests (see the module's docstring)
P95_BOUND_S = 4.0
REQUESTS = 7
T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)  # the console's fixed clock


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
    outs = []
    for (name, tag), data in {
        ("screen_candidates_GZQO_v1.0.0_2026-10-05.json", "aggregate"): json.dumps(summary).encode(),
        ("candidate_list_GZQO_v1.0.0.json", "phi"): json.dumps(cl).encode(),
    }.items():
        key = f"outputs/{jid}/{name}"
        backend.objects[key] = data
        outs.append(JobOutput(filename=name, sha256=sha256_bytes(data), minio_key=key, recipients=[], tag=tag))
    backend.add_job(
        base.Job(job_id=jid, type="SCREEN", ruleset="GZQO", requested_by="admin@hospa.test", received_at=T0,
                 updated_at=T0, state="done", options={}, outputs=outs)  # fmt: skip
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
    times = []
    for _ in range(REQUESTS):
        t = time.perf_counter()
        r = client.get(path)
        times.append(time.perf_counter() - t)
        assert r.status_code == 200, (path, r.status_code)
    return statistics.quantiles(times, n=20, method="inclusive")[18], r


@pytest.mark.parametrize(
    "path",
    [
        "/studies/GZQO/week",
        "/studies/GZQO/week?list=all&page=600",
        "/studies/GZQO/candidates",
        "/studies/GZQO/candidates?page=900",
        "/home",
    ],
)
def test_a_heavy_page_at_50k_candidates_stays_under_its_bound(big: dict[str, Any], path: str) -> None:
    p95, r = _p95(big["crc"], path)
    assert p95 < P95_BOUND_S, f"{path}: p95 {p95:.2f} s at {N} candidates (bound {P95_BOUND_S} s)"
    assert len(r.content) < 1_000_000  # one page of rows, never the whole list


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


class _Counted:
    """A transaction whose ``executemany`` row counts are kept in ``writes``."""

    def __init__(self, cm: Any, writes: list[int]) -> None:
        self.cm, self.writes = cm, writes

    def __enter__(self) -> _Counted:
        self.tx = self.cm.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self.cm.__exit__(*exc)

    def executemany(self, sql: str, rows: list[Any]) -> Any:
        self.writes.append(len(rows))
        return self.tx.executemany(sql, rows)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.tx, name)


def test_a_run_s_first_appearances_are_written_once(big: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The week list records when a pseudonym was first listed; a list read again writes nothing new and keeps the
    first listing (P-20: a 50k list was written again at every page view)."""
    store: SiteStore = big["app"].state.helpers.store
    pids = [f"{i:032x}" for i in range(6)]
    assert store.seen("P20", pids[:4], "JOB-A", "2026-10-01T00:00:00+00:00") == dict.fromkeys(pids[:4], "JOB-A")
    writes: list[int] = []
    real = store.db.transaction
    monkeypatch.setattr(store.db, "transaction", lambda *a, **k: _Counted(real(*a, **k), writes))
    assert store.seen("P20", pids[:4], "JOB-B", "2026-10-08T00:00:00+00:00") == dict.fromkeys(pids[:4], "JOB-A")
    assert writes == []
    got = store.seen("P20", pids, "JOB-B", "2026-10-08T00:00:00+00:00")
    assert got == {**dict.fromkeys(pids[:4], "JOB-A"), **dict.fromkeys(pids[4:], "JOB-B")} and writes == [2]
