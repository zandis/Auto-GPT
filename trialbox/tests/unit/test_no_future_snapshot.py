"""NEW-PERF-3 (D-529; PERF-009): a night dated after the site's today is refused.

One night with a future date (a host clock wrong for one night, a re-run typed with a wrong date) became the
served night. Every later night was older than it, so none was ever served again, and a future night counted as
0 days old, so the staleness check never fired: the box served that one night for weeks."""

from __future__ import annotations

import json
import shutil
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
    tomorrow = (_today(cfg.tz) + timedelta(days=2)).isoformat()  # two days: the run reads its own clock later
    with pytest.raises(ValueError, match="dated after today"):
        run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot=tomorrow, load_fhir=False, validate=False)
    assert not snapshot_dir(cfg.lake_dir, tomorrow).exists() and lakes.calls == []
    assert lakes.lake.current() is None
    events = [json.loads(x) for f in sorted((tmp_path / "audit").rglob("*")) if f.is_file()
              for x in f.read_text(encoding="utf-8").splitlines()]  # fmt: skip
    (refused,) = [e for e in events if (e.get("detail") or {}).get("refused") == "future_night"]
    assert refused["event"] == "ingest.failed"
    assert refused["detail"]["refused"] == "future_night" and "dated after today" in refused["detail"]["reason"]
    # today's night, and an earlier one, go on as before
    today = _today(cfg.tz).isoformat()
    rep = run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot=today, load_fhir=False, validate=False)
    assert rep.passed and lakes.lake.current() == today


@pytest.mark.nodb
def test_a_served_night_dated_after_today_is_not_zero_days_old(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pin: a job never reads a night dated after its own day (it was "0 days old" and passed the age check).
    Refused whatever the age limit, 0 ("no check") included: this is not an age."""
    monkeypatch.delenv("TB_TODAY", raising=False)
    today = date(2026, 10, 8)
    assert snapshot_age_days("2026-10-08", today) == 0 and snapshot_age_days("2026-10-01", today) == 7
    for limit in (0, 7):
        with pytest.raises(StaleSnapshotError, match="dated after"):
            check_snapshot_age("2027-01-01", today, limit)
    assert check_snapshot_age("2026-10-08", today, 7) == 0 and check_snapshot_age("2026-10-08", today, 0) is None
    # the test stack pins the box's day behind its feed on purpose (TB_TODAY): there the night is 0 days old
    monkeypatch.setenv("TB_TODAY", "2026-10-05")
    assert check_snapshot_age("2027-01-01", today, 7) == 0


def test_a_stewards_accept_does_not_serve_a_night_dated_after_today(tmp_path: Path) -> None:
    """Review HIGH: a night held under a future name (left on disk from before this rule) was published by the
    steward's accept: it goes through the publish, not through the ingest."""
    from adapter.pipeline import HELD, PASSED
    from adapter.publish import RECORD, publish_held

    lakes = _Lakes(tmp_path / "lake")
    cfg = _cfg(tmp_path, lakes)
    _csv(tmp_path / "n1", [_row("D1", "2026-09-01")])
    served = (_today(cfg.tz) - timedelta(days=3)).isoformat()
    assert run_ingest(cfg, "csv", str(tmp_path / "n1"), snapshot=served, load_fhir=False, validate=False).passed
    future = (_today(cfg.tz) + timedelta(days=30)).isoformat()
    held = snapshot_dir(cfg.lake_dir, future)
    shutil.copytree(snapshot_dir(cfg.lake_dir, served), held)
    for name in (PASSED, RECORD):
        (held / name).unlink(missing_ok=True)
    (held / HELD).write_text(json.dumps({"snapshot": future, "why": "gate"}), encoding="utf-8")
    calls = list(lakes.calls)
    out = publish_held(cfg, future)
    assert not out.promoted and lakes.lake.current() == served and lakes.calls == calls  # nothing built or served
    assert any("dated after today" in e for e in out.errors), out.errors


def test_the_first_load_refuses_it_too(tmp_path: Path) -> None:
    from adapter.backfill import backfill

    cfg = _cfg(tmp_path, _Lakes(tmp_path / "lake"))
    _csv(tmp_path / "n1", [_row("D1", "2026-09-01")])
    future = (_today(cfg.tz) + timedelta(days=2)).isoformat()
    with pytest.raises(ValueError, match="dated after today"):
        backfill(cfg, "csv", str(tmp_path / "n1"), snapshot=future, validate=False)
    assert not (cfg.lake_dir / "backfill" / future).exists()
