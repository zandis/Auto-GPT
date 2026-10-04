"""Retention rules (SPEC §10.3) as pure functions, shared by the orchestrator's daily RETENTION job and the adapter's
snapshot pruning."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from tb_common.timeutil import add_months


def snapshots_to_keep(snapshots: Iterable[str], today: date, nightly: int = 3, month_end_months: int = 36) -> set[str]:
    """Keep the last ``nightly`` snapshots plus the last snapshot of each of the last ``month_end_months`` completed
    months (the month-end history FEAS/COHORT use; the current month is covered by the nightly ones). Snapshot names
    are ISO dates."""
    snaps = sorted(set(snapshots))
    keep = set(snaps[-nightly:]) if nightly > 0 else set()
    this_month = today.replace(day=1)
    oldest = add_months(this_month, -month_end_months)
    by_month: dict[str, str] = {}
    for s in snaps:
        d = date.fromisoformat(s)
        if oldest <= d < this_month:
            by_month[s[:7]] = max(by_month.get(s[:7], s), s)
    keep |= set(by_month.values())
    return keep


def expired(last_modified: datetime, now: datetime, days: int) -> bool:
    return days > 0 and last_modified < now - timedelta(days=days)
