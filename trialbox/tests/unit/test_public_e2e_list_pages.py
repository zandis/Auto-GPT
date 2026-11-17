"""The public run finds its patients on any page of the PI's list (D-974).

`tools.public_e2e` stage 3 took the first three rows of the week's mail list and looked for them on the PI's list
page. That page shows 25 rows at a time (`console.studies.PAGE_SIZE`), in its own order (the fewest criteria still
open first). Since D-914 (train 42: a record that is not there never excludes) the public site lists 215 patients, and
two of the three were on later pages: the check failed every night from train 42 on, with the page itself correct.
The check now reads the pages, following the list's own next-page link, until it has seen every patient's row.
"""

from __future__ import annotations

from dataclasses import dataclass

from tools import public_e2e as pe


@dataclass
class Resp:
    status_code: int
    text: str


def _site(pages: list[list[str]]):  # type: ignore[no-untyped-def]
    asked: list[str] = []

    def get(path: str) -> Resp:
        asked.append(path)
        n = int(path.rsplit("page=", 1)[1]) if "page=" in path else 1
        rows = pages[n - 1]
        more = '<a data-testid="next-page" href="?">next</a>' if n < len(pages) else ""
        return Resp(200, "".join(f'<tr data-testid="row-{s}"></tr>' for s in rows) + more)

    return get, asked


def test_patients_on_later_pages_are_found() -> None:
    get, asked = _site([["aaaa0001", "aaaa0002"], ["bbbb0001"], ["cccc0001", "aaaa0009"]])
    status, missing = pe.find_on_list(get, "/studies/X/week?list=all", ["aaaa0001", "cccc0001"])
    assert (status, missing) == (200, [])
    assert len(asked) == 3


def test_reading_stops_once_every_patient_is_seen() -> None:
    get, asked = _site([["aaaa0001"], ["bbbb0001"], ["cccc0001"]])
    assert pe.find_on_list(get, "/studies/X/week?list=all", ["aaaa0001"]) == (200, [])
    assert len(asked) == 1


def test_a_patient_on_no_page_is_missing() -> None:
    get, _ = _site([["aaaa0001"], ["bbbb0001"]])
    assert pe.find_on_list(get, "/studies/X/week?list=all", ["aaaa0001", "dddd0001"]) == (200, ["dddd0001"])


def test_a_short_id_elsewhere_on_the_page_is_not_a_row() -> None:
    """Only the patient's own row counts, not the same eight characters anywhere in the page."""

    def get(path: str) -> Resp:
        return Resp(200, '<p>see aaaa0001</p><tr data-testid="row-bbbb0001"></tr>')

    assert pe.find_on_list(get, "/x?list=all", ["aaaa0001"]) == (200, ["aaaa0001"])


def test_a_page_that_is_not_200_stops_with_its_status() -> None:
    def get(path: str) -> Resp:
        return Resp(500, "")

    assert pe.find_on_list(get, "/x?list=all", ["aaaa0001"]) == (500, ["aaaa0001"])
