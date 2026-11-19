# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""J-7 (D-1251; the journey review's R17, R18 and R22, section D): a pruned "More", one name per page, and no job word
or variable name on a clinical page, behind the flag ``layout.plain_menu``.

* the flag is declared, off by default, described in three languages, read with the other layout flags in one read;
* one name per page: for every menu entry of every role, on the opening page and on a study page, in en, ja and
  zh-TW, the menu's label, the page's title and its main heading are the same words (the study code and other data
  segments set aside).

Synthetic data only (the test box's study GZQO)."""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from typing import Any

import pytest
from console import phone
from tb_common import flags as fl

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box  # noqa: F401
from tests.console.test_role_route_matrix import COLUMNS, _clients

FLAG = "layout.plain_menu"
LANGS = ("en", "ja", "zh-TW")
RS = "GZQO"
#: the pages each role's menu is read on: the opening page and a study page
MENU_PAGES = ("/home", f"/studies/{RS}/week")


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    fl.clear_cache()
    phone.clear_cache()
    yield
    fl.clear_cache()
    phone.clear_cache()


def _flag(b: dict[str, Any], value: str) -> None:
    """The administrator's change on /ops/flags: audited, with a reason."""
    fl.Flags(audit=b["audit"]).set(FLAG, value, actor="console:admin", reason="J-7 test (D-1251)")
    fl.clear_cache()
    phone.clear_cache()
    phone.read_now()  # read now: a page gets the value last read


def _lang(c: Any, csrf: str, lang: str) -> None:
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def menu(page: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(top bar, under "More") of a page's menu: (href, label) of each entry."""
    m = re.search(r'<nav aria-label="main".*?</nav>', page, re.S)
    assert m, page[:2000]
    nav = m.group(0)
    more = re.search(r'<details class="more".*?</details>\s*(?=</nav>|\Z)', nav, re.S)
    more_html = more.group(0) if more else ""
    top_html = nav.replace(more_html, "") if more_html else nav
    link = re.compile(r'<a href="([^"]*)"[^>]*>(.*?)</a>', re.S)
    top = [(html.unescape(h), _text(t)) for h, t in link.findall(top_html)]
    under = [(html.unescape(h), _text(t)) for h, t in link.findall(more_html)]
    return top, under


def _name_parts(text: str) -> list[str]:
    return [p.strip() for p in text.split(" · ") if p.strip()]


# ------------------------------------------------------------------------------------------- the flag
def test_the_flag_is_declared_off_and_described_in_three_languages(box: dict[str, Any]) -> None:
    from console import i18n_flags

    d = fl.DECLARED[FLAG]
    assert d.default == "off" and d.values == ("off", "on") and d.seed_env is None
    assert fl.Flags().row(FLAG) == "off" and not phone.read_now()[FLAG]  # seeded off at create_app
    for cat in (i18n_flags.EN, i18n_flags.JA, i18n_flags.ZH):
        assert cat[f"flags.desc.{FLAG}"]


def test_the_layout_flags_are_read_together_in_one_read(box: dict[str, Any], monkeypatch: Any) -> None:
    """This flag is read with ``layout.phone_first`` and ``layout.home_today`` in the console's one background read
    (one statement); a page takes its value from the request."""
    reads: list[tuple[str, ...]] = []
    real = fl.Flags.rows

    def rows(self: Any, names: Any) -> dict[str, str]:
        reads.append(tuple(names))
        return real(self, names)

    monkeypatch.setattr(fl.Flags, "rows", rows)
    fl.Flags(audit=box["audit"]).set(FLAG, "on", actor="console:admin", reason="J-7 test (D-1251)")
    got = phone.read_now()
    assert got[FLAG] is True and got[phone.FLAG] is False and got[phone.HOME_FLAG] is False
    assert len(reads) == 1 and set(reads[0]) == {phone.FLAG, phone.HOME_FLAG, FLAG}


# ------------------------------------------------------------------------------------------- one name per page (R18)
def test_every_menu_entry_has_one_name_its_label_title_and_heading_in_three_languages(box: dict[str, Any]) -> None:
    """For every role, every entry of its menu (top bar and "More") on the opening page and on a study page, in each
    language: the page the entry opens has the entry's label as its title's first part and as one part of its main
    heading (the parts are joined by " · "; the others are data: the study code, a year, the site's name). A page
    that refuses the account (403) is not that account's page and is left out."""
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    _flag(box, "on")
    differ: list[str] = []
    for col in COLUMNS:
        page, csrf, _ = clients[col]
        for lang in LANGS:
            _lang(page, csrf, lang)
            entries: dict[str, str] = {}
            for p in MENU_PAGES:
                top, under = menu(page.get(p).text)
                for href, label in top + under:
                    if href.startswith("/help"):  # the help page names the page it was opened from (R20)
                        continue
                    entries.setdefault(href, label)
            for href, label in sorted(entries.items()):
                name = label.split(" · ", 1)[1] if label.startswith(f"{RS} · ") else label
                r = page.get(href)
                if r.status_code == 403:
                    continue
                assert r.status_code == 200, (col, lang, href, r.status_code)
                title = re.search(r"<title>(.*?)</title>", r.text, re.S)
                h1 = re.search(r"<h1[^>]*>(.*?)</h1>", r.text, re.S)
                t_parts = _name_parts(_text(title.group(1))) if title else []
                h_parts = _name_parts(_text(h1.group(1))) if h1 else []
                if not t_parts or t_parts[0] != name or name not in h_parts:
                    differ.append(f"{col} [{lang}] {href}: menu {name!r} · title {t_parts} · heading {h_parts}")
        _lang(page, csrf, "en")
    assert not differ, "a page's menu label, title and heading differ:\n" + "\n".join(differ)
