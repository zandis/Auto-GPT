"""WALK-1 (lane H's H-20, F-16): a closed study's "kept until" is the close's own site day plus the period.

A close at 2026-11-02 07:00 site time (Taipei, 2026-11-01 23:00 UTC) with 5 years showed "kept until 2031-11-01":
the period was counted from the UTC day of the stored instant, a day before the site's. D-779 says the close's own
day. Synthetic dates only."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from tb_common.retention import held_after_close, kept_until

CLOSED_AT = datetime(2026, 11, 1, 23, 0, tzinfo=UTC).isoformat()  # 2026-11-02 07:00 in Taipei
TPE = ZoneInfo("Asia/Taipei")


def test_kept_until_counts_from_the_sites_day() -> None:
    assert kept_until(CLOSED_AT, 5, TPE) == date(2031, 11, 2)
    assert kept_until(CLOSED_AT, 5) == date(2031, 11, 1)  # no zone given: the instant's own day, as before


def test_held_after_close_reads_both_days_on_the_site() -> None:
    # 2031-11-01 20:00 site time: still the last day the files are held
    assert held_after_close(CLOSED_AT, 5, datetime(2031, 11, 1, 12, 0, tzinfo=UTC).astimezone(TPE))
    # 2031-11-02 08:00 site time (2031-11-02 00:00 UTC): the period has ended
    assert not held_after_close(CLOSED_AT, 5, datetime(2031, 11, 2, 0, 0, tzinfo=UTC).astimezone(TPE))
