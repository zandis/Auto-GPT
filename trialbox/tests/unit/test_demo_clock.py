"""T-513 (UX-003, D-329): one demo clock. The demo day is the real day in the site's zone, the synthetic hospital's
dates move to it, the seed's clock stands at 07:00 site time, and afterwards the console and the box follow the real
clock."""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import feas_demo as fd
from tools import list_demo as ld


@pytest.mark.parametrize(
    ("today", "seed"),
    [
        (date(2026, 11, 9), date(2026, 11, 3)),  # Monday: the Tuesday before the last Wednesday (4 November)
        (date(2026, 11, 10), date(2026, 11, 3)),  # Tuesday: this Wednesday is tomorrow, so last week's
        (date(2026, 11, 11), date(2026, 11, 10)),  # Wednesday: yesterday
        (date(2026, 11, 13), date(2026, 11, 10)),  # Friday (the rehearsal's day: it showed data as of 17 November)
        (date(2026, 11, 14), date(2026, 11, 10)),  # Saturday
        (date(2026, 11, 15), date(2026, 11, 10)),  # Sunday
        (date(2026, 11, 17), date(2026, 11, 10)),  # Tuesday 17 November, the showing
    ],
)
def test_seed_day(today: date, seed: date) -> None:
    assert ld.seed_day(today) == seed


@pytest.mark.parametrize("offset", range(14))
def test_no_seeded_date_is_after_the_demo_day(offset: int) -> None:
    """DEMO-JA (D-584): the seed and the cadence stage after it (the next Tuesday's data, screened on the Wednesday)
    play on or before the demo day, on a working day, so the data date and the run date a viewer sees are not later
    than "today"."""
    today = date(2026, 11, 9) + timedelta(days=offset)
    seed = ld.seed_day(today)
    night = ld.cadence_night(seed)
    assert seed.weekday() < 5 and seed < today
    assert night - timedelta(days=1) <= night <= today  # Tuesday's data, Wednesday's run
    assert (today - seed).days <= 7


def test_demo_day_reads_the_setting() -> None:
    # 23:30 UTC on Tuesday 10 November is Wednesday 11 November in Taipei and Tokyo, still the 10th in London
    late = datetime(2026, 11, 10, 23, 30, tzinfo=UTC)
    assert ld.demo_day("Asia/Taipei", {}) is None
    assert ld.demo_day("Asia/Taipei", {ld.DAY_ENV: "data"}) is None
    # D-584: the seed plays on the Tuesday before the last Wednesday on or before that day
    assert (
        ld.demo_day("Asia/Taipei", {ld.DAY_ENV: "today"}, late) == ld.seed_day(date(2026, 11, 11)) == date(2026, 11, 10)
    )
    assert (
        ld.demo_day("Europe/London", {ld.DAY_ENV: "today"}, late)
        == ld.seed_day(date(2026, 11, 10))
        == date(2026, 11, 3)
    )
    assert ld.demo_day("Asia/Tokyo", {ld.DAY_ENV: "2026-12-01"}) == date(2026, 12, 1)
    with pytest.raises(SystemExit, match="TB_DEMO_DAY"):
        ld.demo_day("Asia/Tokyo", {ld.DAY_ENV: "tomorrow"})
    assert ld.is_live({ld.DAY_ENV: "today"}) and not ld.is_live({ld.DAY_ENV: "2026-12-01"}) and not ld.is_live({})


def test_the_seed_clock_is_seven_in_the_morning_site_time() -> None:
    """The old clock was 07:00 at UTC+9 on every site: 06:00 in Taipei, and the digest list then read 22:00 UTC."""
    taipei = ld.Clock(date(2026, 11, 2), "Asia/Taipei")
    assert taipei() == datetime(2026, 11, 1, 23, 0, tzinfo=UTC)
    tokyo = ld.Clock(date(2026, 11, 2), "Asia/Tokyo")
    assert tokyo() == datetime(2026, 11, 1, 22, 0, tzinfo=UTC)
    tokyo.go_live()
    assert abs((tokyo() - datetime.now(UTC)).total_seconds()) < 60


def test_go_live_moves_the_box_with_the_console() -> None:
    from console.timefmt import local_today

    box = SimpleNamespace(today=[date(2026, 11, 2)], orch=SimpleNamespace(_today=lambda: date(2026, 11, 2)))
    clock = ld.Clock(date(2026, 11, 2), "Asia/Tokyo")
    ld.go_live(box, clock)
    now = local_today(datetime.now(UTC), clock.zone)
    assert box.orch._today() == box.today[0] == now == local_today(clock(), clock.zone)


def test_shift_dates_moves_dates_and_keeps_intervals(tmp_path: Path) -> None:
    rows = [
        {
            "mrn": "x1",
            "appt_datetime": "2026-11-02 10:40:00",
            "birth": "1960-02-28",
            "phone": "090-1234-5678",
            "note": "seen 2026-10-01",
            "id_no": "00240718",
            "empty": "",
        },
    ]
    f = tmp_path / "appointment.csv"
    with f.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    assert fd.shift_dates(tmp_path, 0) == 0
    assert fd.shift_dates(tmp_path, 9) == 2
    with f.open(encoding="utf-8") as fh:
        (got,) = list(csv.DictReader(fh))
    assert got["appt_datetime"] == "2026-11-11 10:40:00" and got["birth"] == "1960-03-08"
    # not a date cell: left as it was (note text is not rewritten)
    assert got["phone"] == "090-1234-5678" and got["note"] == "seen 2026-10-01" and got["id_no"] == "00240718"
    assert date.fromisoformat(got["appt_datetime"][:10]) - date.fromisoformat(got["birth"]) == date(2026, 11, 2) - date(
        1960, 2, 28
    )


def test_the_data_day_is_the_box_day_after_the_reference() -> None:
    assert fd.data_day() == fd.REF + timedelta(days=1) == date(2026, 11, 2)
