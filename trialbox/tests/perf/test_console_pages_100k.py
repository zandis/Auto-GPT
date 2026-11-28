"""MVP-B (REAL2 M-3): the candidates list, the week page and the patient sheet within 2 s (nearest-rank p95) on a
study of 100,000 listed and excluded patients (50,000 listed, six criteria a row: about 90 MB stored), on the console
test box (its stand-in backend: the object store, the lake's death check and the registry answer in process, so this
times the console's own work). The first view after a new run reads and parses the stored list; it is printed and
held to its own bound, the warm views to 2 s. Synthetic data only; ``TB_PAGES_100K_N`` sets the row count."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from typing import Any

import pytest

from tests.console.timing_walk import JOB, clients

pytestmark = [pytest.mark.perf]

N = int(os.environ.get("TB_PAGES_100K_N") or 100_000)
VIEWS = 20
BUDGET_S = 2.0
FIRST_VIEW_S = 15.0  # parse once per run: the measured 100k first views were 3 to 9.5 s on a loaded host
CRIT = [f"GZQO-INC-0{i}" for i in range(1, 5)] + ["GZQO-EXC-01", "GZQO-EXC-02"]


def _rows(n: int) -> list[dict[str, Any]]:
    return [
        {
            "pid": f"{i:032x}",
            "tier": "high" if i % 10 == 0 else ("review" if i % 10 < 5 else "excluded"),
            "next_appointment": "2026-10-07T09:30:00+08:00" if i % 7 == 0 else None,
            "practitioner_id": f"DR-{i % 300}",
            "department": "RHEU",
            "criteria": [
                {
                    "id": c,
                    "verdict": "pass" if (i + k) % 3 else "unknown",
                    "evidence": {"resource_refs": [f"Observation/{i}-{k}"], "reason": "coded"},
                }
                for k, c in enumerate(CRIT)
            ],
            "actions": [],
            "n_unknown": 1,
        }
        for i in range(n)
    ]


def _p95(ts: list[float]) -> float:
    return sorted(ts)[math.ceil(0.95 * len(ts)) - 1]


def test_the_three_review_pages_answer_within_two_seconds_at_100k(box: dict[str, Any]) -> None:
    crc = clients(box)["coordinator"]
    bk = box["backend"]
    out = next(o for o in bk.jobs[JOB].outputs if o.filename.startswith("candidate_list_"))
    cl = json.loads(bk.objects[out.minio_key])
    bk.objects[out.minio_key] = json.dumps({**cl, "rows": _rows(N)}).encode()
    out.sha256 = hashlib.sha256(bk.objects[out.minio_key]).hexdigest()  # a new run's list, as the store gives it
    pages = {
        "candidates": "/studies/GZQO/candidates",
        "week": "/studies/GZQO/week",
        "patient": f"/studies/GZQO/patients/{10:032x}",
    }
    first: dict[str, float] = {}
    times: dict[str, list[float]] = {k: [] for k in pages}
    for i in range(VIEWS + 1):
        for name, path in pages.items():
            t = time.perf_counter()
            r = crc.get(path, follow_redirects=False)
            dt = time.perf_counter() - t
            assert r.status_code == 200, (name, r.status_code)
            if i == 0 and not first:
                first[name] = dt  # the one view that reads and parses the run's list
            else:
                times[name].append(dt)
    lines = [f"first view ({next(iter(first))}): {next(iter(first.values())):.2f} s"]
    lines += [f"{k}: p95 {_p95(v):.2f} s, max {max(v):.2f} s over {len(v)} views" for k, v in times.items()]
    print("\n" + "\n".join(lines))
    assert max(first.values()) <= FIRST_VIEW_S, lines
    assert all(_p95(v) <= BUDGET_S for v in times.values()), lines
