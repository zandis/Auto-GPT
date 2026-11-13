# ruff: noqa: F811 - the fixtures are imported and taken by name
"""NEW-SITE-2 (D-709): the console's site pages while the hospital's lake cannot be asked.

The upload-then-raise sequence through the real pages and the real set-up routes: a sheet uploaded while the lake
is down is saved once and the page says it was read (before, the route answered 500 and a second try added a
second input); the readiness page, the patient check and the counts say the data could not be read, never "no
feed", "no patient" or a table of counts. Synthetic data only."""

from __future__ import annotations

import io
from typing import Any

import pytest
from console.i18n import CATALOGUES
from lake.client import LakeUnhealthy
from markupsafe import escape
from sitesetup import help as site_help
from tb_common.wording import check

from tests.console.test_console_app import box, login  # noqa: F401
from tests.console.test_site_setup_pages import PW, _form, sb  # noqa: F401
from tests.unit.test_site_setup_lake_down import Down

LANGS = ("en", "ja", "zh-TW")


@pytest.fixture
def down(sb: dict[str, Any]) -> dict[str, Any]:
    svc = sb["svc"]
    svc.main_lake = Down(svc.main_lake, LakeUnhealthy(503))
    return sb


def _upload(c: Any) -> Any:
    name, data = site_help.practice_inputs()["dump"]
    return _form(c, "/site/sheets", {"kind": "dump"}, files={"file": (name, io.BytesIO(data), "text/csv")})


def test_an_upload_while_the_lake_is_down_is_saved_once_and_the_page_says_it_was_read(down: dict[str, Any]) -> None:
    c, _ = login(down["app"], "crc", PW)
    r = _upload(c)
    assert r.status_code == 200 and 'data-testid="sheet-done"' in r.text, r.text[:300]
    assert len(down["svc"].store.inputs("main")) == 1
    assert down["svc"].store.published("main") is None  # saved; its publish waits for the lake
    # the lake answers again: the next tick publishes it, with no second upload
    down["svc"].main_lake = down["svc"].main_lake._lake
    down["svc"].flush("main")
    assert down["svc"].store.published("main") is not None and len(down["svc"].store.inputs("main")) == 1


@pytest.mark.parametrize("lang", LANGS)
def test_the_pages_say_the_data_could_not_be_read(down: dict[str, Any], lang: str) -> None:
    c, csrf = login(down["app"], "crc", PW)
    _upload(c)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
    cat = CATALOGUES[lang]
    page = c.get("/site?study=GZQO")
    assert page.status_code == 200
    assert 'data-testid="miss-lake_unread"' in page.text and str(escape(cat["site.miss.lake_unread"])) in page.text
    assert 'data-testid="q-patients" data-state="amber"' in page.text  # not known: not red ("none"), not green
    assert 'data-testid="site-feed"' not in page.text
    assert 'data-testid="feas-lake-unread"' in page.text and 'data-testid="feas-basis"' not in page.text
    pc = c.get("/site/patients?study=GZQO")
    assert pc.status_code == 200 and 'data-testid="pc-lake-unread"' in pc.text
    assert 'data-testid="pc-none"' not in pc.text and str(escape(cat["site.lake_unread"])) in pc.text
    for key in ("site.miss.lake_unread", "site.lake_unread"):
        assert not check(cat[key]), (lang, key)


def test_with_the_lake_up_the_pages_say_nothing_of_it(sb: dict[str, Any]) -> None:
    c, _ = login(sb["app"], "crc", PW)
    _upload(c)
    page = c.get("/site?study=GZQO").text
    assert "lake_unread" not in page and "feas-lake-unread" not in page
    assert "pc-lake-unread" not in c.get("/site/patients?study=GZQO").text
