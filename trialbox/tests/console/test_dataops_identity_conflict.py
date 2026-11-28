# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""H34-06: a night held because a chart number arrived as two people says so on its page, in en, ja and zh-TW.

The adapter counts them in the night's ``ingest.held`` event (``identity_conflicts``, counts only); the batch row
keeps it (``DETAIL_KEYS``) and the held night's page tells the steward the night cannot be accepted as it stands.
A held night without it shows no such line. Synthetic data only."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pytest
from console.i18n import translate
from datacore.dataops import DataOps
from tb_common.audit import AuditLog

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import PW, _user

AT = "2026-11-11T02:00:00+09:00"


def _held(b: dict[str, Any], two: Any) -> int:
    ops = DataOps()
    try:
        detail = {"counts": {"Patient": 10}, **({"identity_conflicts": two} if two is not None else {})}
        batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"), "ingest.held", source="csv",
                                    snapshot="2026-11-10", passed=False, held=True, by="adapter", at=AT,
                                    actor="adapter", detail=detail)  # fmt: skip
        return batch.id
    finally:
        ops.close()


@pytest.fixture(autouse=True)
def _orch(box: dict[str, Any]) -> None:
    from tests.console.dataops_orch import attach

    attach(box["backend"], box["audit"])


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_a_night_held_for_two_people_under_one_chart_says_so(box: dict[str, Any], lang: str) -> None:
    bid = _held(box, {"tonight": 1, "against_served": 2})
    _user(box, "stwi", "steward")
    c, csrf = login(box["app"], "stwi", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    page = html.unescape(c.get(f"/data-ops/batches/{bid}").text)
    assert 'data-testid="batch-identity-conflict"' in page
    assert translate(lang, "dataops.identity_conflict", n=3) in page


def test_a_night_held_for_another_reason_has_no_such_line(box: dict[str, Any]) -> None:
    bid = _held(box, None)
    _user(box, "stwj", "steward")
    c, _csrf = login(box["app"], "stwj", PW)
    assert 'data-testid="batch-identity-conflict"' not in c.get(f"/data-ops/batches/{bid}").text


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_the_page_counts_the_held_chart_numbers_within_the_night_and_against_the_served_one(
    box: dict[str, Any], lang: str
) -> None:
    """Ruling (#1561, round 2, A): the steward's role holds no ``id.reveal`` (the permission matrix), so the page
    shows the held chart numbers as two counts, never an identifier, and says where a chart number is shown."""
    bid = _held(box, {"tonight": 1, "against_served": 2})
    _user(box, "stwk", "steward")
    c, csrf = login(box["app"], "stwk", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    page = html.unescape(c.get(f"/data-ops/batches/{bid}").text)
    assert 'data-testid="batch-identity-conflict-counts" data-tonight="1" data-against="2"' in page
    assert translate(lang, "dataops.identity_conflict_counts", tonight=1, against=2) in page


@pytest.mark.parametrize("lang", ["en", "ja", "zh-TW"])
def test_a_night_that_applied_a_merge_of_differing_people_says_so_on_its_page(box: dict[str, Any], lang: str) -> None:
    """Ruling (#1561, P01): a recorded merge overrides differing demographics and the night passes, but its page
    names the merged pids and the ticket and says "demographics differ: merge recorded"."""
    ops = DataOps()
    try:
        said = [{"pids": ["p-old", "p-new"], "ticket": "HIS-1", "said": "demographics differ: merge recorded"}]
        batch, _ = ops.record_night(AuditLog(Path(box["dir"]) / "audit", "UTC"), "ingest.done", source="csv",
                                    snapshot="2026-11-10", passed=True, held=False, by="adapter", at=AT,
                                    actor="adapter", detail={"counts": {"Patient": 10}, "merge_recorded": said})  # fmt: skip
    finally:
        ops.close()
    _user(box, "stwm", "steward")
    c, csrf = login(box["app"], "stwm", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    page = html.unescape(c.get(f"/data-ops/batches/{batch.id}").text)
    assert 'data-testid="batch-merge-recorded"' in page
    assert translate(lang, "dataops.merge_recorded", old="p-old", new="p-new", ticket="HIS-1") in page
