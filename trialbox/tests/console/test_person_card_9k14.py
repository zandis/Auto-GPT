# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""9k-14 (D-1386): the person card. The weekly list and the cohort list show each person as one card (``article.pcard``)
and not as a table row. The invariant (D-1386): no page shows a patient field it did not show before.

The proof: ``data/person_card_9k14_before.json`` holds, for the two pages the card touches, each role of the role
matrix and two languages, every word and every address value (hrefs, ids, attributes) the page carried on origin/master
before the card, from the seeded synthetic study of the test box. The test renders the pages now and fails if a value
appears that the old page did not carry for that role, or if a role's answer (status code) changed. The baseline is
captured by this very test: ``TB_CAPTURE_9K14=<file> pytest tests/console/test_person_card_9k14.py`` run on the old
tree writes it. Synthetic data only."""

from __future__ import annotations

import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from console import phone
from tb_common import flags as fl

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box, login  # noqa: F401
from tests.console.test_role_route_matrix import _clients

RS = "GZQO"
PAGES = {"week": f"/studies/{RS}/week?list=all", "cohort": f"/studies/{RS}/cohort"}
LANGS = ("en", "ja")
BEFORE = Path(__file__).parent / "data" / "person_card_9k14_before.json"
CAPTURE = os.environ.get("TB_CAPTURE_9K14")
CSS = (Path(__file__).parents[2] / "services" / "console" / "static" / "console.css").read_text(encoding="utf-8")
TEMPLATES = Path(__file__).parents[2] / "services" / "console" / "templates"


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    fl.clear_cache()
    phone.clear_cache()
    yield
    fl.clear_cache()
    phone.clear_cache()


class _Values(HTMLParser):
    """Every word of the page's text and of its attributes (the csrf token apart: it is new on every render)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: set[str] = set()
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        d = {k: v or "" for k, v in attrs}
        if tag == "input" and d.get("name") in ("csrf", "login_csrf", "back_csrf"):
            return
        for k, v in d.items():
            if k in ("data-idle-left", "data-abs-left"):
                continue  # the session clock of the idle warning: it counts down on every render
            if k in ("class", "style", "id", "tabindex", "role", "data-testid", "data-label"):
                continue  # markup, not a value a person reads: the words of a test id are no patient field
            self.out.update(w for w in re.split(r"[\s&?=;]+", v) if w)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.out.update(re.split(r"[\s·]+", data.strip()) if data.strip() else [])


def values(page: str) -> list[str]:
    p = _Values()
    p.feed(page)
    # the render date and nothing else of "now": a page may print today's date
    return sorted(w for w in p.out if w)


def _snapshot(b: dict[str, Any]) -> dict[str, Any]:
    _done_feas(b["backend"])
    _done_screen(b["backend"], _ulid(990))
    out: dict[str, Any] = {}
    for col, (c, csrf, *_rest) in sorted(_clients(b).items()):
        for lang in LANGS:
            c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
            for name, url in PAGES.items():
                r = c.get(url, follow_redirects=False)
                out[f"{col}|{name}|{lang}"] = {
                    "status": r.status_code,
                    "values": values(r.text) if r.status_code == 200 else [],
                }
    return out


def test_capture_or_compare_no_page_shows_a_new_patient_field(box: dict[str, Any]) -> None:
    now = _snapshot(box)
    if CAPTURE:
        Path(CAPTURE).write_text(json.dumps(now, indent=0, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        pytest.skip("baseline written")
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    assert set(now) == set(before)
    assert any(v["status"] == 200 and v["values"] for v in before.values())
    for key, was in before.items():
        assert now[key]["status"] == was["status"], key  # the role gets the same answer
        new = set(now[key]["values"]) - set(was["values"])
        assert not new, (key, sorted(new))  # nothing a page did not carry before


def test_the_pages_the_card_touches_render_cards_with_every_testid_of_the_old_rows(box: dict[str, Any]) -> None:
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    cols = _clients(box)
    c, _csrf, *_ = cols["crc"]
    page = c.get(PAGES["week"]).text
    assert '<table class="worklist"' not in page and 'class="pcards"' in page
    assert page.count('<article class="pcard') >= 2
    for t in ("row-aaaaaaaa", "open-aaaaaaaa", "state-aaaaaaaa"):
        assert f'data-testid="{t}"' in page, t


def test_the_card_names_no_banned_class_and_has_one_stylesheet_block() -> None:
    classes = " ".join(re.findall(r'class="([^"]*)"', (TEMPLATES / "_pcard.html").read_text(encoding="utf-8")))
    assert "pcard" in classes and not re.search(r"(^|\s)pc-", classes)  # the badge guard bans the pc- family (D-1380)
    assert CSS.count("/* 9k-14 (D-1386): the person card") == 1
    assert "table.worklist" not in CSS
