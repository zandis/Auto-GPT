"""DIN-001 (deep review of 2026-11-12): a feed date that is not a western calendar date is refused, never re-read.

A Taiwanese feed may carry a Republic-of-China date (`1150501` is 2026-05-01, `0490301` is 1960-03-01) and a
two-digit-year form (`640715`). The compact form `%Y%m%d` used to be tried on the first eight characters of whatever
came, and `strptime` accepts a one-digit month, so `1150501` became the year 1150 and the night passed.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from adapter.mapping.engine import LATEST_YEARS_AHEAD, Mapper, Mapping, MappingError


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


# ---------------------------------------------------------------- the adversarial review of PR #323 (2026-11-12)
# H1: a two-digit-year date-time has 12 digits, as a western minute has: `640712081500` (1975-07-12 08:15:00 in a
# YYMMDDhhmmss column) was read as the year 6407, `490312081500` as 4903, `251208151000` as 2512. No patient's
# record is dated more than ``LATEST_YEARS_AHEAD`` years after today, so those are refused; a placeholder
# (`9999-12-31`, `2999-12-31`) is refused with them and no longer stored as a fact (DIN-012).
@pytest.mark.parametrize(
    "raw",
    ["640712081500", "490312081500", "251208151000", "64071208", "6407-12-08 15:00:00", "9999-12-31", "99991231",
     "2999-12-31 00:00:00", "9999-12-31T00:00:00Z", "9999-12-31T00:00:00+08:00"],
)  # fmt: skip
@pytest.mark.parametrize("typ", ["date", "datetime", "instant"])
def test_a_year_far_after_today_is_refused(mapper: Mapper, raw: str, typ: str) -> None:
    with pytest.raises(MappingError, match="not a western calendar date"):
        mapper.convert(raw, typ)


def test_a_date_some_years_ahead_still_reads(mapper: Mapper) -> None:
    ahead = date.today().year + LATEST_YEARS_AHEAD  # a booked visit, the end of a long prescription
    assert mapper.convert(f"{ahead}-03-01", "date") == f"{ahead}-03-01"
    assert mapper.convert(f"{ahead}0301083000", "datetime") == f"{ahead}-03-01T08:30:00+08:00"
    with pytest.raises(MappingError):
        mapper.convert(f"{ahead + 1}-03-01", "date")


# M1: a compact western value with a fraction or a zone after it was read as its date before this card; it still is
# (the fraction is dropped and the time kept; with a zone only the date is read, as before)
@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("20260512083000.000", "2026-05-12T08:30:00+08:00"),
        ("20260512083000.0", "2026-05-12T08:30:00+08:00"),
        ("20260512083000+0800", "2026-05-12T00:00:00+08:00"),
        ("202605120830+0900", "2026-05-12T00:00:00+08:00"),
        ("20260512 0830", "2026-05-12T00:00:00+08:00"),
    ],
)
def test_a_compact_western_value_with_a_tail_still_reads(mapper: Mapper, raw: str, want: str) -> None:
    assert mapper.convert(raw, "datetime") == want
    assert mapper.convert(raw, "date") == "2026-05-12"


@pytest.mark.parametrize("raw", ["1150501083000.000", "11505010830+0800", "640715.0", "1150501 0830"])
def test_a_compact_value_of_another_length_with_a_tail_is_refused(mapper: Mapper, raw: str) -> None:
    for typ in ("date", "datetime"):
        with pytest.raises(MappingError):
            mapper.convert(raw, typ)


# M2: a condition on a date (`date_before` / `date_from`) used to answer "no" to both bounds for a value it could
# not read, so the element was left out with no reject; the row is refused like any other unreadable date
@pytest.mark.parametrize("raw", ["1150501", "115/05/01", "0115-05-01", "640712081500", "not a date"])
def test_a_condition_on_an_unreadable_date_refuses_the_row(mapper: Mapper, raw: str) -> None:
    for cond in ({"column": "d", "date_before": "2025-01-01"}, {"column": "d", "date_from": "2025-01-01"}):
        with pytest.raises(MappingError):
            mapper.cond([cond], {"d": raw})


def test_a_condition_on_a_readable_or_an_empty_date_answers_as_before(mapper: Mapper) -> None:
    assert mapper.cond([{"column": "d", "date_before": "2025-01-01"}], {"d": "2024-06-30"}) is True
    assert mapper.cond([{"column": "d", "date_from": "2025-01-01"}], {"d": "20250101"}) is True
    assert mapper.cond([{"column": "d", "date_from": "2025-01-01"}], {"d": "2024-06-30"}) is False
    assert mapper.cond([{"column": "d", "date_before": "2025-01-01"}], {"d": ""}) is False
    assert mapper.cond([{"column": "d", "date_from": "2025-01-01"}], {"d": None}) is False


# L1: one reason, one message, whatever the column's type and the value's form (the night's report counts rejected
# rows by message with the values taken out)
def test_one_reason_has_one_message(mapper: Mapper) -> None:
    def said(raw: str, typ: str) -> str:
        with pytest.raises(MappingError) as exc:
            mapper.convert(raw, typ)
        return str(exc.value).replace(repr(raw), "<value>")

    old = ["0115-05-01 08:30", "01150501", "011505010830", "0115-05-01", "0115/05/01", "0115-05-01T08:30:00+08:00",
           "0115-05-01T08:30:00Z", "0115-05-01 08:30:00.000"]  # fmt: skip
    assert {said(r, t) for r in old for t in ("datetime", "instant")} == {said("0115-05-01", "date")}
    unread = ["1151001", "2026.05.12", "12 May 2026", "1150501", "x"]
    assert {said(r, "datetime") for r in unread} == {"unparseable datetime <value>"}
    assert {said(r, "date") for r in unread} == {"unparseable date <value>"}
