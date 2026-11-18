"""9l-7 (AQ-7): the eight ``date.today()`` of the services read the site's day, not the server's.

A box that keeps its clock in UTC and serves a site in Tokyo is a day behind from 15:00 UTC: at 23:30 UTC on
2026-11-17 it is 08:30 on 2026-11-18 in Tokyo. ``date.today()`` gave the server's 2026-11-17 to an OMOP batch's
date and the CDM source's release day, the data-quality check's day, a mapping's "nobody lives that long" and its
latest plausible year, and the vocabulary's "validity ended" (synthetic values only)."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
UTC_NOW = datetime(2026, 11, 17, 23, 30, tzinfo=UTC)  # 08:30 on 2026-11-18 in Tokyo


class _Clock(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> Any:
        return UTC_NOW if tz is None else UTC_NOW.astimezone(tz)


@pytest.fixture
def tokyo(monkeypatch: pytest.MonkeyPatch) -> None:
    from tb_common import timeutil

    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    monkeypatch.setattr(timeutil, "datetime", _Clock)


def test_the_site_day_is_tokyos_at_2330_utc(tokyo: None) -> None:
    from tb_common.timeutil import today

    assert today() == date(2026, 11, 18)


def test_an_omop_batch_without_a_date_is_on_the_sites_day(tokyo: None) -> None:
    from omop import load

    assert load._batch_date("feed") == date(2026, 11, 18)
    assert load._batch_day("site@not-a-day") == date(2026, 11, 18)
    assert load._batch_date("site@2026-10-31") == date(2026, 10, 31)  # a batch's own day wins, as before


def test_a_mappings_latest_year_is_the_sites(tokyo: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from adapter.mapping import engine

    monkeypatch.setattr(engine, "LATEST_YEARS_AHEAD", 0)  # only this year: the day decides
    late = datetime(2026, 12, 31, tzinfo=UTC)
    assert engine.Mapper._western(late, "2026-12-31") == late  # Tokyo's 2026 holds it
    with pytest.raises(engine.DateRangeError):
        engine.Mapper._western(datetime(2027, 1, 1, tzinfo=UTC), "2027-01-01")


def test_no_service_reads_the_servers_day() -> None:
    """The ratchet of this card (9l-8 widens it to every clock read): ``date.today()`` and ``datetime.today()`` are
    not called in ``services/`` or ``libs/``; the site's day is ``tb_common.timeutil.today()``."""
    found = []
    for base in ("services", "libs"):
        for f in (ROOT / base).rglob("*.py"):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "today"
                    and isinstance(node.func.value, ast.Name | ast.Attribute)
                    and (node.func.value.id if isinstance(node.func.value, ast.Name) else node.func.value.attr)
                    in ("date", "datetime")
                ):
                    found.append(f"{f.relative_to(ROOT)}:{node.lineno}")
    assert found == []
