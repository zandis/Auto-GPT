"""Step-2 follow-up: user-facing times show in the site's time zone, not UTC (S20 ticks, S5 marks, log)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from console.timefmt import local_date, local_time, site_zone
from fastapi.templating import Jinja2Templates

TOKYO = ZoneInfo("Asia/Tokyo")


def test_utc_evening_is_the_next_tokyo_morning() -> None:
    # a mark made at 07:00 in Tokyo is stored as 22:00 UTC the day before
    assert local_time("2026-11-01T22:00:00+00:00", TOKYO) == "2026-11-02 07:00"
    assert local_time("2026-11-01T22:00:00", TOKYO) == "2026-11-02 07:00"  # naive means UTC
    assert local_time("2026-11-01T22:00:00Z", TOKYO, 19) == "2026-11-02 07:00:00"
    assert local_date("2026-11-01T22:00:00+00:00", TOKYO) == "2026-11-02"
    assert local_time(datetime(2026, 11, 1, 22, tzinfo=UTC), TOKYO) == "2026-11-02 07:00"


def test_dates_and_odd_values_pass_through() -> None:
    assert local_time("2026-11-30", TOKYO) == "2026-11-30"
    assert local_time("", TOKYO) == "" and local_time(None, TOKYO) == ""
    assert local_time("not a time at all", TOKYO, 10) == "not a time"


def test_site_zone_comes_from_the_backend_config() -> None:
    bk = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(tz="Asia/Tokyo")))
    assert site_zone(bk) == TOKYO
    bad = SimpleNamespace(cfg=SimpleNamespace(env=SimpleNamespace(tz="Mars/Olympus")))
    assert site_zone(bad) == ZoneInfo("UTC")
    both = SimpleNamespace(
        cfg=SimpleNamespace(
            env=SimpleNamespace(tz="Asia/Taipei"), settings=SimpleNamespace(site=SimpleNamespace(tz="Asia/Tokyo"))
        )
    )
    assert site_zone(both) == TOKYO  # site.tz wins over env.tz (a box built without config.load)


def test_templates_use_the_local_filter(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pathlib import Path

    import console

    tpl = Path(console.__file__).parent / "templates"
    for name in ("approval.html", "patient.html", "_mark.html", "screening_log.html", "_audit_table.html"):
        text = (tpl / name).read_text(encoding="utf-8")
        assert "|local" in text, name
        assert ".at[:16]" not in text and ".at[:10]" not in text, name
    env = Jinja2Templates(directory=str(tpl)).env
    env.filters["local"] = lambda v, n=16: local_time(v, TOKYO, n)
    out = env.from_string("{{ at|local }} / {{ at|local(10) }}").render(at="2026-11-01T22:00:00+00:00")
    assert out == "2026-11-02 07:00 / 2026-11-02"
