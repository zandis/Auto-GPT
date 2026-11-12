"""DIN-001 (deep review of 2026-11-12): a feed date that is not a western calendar date is refused, never re-read.

A Taiwanese feed may carry a Republic-of-China date (`1150501` is 2026-05-01, `0490301` is 1960-03-01) and a
two-digit-year form (`640715`). The compact form `%Y%m%d` used to be tried on the first eight characters of whatever
came, and `strptime` accepts a one-digit month, so `1150501` became the year 1150 and the night passed.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from adapter.mapping.engine import Mapper, Mapping, MappingError


@pytest.mark.parametrize("raw", ["1150501", "0490301", "640715", "115501", "01150501", "0115-05-01", "0115/05/01"])
def test_a_date_that_is_not_western_is_refused(raw: str) -> None:
    with pytest.raises(MappingError):
        Mapper._parse_date(raw)


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("20260501", date(2026, 5, 1)),
        ("2026-05-01", date(2026, 5, 1)),
        ("2026/05/01", date(2026, 5, 1)),
        ("2026-05-01 08:30:00", date(2026, 5, 1)),
        ("19350102", date(1935, 1, 2)),
    ],
)
def test_a_western_date_still_reads(raw: str, want: date) -> None:
    assert Mapper._parse_date(raw) == want


TW_MAPPING = Path(__file__).resolve().parents[2] / "services" / "adapter" / "mapping" / "tw_core" / "demo_his.yaml"


@pytest.fixture(scope="module")
def mapper() -> Mapper:
    return Mapper(Mapping.load(TW_MAPPING), b"k" * 32, "s")


# most clinical columns are typed `datetime` or `instant`, not `date`: the same refusal holds there. A
# Republic-of-China date-time `1150501083000` (13 digits) matched `%Y%m%d%H%M%S` as the year 1150 with a
# one-digit month; `0115-05-01 08:30:00` matched the dashed form as the year 115.
@pytest.mark.parametrize(
    "raw",
    [
        "1150501083000",
        "11505010830",
        "0115-05-01 08:30:00",
        "0115-05-01 08:30",
        "0115/05/01 08:30:00",
        "0115/05/01 08:30",
        "0115-05-01T08:30:00",
        "0115-05-01T08:30:00+08:00",
        "0115-05-01T08:30:00Z",
        "1150501",
        "640715",
        "640715083000",
        "115050108",
    ],
)
@pytest.mark.parametrize("typ", ["datetime", "instant"])
def test_a_date_time_that_is_not_western_is_refused(mapper: Mapper, raw: str, typ: str) -> None:
    with pytest.raises(MappingError):
        mapper.convert(raw, typ)


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("20260501083000", "2026-05-01T08:30:00+08:00"),
        ("2026-05-01 08:30:00", "2026-05-01T08:30:00+08:00"),
        ("2026/05/01 08:30", "2026-05-01T08:30:00+08:00"),
        ("2026-05-01T08:30:00", "2026-05-01T08:30:00+08:00"),
        ("2026-05-01T08:30:00+09:00", "2026-05-01T08:30:00+09:00"),
        ("2026-05-01", "2026-05-01T00:00:00+08:00"),
        ("20260501", "2026-05-01T00:00:00+08:00"),
        ("1935-01-02 07:00:00", "1935-01-02T07:00:00+08:00"),
    ],
)
def test_a_western_date_time_still_reads(mapper: Mapper, raw: str, want: str) -> None:
    assert mapper.convert(raw, "datetime") == want


# a compact value of another length is not a date with something after it: `202605120830` (12 digits) used to
# be read by `%Y%m%d%H%M%S` as 08:03 (DIN-014), and a date column took the first eight digits of anything.
@pytest.mark.parametrize("raw", ["202605010", "2026050108300", "202605010830001", "2026050", "20260501083"])
@pytest.mark.parametrize("typ", ["date", "datetime"])
def test_a_compact_value_of_another_length_is_refused(mapper: Mapper, raw: str, typ: str) -> None:
    with pytest.raises(MappingError):
        mapper.convert(raw, typ)


def test_twelve_compact_digits_are_a_minute_not_a_second(mapper: Mapper) -> None:
    assert mapper.convert("202605120830", "datetime") == "2026-05-12T08:30:00+08:00"
    assert mapper.convert("202605120830", "date") == "2026-05-12"
    assert mapper.convert("20260512083000", "date") == "2026-05-12"
