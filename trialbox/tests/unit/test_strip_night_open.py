"""Rollback past job schema 1.3.0: ``tools.strip_night_open`` leaves stored job records that the previous schema (the
current one without ``metrics.night_open``) accepts, and changes nothing else."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from orchestrator.db import JobDB
from tb_contracts import Job, JobMetrics, NightOpen, OpenReason

from tools.strip_night_open import strip

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "job.schema.json").read_text(encoding="utf-8"))


def _previous_schema() -> dict[str, Any]:
    old: dict[str, Any] = copy.deepcopy(SCHEMA)
    del old["$defs"]["job_metrics"]["properties"]["night_open"]
    return old


def _job(job_id: str, no: NightOpen | None) -> Job:
    return Job(
        job_id=job_id,
        type="MICROBATCH",
        requested_by="scheduler",
        received_at=datetime(2026, 11, 28, tzinfo=UTC),
        state="done",
        ruleset="R-1",
        metrics=JobMetrics(patients_scoped=3, night_open=no),
    )


def test_strip_makes_every_stored_record_valid_for_the_previous_schema(tmp_path: Path) -> None:
    no = NightOpen(
        coded_complete=2, open_reasons=[OpenReason(criterion="N-1", reason="no_notes", where="notes", count=2)]
    )
    db = JobDB(schema="orch_" + hashlib.sha1(str(tmp_path.resolve()).encode()).hexdigest()[:10])
    try:
        db.put(_job("01J0000000000000000000000A", no))
        db.put(_job("01J0000000000000000000000B", None))
        old = Draft202012Validator(_previous_schema())

        def rows() -> list[dict[str, Any]]:
            return [json.loads(r[0]) for r in db._db.fetchall("SELECT data FROM jobs ORDER BY job_id")]

        assert not all(old.is_valid(r) for r in rows())  # the new shape is what the previous schema refuses
        assert strip(db) == 1
        assert all(old.is_valid(r) for r in rows())
        kept = db.get("01J0000000000000000000000A")
        assert kept is not None and kept.metrics is not None and kept.metrics.patients_scoped == 3
        assert strip(db) == 0  # twice is safe
    finally:
        db.close()
