"""NEW-EDC-13 (D-697, deep-review EDC-016): era and ROC dates in prefill.

(a) A date written in a note as 民國 113年1月10日, 113/01/10 or 令和6年1月10日 could never be drafted: the quote's
digits never held the Gregorian date, and the reason shown was `quote_not_found`. The quote is now read with its era
and ROC years turned into Gregorian ones. (b) A lake date of year 0049 was drafted as a birth date: a drafted date
before 1900 is now `invalid`. Synthetic data only."""

from __future__ import annotations

from datetime import date

import pytest
from datacore.forms import Field
from edc import prefill
from edc.mapping import ItemMap

from tests import edc_kit as k

DATE = Field(name="ae_start", form="ae", kind="date", label="Start")


@pytest.mark.parametrize(
    "quote",
    [
        "回診 民國113年1月10日 痛風發作",
        "民国113年01月10日に受診",
        "onset 113/01/10, right toe",
        "113.01.10 痛風",
        "令和6年1月10日 発症",
        "R06.01.10 発症",
        "R06/01/10 外来",
        "平成31年4月30日 初診",
    ],
)
def test_a_date_written_in_an_era_or_roc_year_is_found_in_its_quote(quote: str) -> None:
    want = "2019-04-30" if "平成" in quote else "2024-01-10"
    assert prefill._value_in_quote(DATE, want, quote)


def test_the_first_year_of_an_era_is_read() -> None:
    assert prefill._value_in_quote(DATE, "2019-05-01", "令和元年5月1日 即位")


@pytest.mark.parametrize(
    ("value", "quote"),
    [
        ("2024-01-10", "民國112年1月10日"),  # another year
        ("2024-01-10", "令和6年1月11日"),  # another day
        ("2024-01-10", "113/13/10"),  # no such month
        ("2024-01-10", "10/01/24"),  # a two-digit year is not read as ROC
        # the review: a phone, a lot number or two numbers side by side are not a date
        ("2024-01-10", "phone 0920240110 x"),
        ("2012-01-01", "113/1/10 2012 0101"),
        ("2024-01-10", "lot 120240110"),
        # the review: a lab flag or a code before three numbers is not an era; an unpadded bare form is not a date
        ("1994-01-10", "CRP H6.1.10"),
        ("2000-01-03", "Hb H12.1.3"),
        ("1926-02-03", "S1.2.3 fracture"),
        ("2011-05-02", "dose 100/5/2"),
        ("2024-01-10", "lab 113.1.10 mg"),
        ("2024-01-10", "R06.01/10"),  # separators that differ
        # the review: an era date that never was
        ("2019-05-01", "平成31年5月1日"),
        ("1989-01-08", "昭和64年1月8日"),
        ("2018-01-01", "令和0年1月1日"),
    ],
)
def test_another_date_or_no_date_is_not_found(value: str, quote: str) -> None:
    assert not prefill._value_in_quote(DATE, value, quote)


def test_a_gregorian_date_is_found_as_before() -> None:
    for quote in ("seen on 2024-01-10 at the clinic", "2024年1月10日", "2024/1/10", "2024.01.10", "on 20240110,"):
        assert prefill._value_in_quote(DATE, "2024-01-10", quote), quote


def test_a_drafted_date_before_1900_is_invalid() -> None:
    facts = k.FakeFacts()
    facts.patients[k.PID]["birth_date"] = date(49, 5, 1)  # a lake date that lost its century
    m = next(prefill_map for prefill_map in _maps() if prefill_map.what == "birth_date")
    f = Field(name=m.item, form="demographics", kind="date", label="Birth date")
    d = prefill.build(k.PID, date(2026, 11, 5), [m], {m.item: f}, facts)[0]
    assert (d.state, d.why, d.value) == ("unknown", "invalid", "")


def _maps() -> list[ItemMap]:
    return [ItemMap.from_dict(x) for x in k.MAP]
