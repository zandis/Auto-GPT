"""Lane N (HOLISTIC-3 §1.2 row 17; H3-NLP §3.1): the DQD-shaped checks of ``omop.dqd`` run after every dual-write
load, and the night report, the night's audit event and its data-operations row carry each check that did not pass
in DQD's words (check, table, field, rows). Counts and check names only. Synthetic data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.test_omop_slice2 import NIGHT1, SITE_A, _cfg, _night

FIELDS = {"checkName", "cdmTableName", "cdmFieldName", "numViolatedRows", "numDenominatorRows", "status", "notes"}


def test_the_night_report_names_every_check_that_did_not_pass(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TB_OMOP_DUAL_WRITE", "on")
    cfg = _cfg(tmp_path, db_url)
    rep = _night(cfg, SITE_A, NIGHT1)
    assert rep.omop is not None and rep.omop.state == "loaded", rep.omop
    dqd = rep.omop.dqd
    assert dqd is not None and dqd.checks > 50
    assert len(dqd.failed) == dqd.fail + dqd.known < dqd.checks
    assert all(r.status in ("fail", "known") for r in dqd.failed)
    # without SNOMED on the box a condition's standard concept stays 0: a known gap, named with its reason
    known = [r for r in dqd.failed if r.status == "known"]
    assert any(r.checkName == "standardConceptRecordCompleteness" and r.notes for r in known)

    body = json.loads((cfg.lake_dir / "ndjson" / NIGHT1 / "ingest_report.json").read_text(encoding="utf-8"))
    kept = body["omop"]["dqd"]
    assert kept["checks"] == dqd.checks and all(set(r) == FIELDS for r in kept["failed"])
    events = [json.loads(x) for f in sorted((tmp_path / "audit").rglob("*.jsonl")) for x in f.read_text().splitlines()]
    done = [e for e in events if e.get("event") == "ingest.done"]
    assert done and done[-1]["detail"]["omop"]["dqd"] == kept
