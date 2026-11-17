"""D-989, lane C2's finding (2026-11-17): SCREEN's ``ai.used`` covered only the listed patients (``candidate_list``
keeps the ``high`` and ``review`` rows), so an excluded patient's model verdicts never reached the chain, while
MICROBATCH recorded them. An exclusion is the model use with the most at stake: every row the run read is recorded
now, by pseudonym. A row whose verdicts no model answered records nothing (its ``prov: []`` says so).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from orchestrator.scenarios.screen import record_model_uses
from tb_common.audit import AuditLog

LISTED = "0ca5381cfa6bdf1c22961d65579f93b3"
EXCLUDED = "1afe78d42518132b113c5858cedcbb54"
CODED = "23eeb6239d5526cc352af991cf4097df"


def _row(pid: str, tier: str, prov: list[str]) -> Any:
    v = SimpleNamespace(id="N-INC-01", prov=prov)
    return SimpleNamespace(pid=pid, tier=tier, criteria=[v])


def test_the_excluded_patients_model_verdicts_are_recorded_too(tmp_path: Path) -> None:
    log = AuditLog(tmp_path)
    rows = [_row(LISTED, "high", ["c1", "c2"]), _row(EXCLUDED, "excluded", ["c3", "c4"]), _row(CODED, "excluded", [])]
    ctx = SimpleNamespace(orch=SimpleNamespace(audit=log), job=SimpleNamespace(job_id="01JOB"))
    rs = SimpleNamespace(id="GZQO", version="1.0.0")
    srun = SimpleNamespace(rows=rows)
    assert record_model_uses(ctx, rs, srun) == 2  # type: ignore[arg-type]
    lines = [json.loads(x) for p in sorted(tmp_path.glob("*.jsonl")) for x in p.read_text("utf-8").splitlines() if x]
    used = {e["detail"]["record_ref"]["pid"]: e["detail"]["calls"] for e in lines if e["event"] == "ai.used"}
    assert used == {LISTED: ["c1", "c2"], EXCLUDED: ["c3", "c4"]}
