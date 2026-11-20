# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""10B-23 (D-1254): the data-operations page says when the box's last full night was.

The adapter keeps the lake's record (``adapter.full_nights``) in each night's event; the ``/data-ops`` page shows it
in its counts area: "Last full night: <date> (N days ago), M nightly updates since", in the page's warning style with
one sentence on what a full night corrects when it is older than ``FULL_NIGHT_STALE_DAYS`` and delta nights ran
since, or not known and delta nights ran. The line is shown to exactly the accounts that read the page (the matrix's
``dataops.view``); with no record and no delta night the sources section is the page's without this card, byte for byte
(both rendered in the test, from the current templates; D-1380). Synthetic data only."""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from console import dataops_page
from console.i18n import translate
from datacore.dataops import DataOps
from tb_common.audit import AuditLog
from tb_common.authz import MATRIX_ROLES, permit
from tb_common.config import site_tz
from tb_common.wording import check

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import PW, _user

AT = "2026-11-11T02:00:00+09:00"
LANGS = ("en", "ja", "zh-TW")
NO_RECORD = object()


def _today() -> date:
    return datetime.now(ZoneInfo(site_tz())).date()


def _night(b: dict[str, Any], record: Any = NO_RECORD, *, snap: str = "2026-11-10", event: str = "ingest.done") -> int:
    ops = DataOps()
    try:
        detail: dict[str, Any] = {"counts": {"Observation": 10}}
        if record is not NO_RECORD:
            detail["full_night"] = record
        passed, held = event == "ingest.done", event == "ingest.held"
        batch, _ = ops.record_night(AuditLog(Path(b["dir"]) / "audit", "UTC"), event, source="csv", snapshot=snap,
                                    passed=passed, held=held, by="adapter", at=AT, actor="adapter",
                                    detail=detail)  # fmt: skip
        return batch.id
    finally:
        ops.close()


def _days_ago(n: int) -> str:
    return (_today() - timedelta(days=n)).isoformat()


def _steward(b: dict[str, Any]) -> Any:
    _user(b, "stwf", "steward")
    return login(b["app"], "stwf", PW)


def _sources(page: str) -> str:
    m = re.search(r'<section class="card" data-testid="dataops-sources">(.*?)</section>', page, re.S)
    assert m, "no sources section"
    return m.group(1)


def _line(page: str) -> re.Match[str] | None:
    return re.search(r'<p class="(\w+)" data-testid="dataops-full-night"( data-warn="1")?>(.*?)</p>', page, re.S)


@pytest.fixture(autouse=True)
def _orch(box: dict[str, Any]) -> None:
    from tests.console.dataops_orch import attach

    attach(box["backend"], box["audit"])


@pytest.mark.parametrize("lang", LANGS)
def test_the_page_says_the_last_full_night_and_the_updates_since(box: dict[str, Any], lang: str) -> None:
    _night(box, {"last_full": _days_ago(3), "deltas": 2})
    c, csrf = _steward(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    page = c.get("/data-ops").text
    got = _line(_sources(page))
    assert got and got.group(1) == "hint" and not got.group(2)
    want = translate(lang, "dataops.full_night.known", date=_days_ago(3),
                     ago=translate(lang, "dataops.full_night.days", n="3"),
                     updates=translate(lang, "dataops.full_night.updates", n="2"))  # fmt: skip
    assert html.unescape(got.group(3)) == want
    assert translate(lang, "dataops.full_night.why") not in page
    if lang == "en":
        assert want == f"Last full night: {_days_ago(3)} (3 days ago), 2 nightly updates since."
        assert not check(got.group(3))


@pytest.mark.parametrize(("days", "warn"), [(7, False), (8, True)])
@pytest.mark.parametrize("lang", LANGS)
def test_the_seven_day_boundary_both_sides(box: dict[str, Any], lang: str, days: int, warn: bool) -> None:
    _night(box, {"last_full": _days_ago(days), "deltas": 1})
    c, csrf = _steward(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    got = _line(_sources(c.get("/data-ops").text))
    assert got
    assert (got.group(1) == "warn") is warn and bool(got.group(2)) is warn
    assert (translate(lang, "dataops.full_night.why") in html.unescape(got.group(3))) is warn
    assert translate(lang, "dataops.full_night.update") in html.unescape(got.group(3))


def test_an_old_full_night_with_no_update_since_is_no_warning(box: dict[str, Any]) -> None:
    """Nothing a full night corrects can have been missed when no delta night ran after it."""
    _night(box, {"last_full": _days_ago(30), "deltas": 0})
    c, _ = _steward(box)
    got = _line(c.get("/data-ops").text)
    assert got and got.group(1) == "hint" and "0 nightly updates since" in got.group(3)


@pytest.mark.parametrize("lang", LANGS)
def test_not_known_with_updates_is_said_as_not_known_and_warned(box: dict[str, Any], lang: str) -> None:
    _night(box, {"last_full": None, "deltas": 4})
    c, csrf = _steward(box)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    got = _line(c.get("/data-ops").text)
    assert got and got.group(1) == "warn"
    text = html.unescape(got.group(3))
    unknown = translate(lang, "dataops.full_night.unknown", updates=translate(lang, "dataops.full_night.updates",
                                                                               n="4"))  # fmt: skip
    assert text == f"{unknown} {translate(lang, 'dataops.full_night.why')}"
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)  # never a guessed date


def test_the_newest_night_that_carries_the_record_is_the_one_said(box: dict[str, Any]) -> None:
    """A night that failed carries the record as it stood (it moved nothing); a row with no record (a night still
    running, a refused one) does not hide the record of the night before."""
    _night(box, {"last_full": _days_ago(10), "deltas": 1}, snap="2026-11-08")
    _night(box, {"last_full": _days_ago(2), "deltas": 0}, snap="2026-11-09")
    _night(box, snap="2026-11-10", event="ingest.failed")
    c, _ = _steward(box)
    got = _line(c.get("/data-ops").text)
    assert got and got.group(1) == "hint" and _days_ago(2) in got.group(3)


@pytest.mark.parametrize(
    "bad", ["x", {"last_full": "2026-13-01", "deltas": 1}, {"last_full": None, "deltas": -1},
            {"last_full": None, "deltas": True}, {"last_full": 20261101, "deltas": 1}, {"deltas": "2"}],
)  # fmt: skip
def test_a_record_of_another_shape_is_not_shown_and_breaks_no_page(box: dict[str, Any], bad: Any) -> None:
    row = dataops_page.NightRow(1, "csv", "2026-11-10", 1, "PUBLISHED", 1, AT, AT, "adapter", {"full_night": bad})
    assert dataops_page.full_night_of([row], _today()) is None
    _night(box, bad)
    c, _ = _steward(box)
    r = c.get("/data-ops")
    assert r.status_code == 200 and 'data-testid="dataops-full-night"' not in r.text


@pytest.mark.parametrize("role", MATRIX_ROLES)
def test_the_line_is_shown_to_exactly_the_accounts_that_read_the_page(box: dict[str, Any], role: str) -> None:
    """The role walk of the page's tests (``test_dataops_page``: the steward and the administrator read, every
    other role gets 403), over every role of the matrix, for the page and its API twin."""
    from fastapi.testclient import TestClient

    _night(box, {"last_full": _days_ago(9), "deltas": 3})
    c = _user(box, f"fn_{role}", role)
    r = c.get("/data-ops")
    tok = TestClient(box["app"]).post("/api/v1/session", json={"username": f"fn_{role}", "password": PW})
    api = TestClient(box["app"]).get("/api/v1/data/sources",
                                     headers={"Authorization": f"Bearer {tok.json().get('token', '')}"})  # fmt: skip
    if permit(role, dataops_page.VIEW):
        assert r.status_code == 200 and 'data-testid="dataops-full-night"' in r.text
        assert api.status_code == 200
    else:
        assert r.status_code == 403 and "dataops-full-night" not in r.text and "nightly update" not in r.text
        assert api.status_code in (401, 403) and "full_night" not in api.text
    assert {r for r in MATRIX_ROLES if permit(r, dataops_page.VIEW)} == {"admin", "steward"}  # the page's own walk


@pytest.mark.parametrize("record", [NO_RECORD, {"last_full": None, "deltas": 0}], ids=["none", "not-known-no-delta"])
def test_no_record_and_no_delta_night_is_the_page_without_this_card(box: dict[str, Any], record: Any,
                                                                    monkeypatch: Any) -> None:  # fmt: skip
    """Every 10B-23 part of ``dataops.html`` sits between ``{#FN#}`` and ``{#/FN#}``. With no record and no delta
    night the sources section is the same, byte for byte, as the one from the template with those parts taken out
    (the page as it was before this card), in three languages. Both sides are rendered here, from the current
    templates (the card's own pill included), and nothing is stripped. (Until D-1380 the other side was a stored
    copy of master's markup, ``dataops_sources_master.json``, which a change of the pill markup broke.)"""
    import jinja2

    form = ["with"]
    real = jinja2.FileSystemLoader.get_source

    def source(self: Any, env: Any, name: str) -> Any:
        text, path, _uptodate = real(self, env, name)
        if name == "dataops.html" and form[0] == "without":
            text = re.sub(r"\{#FN#\}.*?\{#/FN#\}", "", text, flags=re.S)
        return text, path, lambda: False  # never kept: each render reads the form asked for

    monkeypatch.setattr(jinja2.FileSystemLoader, "get_source", source)  # before any page is rendered
    _night(box, record)
    c, csrf = _steward(box)
    pages: dict[str, list[str]] = {"with": [], "without": []}
    for f in ("with", "without"):
        form[0] = f
        for lang in LANGS:
            c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
            pages[f].append(_sources(c.get("/data-ops").text))
    assert "data-testid=\"dataops-full-night\"" not in "".join(pages["with"])
    assert "data-light=\"green\"" in pages["with"][0]  # a section with a source in it, not an empty one
    for lang, a, b in zip(LANGS, pages["with"], pages["without"], strict=True):
        assert a == b, lang


def test_the_seven_is_a_named_constant() -> None:
    assert dataops_page.FULL_NIGHT_STALE_DAYS == 7
    rows = [dataops_page.NightRow(1, "csv", "2026-11-10", 1, "PUBLISHED", 1, AT, AT, "adapter",
                                  {"full_night": {"last_full": "2026-11-01", "deltas": 1}})]  # fmt: skip
    assert dataops_page.full_night_of(rows, date(2026, 11, 8))["warn"] is False  # type: ignore[index]
    assert dataops_page.full_night_of(rows, date(2026, 11, 9))["warn"] is True  # type: ignore[index]
