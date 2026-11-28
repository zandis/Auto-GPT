# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""FU-DQD-NAMES: a synthetic chart number and a Japanese name planted in a data quality row's name and note are
absent from the night's page, its API answer, the audit event and the batch row; a wrongly typed record is not
copied. Synthetic data."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from datacore.dataops import DataOps

from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_dataops_dqd import FAIL, _api, _night, _orch, _steward  # noqa: F401

CHART = "00123456"
NAME = "山田太郎"
DIRTY = {**FAIL, "checkName": f"plausible MRN {CHART}", "cdmFieldName": f"MRN {CHART}", "notes": f"患者 {NAME} さん"}


def _clean(text: str) -> None:
    assert CHART not in text and NAME not in text


def test_the_page_the_api_the_row_and_the_audit_event_carry_no_identifier(box: dict[str, Any]) -> None:
    bid = _night(box, {"state": "loaded", "dqd": {"checks": 60, "fail": 1, "known": 0, "failed": [DIRTY]}})
    c, _ = _steward(box)
    page = c.get(f"/data-ops/batches/{bid}").text
    assert 'data-testid="batch-dqd"' in page
    _clean(page)
    api = _api(box).get(f"/api/v1/data/batches/{bid}")
    assert api.status_code == 200
    _clean(api.text)
    ops = DataOps()
    try:
        b = ops.batch(bid)
        assert b is not None
        _clean(repr(b.detail))
    finally:
        ops.close()
    audit = "".join(f.read_text(encoding="utf-8") for f in sorted((Path(box["dir"]) / "audit").rglob("*.jsonl")))
    assert "ingest.done" in audit
    _clean(audit)


def test_a_row_stored_before_the_scrub_is_scrubbed_when_shown(box: dict[str, Any]) -> None:
    from console.dataops_page import dqd_of

    got = dqd_of({"omop": {"dqd": {"checks": 1, "fail": 1, "known": 0, "failed": [DIRTY]}}})
    assert got is not None
    _clean(repr(got))


def test_a_wrongly_typed_record_is_not_copied(box: dict[str, Any]) -> None:
    c, _ = _steward(box)
    api = _api(box)
    for omop in (
        {"state": "loaded", "dqd": {"checks": 1, "fail": 0, "known": 0, "failed": f"{NAME} {CHART}"}},
        {"state": "loaded", "dqd": {"checks": 1, "fail": 1, "known": 0, "failed": [{**FAIL, "notes": [NAME]}]}},
    ):
        bid = _night(box, omop)
        _clean(c.get(f"/data-ops/batches/{bid}").text)
        _clean(api.get(f"/api/v1/data/batches/{bid}").text)
        ops = DataOps()
        try:
            b = ops.batch(bid)
            assert b is not None
            assert NAME not in repr(b.detail) and "failed" not in b.detail["omop"]["dqd"] or (
                b.detail["omop"]["dqd"]["failed"] and "notes" not in b.detail["omop"]["dqd"]["failed"][0]
            )
        finally:
            ops.close()
