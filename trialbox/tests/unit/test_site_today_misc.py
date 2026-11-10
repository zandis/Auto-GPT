"""D-270 (integrity review DI-14): two more "today" reads outside the console use the site's date."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest


def test_the_night_gate_is_keyed_by_the_site_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """03:00 on 2026-11-10 in Tokyo is 18:00 on 11-09 in UTC: the self-test result belongs to the site's night."""
    import orchestrator.selftest as selftest
    import tb_common.timeutil as timeutil
    from orchestrator import scheduler

    asked: list[str] = []

    def now(tz: str = "Asia/Taipei") -> datetime:
        asked.append(tz)
        return datetime(2026, 11, 9, 18, 0, tzinfo=UTC).astimezone(ZoneInfo(tz))

    monkeypatch.setattr(timeutil, "now", now)
    monkeypatch.setattr(selftest, "preflight", lambda _orch: True)
    monkeypatch.setattr(scheduler, "_gate", {})
    orch: Any = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Tokyo")))
    assert scheduler.night_gate(orch) is True
    assert asked == ["Asia/Tokyo"] and list(scheduler._gate) == ["2026-11-10"]


def test_the_dqd_command_reads_the_site_date() -> None:
    from omop.__main__ import _site_today

    at = datetime(2026, 12, 31, 15, 30, tzinfo=UTC)  # 00:30 on 2027-01-01 in Tokyo
    assert _site_today("Asia/Tokyo", at) == date(2027, 1, 1) and _site_today("Asia/Taipei", at) == date(2026, 12, 31)
    assert _site_today("", at) is None
