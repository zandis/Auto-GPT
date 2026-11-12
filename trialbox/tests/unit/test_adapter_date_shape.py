"""DIN-001 (deep review of 2026-11-12): a feed date that is not a western calendar date is refused, never re-read.

A Taiwanese feed may carry a Republic-of-China date (`1150501` is 2026-05-01, `0490301` is 1960-03-01) and a
two-digit-year form (`640715`). The compact form `%Y%m%d` used to be tried on the first eight characters of whatever
came, and `strptime` accepts a one-digit month, so `1150501` became the year 1150 and the night passed.
"""

from __future__ import annotations

from datetime import date

import pytest
from adapter.mapping.engine import Mapper, MappingError


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
