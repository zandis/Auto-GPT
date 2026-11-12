"""NEW-PERF-3 (D-529; PERF-009): a night dated after the site's today is refused.

One night with a future date (a host clock wrong for one night, a re-run typed with a wrong date) became the
served night. Every later night was older than it, so none was ever served again, and a future night counted as
0 days old, so the staleness check never fired: the box served that one night for weeks."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from adapter.ndjson import snapshot_dir
from adapter.pipeline import run_ingest
from lake.store import StaleSnapshotError, check_snapshot_age, snapshot_age_days

from tests.unit.test_dataflow_lake_p0 import _cfg, _csv, _Lakes, _row


def _today(cfg_tz: str) -> date:
    return datetime.now(ZoneInfo(cfg_tz)).date()


def test_a_night_dated_after_today_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _csv(tmp_path / "n1", [_row("D1", "2026-09-01")])
    tomorrow = (_today(cfg.tz) + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="dated after today"):
        run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot=tomorrow, load_fhir=False, validate=False)
    assert not snapshot_dir(cfg.lake_dir, tomorrow).exists() and lakes.calls == []
    assert lakes.lake.current() is None
    # today's night, and an earlier one, go on as before
    today = _today(cfg.tz).isoformat()
    rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot=today, load_fhir=False, validate=False)
    assert rep.passed and lakes.lake.current() == today


@pytest.mark.nodb
def test_a_served_night_dated_after_today_is_not_zero_days_old() -> None:
    """The pin: a job never reads a night dated after its own day (it was "0 days old" and passed the age check).
    Refused whatever the age limit, 0 ("no check") included: this is not an age."""
    today = date(2026, 10, 8)
    assert snapshot_age_days("2026-10-08", today) == 0 and snapshot_age_days("2026-10-01", today) == 7
    for limit in (0, 7):
        with pytest.raises(StaleSnapshotError, match="dated after"):
            check_snapshot_age("2027-01-01", today, limit)
    assert check_snapshot_age("2026-10-08", today, 7) == 0 and check_snapshot_age("2026-10-08", today, 0) is None
