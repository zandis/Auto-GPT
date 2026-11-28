# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""H34-06: a night with a chart number that arrived as two people says so on its page, in en, ja and zh-TW.

The adapter counts them in the night's event (``identity_conflicts``, counts only); the batch row keeps it
(``DETAIL_KEYS``) and the night's page tells the steward the chart's records are held (PRODUCT-2, "hold records, not
nights"): on a published night too. A night without it shows no such line. Synthetic data only."""

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


def _held(b: dict[str, Any], two: Any, passed: bool = False) -> int:
    ops = DataOps()
    try:
        detail = {"counts": {"Patient": 10}, **({"identity_conflicts": two} if two is not None else {})}
        batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"),
                                    "ingest.done" if passed else "ingest.held", source="csv", snapshot="2026-11-10",
                                    passed=passed, held=not passed, by="adapter", at=AT, actor="adapter",
                                    detail=detail)  # fmt: skip
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


def test_a_published_night_with_held_records_says_so(box: dict[str, Any]) -> None:
    """PRODUCT-2: the night is published without the chart's records; its page lists them for the steward."""
    bid = _held(box, {"tonight": 1, "against_served": 0}, passed=True)
    _user(box, "stwk", "steward")
    c, _csrf = login(box["app"], "stwk", PW)
    page = html.unescape(c.get(f"/data-ops/batches/{bid}").text)
    assert 'data-state="HELD"' not in page
    assert 'data-testid="batch-identity-conflict"' in page and translate("en", "dataops.identity_conflict", n=1) in page
