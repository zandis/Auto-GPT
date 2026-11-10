"""One date reader (T-118, D-215; review E-05, MR-015): ``tb_common.dates``.

Part 1 pins what the six modules that read or find dates (PHI guard, the stub chart reader, CASE, site set-up's
chart-date finder, the messy-sheet cell reader and the guard's DOB recogniser) returned before they became callers of
``tb_common.dates``: ``tests/fixtures/dates/six_modules.json`` was recorded from origin/master before the module
existed and is replayed here through the modules as they are now, byte for byte. The one intended change is
:data:`CHANGED`: MR-015, ``112年3月15日`` (the ROC year with 年 and no 民國) is now read by the sheet reader.

Part 2 tests :mod:`tb_common.dates` itself: examples, the ``check_dates`` refusals, round-trip sweeps over every form
and (when ``hypothesis`` is installed) the same properties drawn at random.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from guard import recognisers
from llm_stub import handlers
from orchestrator.scenarios import case
from sitesetup import messy, service
from tb_common import dates, phi_guard

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "dates" / "six_modules.json"
CASES: dict[str, dict[str, Any]] = json.loads(RECORDED.read_text(encoding="utf-8"))["cases"]
# the intended behaviour change (MR-015, R-95): input -> {field: value now}; every other field of every input is equal
CHANGED: dict[str, dict[str, Any]] = {
    "112年3月15日": {
        "messy": ["2023-03-15", "minguo", None, None],
        "messy_noserial": "2023-03-15",
        "dmy": "2023-03-15",
    },
}


def _now(s: str) -> dict[str, Any]:
    p = messy.parse_date(s)
    found = case.find_date(s)
    return {
        "phi": phi_guard.DATE.findall(s),
        "stub": handlers._DATE_ANY.findall(s),
        "case": None if found is None else found.isoformat(),
        "first": service._first_date(s),
        "messy": [p.iso, p.kind, p.problem, p.suggestion],
        "messy_noserial": messy.parse_date(s, serial=False).iso,
        "dmy": messy.parse_date(s, "dmy").iso,
        "dob": [m.group("v") for m in recognisers.DOB.finditer(s)],
        "date_re": re.findall(recognisers._DATE, s),
    }


@pytest.mark.parametrize("text", sorted(CASES))
def test_the_six_modules_answer_as_recorded(text: str) -> None:
    assert _now(text) == CASES[text] | CHANGED.get(text, {})


def test_the_detector_patterns_are_the_old_ones_byte_for_byte() -> None:
    """The span patterns the detectors now take from tb_common.dates are the strings they compiled before."""
    stub = (
        r"(?:(?:令和|平成|昭和|R|H|S)\s?\d{1,2}[./年]\s?\d{1,2}[./月]\s?\d{1,2}日?)"
        r"|(?:民國\s?\d{2,3}[./年]\s?\d{1,2}[./月]\s?\d{1,2}日?)"
        r"|(?:(?:19|20)\d{2}[-/.年]\s?\d{1,2}[-/.月]\s?\d{1,2}日?)"
    )
    assert handlers._DATE_ANY.pattern == stub and dates.CHART_SPAN.pattern == stub
    phi = r"(?:19|20)\d{2}[/\-.年]\s?\d{1,2}[/\-.月]\s?\d{1,2}日?|民國\s?\d{2,3}年\s?\d{1,2}月\s?\d{1,2}日"
    assert phi_guard.DATE.pattern == phi
    dob = (
        r"(?:(?:19|20)\d{2}[/\-.]\d{1,2}[/\-.]\d{1,2}|(?:19|20)\d{2}年\s?\d{1,2}月\s?\d{1,2}日"
        r"|民國\s?\d{2,3}年\s?\d{1,2}月\s?\d{1,2}日|(?:昭和|平成|令和)\s?(?:\d{1,2}|元)年\s?\d{1,2}月\s?\d{1,2}日"
        r"|\d{1,2}/\d{1,2}/(?:19|20)\d{2}"
        r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, (?:19|20)\d{2})"
    )
    assert dob == recognisers._DATE
    assert messy.ERAS is dates.ERAS and messy._ERA is dates.CELL_ERA and case.find_date("R8.3.14") == date(2026, 3, 14)


# ------------------------------------------------------------------------------------------------ tb_common.dates
@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        ("112年3月15日", None, date(2023, 3, 15)),  # MR-015
        ("112年3月15日", "ja", date(2023, 3, 15)),  # three digits: only ROC
        ("１１２年３月１５日", "zh-TW", date(2023, 3, 15)),
        ("112 年 3 月 15 日", "zh-TW", date(2023, 3, 15)),
        ("民國112年3月15日", "zh-TW", date(2023, 3, 15)),
        ("中華民國112年3月15日", None, date(2023, 3, 15)),
        ("112/03/15", None, date(2023, 3, 15)),
        ("1120315", None, date(2023, 3, 15)),
        ("99年3月15日", "zh-TW", date(2010, 3, 15)),  # ROC 99 in Taiwan
        ("令和5年3月1日", "ja", date(2023, 3, 1)),
        ("令和元年5月1日", "ja", date(2019, 5, 1)),
        ("R5.3.1", None, date(2023, 3, 1)),
        ("Ｈ３１．４．３０", None, date(2019, 4, 30)),
        ("昭和64年1月7日", "ja", date(1989, 1, 7)),
        ("2026-03-14", "en", date(2026, 3, 14)),
        ("2026年3月14日", "ja", date(2026, 3, 14)),
        ("2026/3/14 09:30", None, date(2026, 3, 14)),
        ("20260314", None, date(2026, 3, 14)),
    ],
)
def test_parse_reads(text: str, lang: str | None, expected: date) -> None:
    assert dates.parse(text, lang) == expected
    assert dates.read(text, lang) == (expected, None)


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("99年3月15日", "ja"),  # 1999 in Japan, ROC 99 in Taiwan: not guessed without the language
        ("99年3月15日", None),
        ("212年3月15日", "zh-TW"),  # no ROC year 212 yet, and not a Gregorian year
        ("平成31年5月1日", "ja"),  # 平成 had ended on 2019-04-30
        ("令和元年4月30日", "ja"),  # 令和 began on 2019-05-01
        ("民國112年2月30日", "zh-TW"),
        ("2026-02-30", None),
        ("03/04/2026", None),  # 3 April or 4 March
        ("3/4/26", None),
        ("45000", None),  # an Excel serial is the sheet reader's question, not a date
        ("someday", "en"),
        ("2026-03-14 and 2026-03-15", None),  # two dates are not one
        ("0112/03/15", "zh-TW"),  # Fable M2: a four-digit year outside 1900-2099 is not read
        ("1120-3-15", None),
    ],
)
def test_parse_refuses_what_it_cannot_read_for_certain(text: str, lang: str | None) -> None:
    assert dates.parse(text, lang) is None
    assert dates.read(text, lang) == (None, "check_dates")


def test_read_without_text_is_no_date_not_a_check() -> None:
    assert (
        dates.read("", "ja") == (None, None) and dates.read(None) == (None, None) and dates.read("　") == (None, None)
    )


def test_era_false_reads_gregorian_only() -> None:
    assert dates.parse("2026-03-14", era=False) == date(2026, 3, 14)
    for text in ("R5.3.1", "令和5年3月1日", "民國112年3月15日", "112年3月15日", "1120315"):
        assert dates.parse(text, "zh-TW", era=False) is None


def test_check_dates_is_a_reason_code_with_words() -> None:
    from tb_common.reasons import CODES, LABELS

    assert dates.CHECK_DATES in CODES and set(LABELS[dates.CHECK_DATES]) == {"en", "ja", "zh-TW"}


# ------------------------------------------------------------------------------------------------ round trips
def _forms(d: date) -> list[tuple[str, str | None]]:
    """Every way the module reads ``d``, with the language it needs."""
    out: list[tuple[str, str | None]] = [
        (d.isoformat(), None),
        (f"{d.year}/{d.month}/{d.day}", None),
        (f"{d.year}年{d.month}月{d.day}日", "ja"),
        (d.strftime("%Y%m%d"), None),
    ]
    roc = d.year - dates.MINGUO_OFFSET
    if roc >= 1:
        out += [(f"民國{roc}年{d.month}月{d.day}日", "zh-TW"), (f"民國{roc:03d}.{d.month:02d}.{d.day:02d}", None)]
    if 100 <= roc <= 199:
        out += [
            (f"{roc}年{d.month}月{d.day}日", None),
            (f"{roc}/{d.month:02d}/{d.day:02d}", None),
            (f"{roc}{d.month:02d}{d.day:02d}", None),
        ]
    if 10 <= roc <= 99:
        out.append((f"{roc}年{d.month}月{d.day}日", "zh-TW"))
    for name, (offset, first, last) in dates.ERAS.items():
        if first <= d and (last is None or d <= last):
            n = d.year - offset
            year = "元" if n == 1 else str(n)
            out.append((f"{name}{year}年{d.month}月{d.day}日", "ja"))
            letter = next(k for k, v in dates.ERA_ABBR.items() if v == name)
            if n >= 1:
                out.append((f"{letter}{n}.{d.month}.{d.day}", None))
    return out


def _wide(text: str) -> str:
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)


def test_every_form_round_trips_over_a_century_and_a_half() -> None:
    """A sweep of days from 1912 to 2099, every 23 days (both eras' edges included), in every form and full width."""
    days = [date(1912, 1, 1) + timedelta(days=23 * i) for i in range(2900)]
    days += [date(1989, 1, 7), date(1989, 1, 8), date(2019, 4, 30), date(2019, 5, 1), date(2024, 2, 29)]
    for d in days:
        for text, lang in _forms(d):
            assert dates.parse(text, lang) == d, (text, lang)
            assert dates.parse(_wide(text), lang) == d, (text, lang)


def test_era_year_is_base_plus_n() -> None:
    for name, (offset, first, last) in dates.ERAS.items():
        end = (last or date(2099, 12, 31)).year
        for n in range(1, end - offset + 1):
            d = dates.parse(f"{name}{n}年7月1日", "ja")
            inside = first <= date(offset + n, 7, 1) and (last is None or date(offset + n, 7, 1) <= last)
            assert d == (date(offset + n, 7, 1) if inside else None), (name, n)


def test_round_trip_property() -> None:
    hypothesis = pytest.importorskip("hypothesis", reason="hypothesis is not a dev dependency yet (T-118 remains)")
    st = pytest.importorskip("hypothesis.strategies")

    def prop(d: date, wide: bool) -> None:
        for text, lang in _forms(d):
            assert dates.parse(_wide(text) if wide else text, lang) == d

    hypothesis.settings(max_examples=400, deadline=None)(
        hypothesis.given(st.dates(min_value=date(1912, 1, 1), max_value=date(2099, 12, 31)), st.booleans())(prop)
    )()


def test_never_raises_property() -> None:
    hypothesis = pytest.importorskip("hypothesis", reason="hypothesis is not a dev dependency yet (T-118 remains)")
    st = pytest.importorskip("hypothesis.strategies")
    alphabet = st.sampled_from(list("0123456789０１２３４５６７８９年月日民國令和平成昭和RHS./- 　元"))

    def prop(text: str, lang: str | None) -> None:
        d, why = dates.read(text, lang)
        assert (d is None) == (why is not None) or (d is None and why is None and not text.strip())

    hypothesis.settings(max_examples=600, deadline=None)(
        hypothesis.given(st.text(alphabet, max_size=16), st.sampled_from([None, "ja", "zh-TW", "en"]))(prop)
    )()
