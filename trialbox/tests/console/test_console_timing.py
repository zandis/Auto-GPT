# ruff: noqa: F811 - the box fixture is imported and taken by name
"""D-1245 (card 10E-13, review 13 item 13-14): the console's ``Server-Timing`` header and the timing walk's rules.

* each of the walk's ten pages answers ``200`` with one header, ``total;dur=<ms>``, and nothing else in it (no path,
  account, study or patient);
* a refused page and a page that does not exist answer alike: neither carries the header;
* the header changes no page body: the ten bodies are byte for byte the same with the timing middleware taken out;
* the walk: nearest-rank p95, the header read (never a client clock), a page over the budget walked once more;
  **a planted slow page fails** (a route this test adds to its own app, never shipped), the ten real pages pass;
  a page that was slow once (a runner's burst) and fast on the second walk passes.

The walk itself, at its full warm-up and repeat, is ``tests/perf/test_console_timing_walk.py`` (marker ``perf``,
nightly). Synthetic data only."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

import pytest
from console import timing
from fastapi.responses import HTMLResponse

from tests.console.test_console_app import box, login  # noqa: F401
from tests.console.timing_walk import TEN, clients, getter, ten_pages
from tools import console_timing as ct


# ---------------------------------------------------------------------------------------------- the header
def test_each_walk_page_carries_one_server_timing_header_with_numbers_only(box: dict[str, Any]) -> None:
    for page in ten_pages(box):
        status, headers = page.get(page.path)
        assert status == 200, page.name
        got = headers.get_list("server-timing")  # type: ignore[attr-defined]
        assert len(got) == 1 and timing.SHAPE.match(got[0]), (page.name, got)
        ms = ct.server_ms(headers)
        assert ms is not None and ms >= 0


def test_a_refused_page_and_a_missing_page_answer_alike(box: dict[str, Any]) -> None:
    cs = clients(box)
    crc = cs["coordinator"]
    refused = crc.get("/admin/ops", follow_redirects=False)  # the administrator's page
    missing = crc.get("/pilot/jobs/" + "0" * 26, follow_redirects=False)  # no such job
    for r in (refused, missing):
        assert r.status_code in (403, 404) and "server-timing" not in r.headers, r.status_code
    assert refused.status_code == 403 and missing.status_code == 404
    assert set(refused.headers) - {"content-length"} == set(missing.headers) - {"content-length"}
    signed_out = login(box["app"])[0]
    signed_out.cookies.clear()
    r = signed_out.get("/home", follow_redirects=False)  # sent to sign in
    assert r.status_code != 200 and "server-timing" not in r.headers


#: a page that lists the console's own audit events changes at each read (its own read is one): compared by its
#: frame (everything but the rows), the others byte for byte
VOLATILE = {"audit trail"}


def test_the_header_search_carries_no_timing_whatever_it_finds(box: dict[str, Any]) -> None:
    """D-1241: the field answers an account off the log as it answers a number that does not exist, every header
    included; a time would differ between the two, so no answer of ``/cmd`` carries one."""
    crc = clients(box)["coordinator"]
    for q in ("GZQO-0001", "ZZZZ-9999", "aaaaaaaa", "", "/home"):
        r = crc.get("/cmd", params={"q": q}, follow_redirects=False)
        assert "server-timing" not in r.headers, (q, r.status_code)
    assert timing.timed(200, "/home") and not timing.timed(200, "/cmd") and not timing.timed(404, "/home")


def test_the_header_changes_no_page_body(box: dict[str, Any]) -> None:
    app = box["app"]
    pages = ten_pages(box)
    cs, who = clients(box), {name: role for name, _, role in TEN}

    def getter_body(page: ct.Page) -> bytes:
        return bytes(cs[who[page.name]].get(page.path, follow_redirects=False).content)

    with_header = {p.name: getter_body(p) for p in pages}
    for p in pages:  # each page but the volatile one answers the same body twice
        assert (getter_body(p) == with_header[p.name]) is (p.name not in VOLATILE), p.name
    kept = [m for m in app.user_middleware if getattr(m.kwargs.get("dispatch"), "__name__", "") != "server_timing"]
    assert len(kept) == len(app.user_middleware) - 1  # the timing middleware, and only it, taken out
    app.user_middleware[:] = kept
    app.middleware_stack = None  # rebuilt at the next request without it
    for p in pages:
        status, headers = p.get(p.path)
        assert status == 200 and "server-timing" not in headers, p.name
        body = getter_body(p)
        if p.name in VOLATILE:
            assert _frame(body) == _frame(with_header[p.name]), p.name
        else:
            assert body == with_header[p.name], p.name


def _frame(body: bytes) -> bytes:
    return re.sub(rb"<tbody>.*?</tbody>", b"<tbody/>", body, flags=re.S)


# ---------------------------------------------------------------------------------------------- the walk's rules
def test_percentile_is_nearest_rank_and_the_header_is_read() -> None:
    times = [float(i) for i in range(1, 61)]  # 1..60
    assert ct.percentile(times, 95) == 57.0 and ct.percentile(times, 50) == 30.0
    assert ct.percentile([], 95) == float("inf")
    assert ct.server_ms({"server-timing": "total;dur=12.5"}) == 12.5
    assert ct.server_ms({"server-timing": "db;dur=3, total;dur=7"}) == 7.0
    assert ct.server_ms({"server-timing": "total"}) is None and ct.server_ms({}) is None


def _fake(times: list[float], status: int = 200) -> ct.Page:
    it: Iterator[float] = iter(times)

    def get(_: str) -> ct.Answer:
        return status, {"server-timing": timing.value(next(it))}

    return ct.Page("fake", "/fake", get)


def test_three_slow_answers_in_sixty_pass_and_four_fail() -> None:
    three = [10.0] * 10 + [10.0] * 57 + [900.0] * 3
    four = [10.0] * 10 + [10.0] * 56 + [900.0] * 4
    assert not ct.walk([_fake(three)]).failed()
    rep = ct.walk([_fake(four + four)])  # over twice: fails
    assert [t.name for t in rep.failed()] == ["fake"] and rep.pages[0].again is not None


def test_a_burst_on_the_first_walk_alone_does_not_fail() -> None:
    first = [10.0] * 10 + [900.0] * 60  # a runner busy for the whole first walk of the page
    second = [10.0] * 70
    rep = ct.walk([_fake(first + second)])
    assert not rep.failed() and rep.pages[0].again is not None
    assert rep.rows()[0]["p95_ms"] == 900.0 and rep.rows()[0]["again_p95_ms"] == 10.0


def test_the_warm_up_is_not_counted() -> None:
    rep = ct.walk([_fake([5000.0] * 10 + [10.0] * 60)])
    assert not rep.failed() and len(rep.pages[0].times) == 60


def test_a_page_that_is_not_served_or_not_timed_fails() -> None:
    assert ct.walk([_fake([10.0] * 70, status=403)]).failed()

    def untimed(_: str) -> ct.Answer:
        return 200, {}

    rep = ct.walk([ct.Page("untimed", "/x", untimed)])
    assert rep.failed() and rep.rows()[0]["broken"] == "no Server-Timing header"


# ---------------------------------------------------------------------------------------------- the planted slow page
PLANTED_S = 0.31  # just over the budget: the walk's p95 must catch a page a few milliseconds over, not only a hang


@pytest.fixture
def planted(box: dict[str, Any]) -> ct.Page:
    """A page slower than the budget, added to this test's own app (never to the console's routes)."""

    async def slow() -> HTMLResponse:
        time.sleep(PLANTED_S)  # a page whose own work is slow: the event loop is held, as a slow render holds it
        return HTMLResponse("<p>planted</p>")

    box["app"].add_api_route("/_planted_slow_page", slow, methods=["GET"])
    box["app"].middleware_stack = None
    cs = clients(box)
    return ct.Page("planted", "/_planted_slow_page", getter(cs["coordinator"]))


def test_a_planted_slow_page_fails_the_walk_and_the_ten_pages_pass(box: dict[str, Any], planted: ct.Page,
                                                                   tmp_path: Any) -> None:  # fmt: skip
    pages = [*ten_pages(box), planted]
    rep = ct.walk(pages, warmup=1, repeat=3)  # the rule, not the statistics: few answers keep this test short
    assert [t.name for t in rep.failed()] == ["planted"], rep.markdown()
    slow = rep.pages[-1]
    assert slow.again is not None and min(slow.times + slow.again) >= ct.BUDGET_MS  # walked twice, slow both times
    assert len(rep.pages) == len(TEN) + 1
    rep.write(tmp_path)
    assert "| planted | `/_planted_slow_page` |" in (tmp_path / "console_timing.md").read_text()
    assert '"passed": false' in (tmp_path / "console_timing.json").read_text()
