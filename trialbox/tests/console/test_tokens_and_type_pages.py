# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""9k-1 and 9k-2 (D-1368): the pages carry what the style sheet's language rules key on.

The CJK rules of ``console.css`` (line height, ``line-break: strict``, the font stack) apply by ``:lang()``: a page
in Japanese or Traditional Chinese must say so on ``<html>``. The page names no colour itself: ``theme-color`` is
``console.phone.THEME``, the light ``--banner`` token (tests/unit/test_console_tokens_and_type.py). The style sheet
the box serves is the one with the tokens.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from console import phone
from fastapi.testclient import TestClient

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401

PW = "tokens-and-type-password-0001"


@pytest.mark.parametrize("lang", ["ja", "zh-TW", "en"])
def test_a_signed_in_page_has_its_language_and_no_colour_of_its_own(box: dict[str, Any], lang: str) -> None:
    _done_screen(box["backend"], _ulid(962))
    box["users"].create("drsato", "investigator", PW, "drsato@hospa.test")
    name_pi(box, "drsato")
    c, csrf = login(box["app"], "drsato", PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    for path in ("/", "/studies/GZQO/week", "/account"):
        page = c.get(path).text
        assert re.search(rf'<html lang="{re.escape(lang)}">', page), path
        assert f'<meta name="theme-color" content="{phone.THEME}">' in page, path
        assert '<link rel="stylesheet" href="/static/console.css' in page, path


@pytest.mark.parametrize(("accept", "lang"), [("ja", "ja"), ("zh-TW", "zh-TW"), ("en", "en")])
def test_the_sign_in_page_takes_the_browser_language(box: dict[str, Any], accept: str, lang: str) -> None:
    page = TestClient(box["app"]).get("/login", headers={"Accept-Language": accept}).text
    assert f'<html lang="{lang}">' in page
    assert f'<meta name="theme-color" content="{phone.THEME}">' in page


def test_the_box_serves_the_style_sheet_with_the_tokens(box: dict[str, Any]) -> None:
    css = TestClient(box["app"]).get("/static/console.css").text
    for token in ("--control:", "--warn-bg:", "--t-body:", "--lh-cjk:"):
        assert token in css, token
    assert "body:lang(ja), body:lang(zh-TW) { line-break: strict; line-height: var(--lh-cjk);" in css
