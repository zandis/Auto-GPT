"""H-35 (D-1101): every stated limit with a driver, driven at the limit, one over and far over on the in-process box
(the console on its stand-in orchestrator with its own PostgreSQL, the real orchestrator's create, the services'
functions). Reports and fixes nothing: it fails only when a row's verdict differs from the one the page records
(``docs/plan/measurements/limits-edge-2026-11-18.md``), or a driver cannot run.

    make limits-edge          # TB_INTEGRATION=1 ... pytest -m e2e tests/e2e/test_limits_edge_box.py

``TB_LIMITS_EDGE_OUT``: where to write the run's JSON (default: not kept)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from tools import limits_edge as le
from tools import pglocal

pytestmark = [pytest.mark.e2e]

#: the verdicts the page records (2026-11-18): every row holds as a limit, except the connector's export, which
#: fetches the whole file before it refuses (H35-01). Words are judged on the page, not here.
EXPECTED = {r.id: "holds" for r in le.STATED if r.driver} | {
    "L07": "one_over refused after work; far_over refused after work"
}


def test_every_driven_limit_gives_the_recorded_verdict() -> None:
    pglocal.scratch_root().mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="limits-edge-", dir=pglocal.scratch_root()))
    doc = le.build()
    doc["results"] = le.drive(work)
    doc["verdicts"] = {k: le.verdict(k, v["cases"]) for k, v in doc["results"].items()}
    out = os.environ.get("TB_LIMITS_EDGE_OUT")
    if out:
        Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    errors = {k: v["error"] for k, v in doc["results"].items() if v.get("error")}
    assert not errors
    assert doc["verdicts"] == EXPECTED
