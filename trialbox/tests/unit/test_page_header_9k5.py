"""9k-5 (D-1380; review 09 DS-5): the page header, and the rule it carries: one ``h1``, at most one primary act, the
title equal to the heading.

Read from the templates, no database (a guard). ``templates/_ds.html`` holds ``page_header``; a page that uses it sets
``page_title`` once and ``base.html`` puts the same string in ``<title>``. The rule is a ratchet, not yet a clean
sheet: ``page_header_baseline_9k5.json`` lists every page that today breaks it. A page may leave the list (a page
moves to the header one journey at a time, 9k-15) and none may join it; a page on the list that now keeps the rule
fails until it is removed. The counts are read from the template text, so a button under each branch of an
``{% if %}`` counts once per branch: a page can be listed that shows one act at a time, never the other way round.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jinja2
import pytest

pytestmark = [pytest.mark.guard, pytest.mark.nodb]

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parents[1] / "services" / "console" / "templates"
BASELINE = json.loads((HERE / "page_header_baseline_9k5.json").read_text(encoding="utf-8"))
NOT_PRIMARY = {"secondary", "quiet", "danger"}


def _source(path: Path) -> str:
    return re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)


def _pages() -> dict[str, str]:
    return {p.name: _source(p) for p in sorted(TEMPLATES.glob("*.html")) if 'extends "base.html"' in _source(p)}


def headings(text: str) -> int:
    return len(re.findall(r"<h1\b", text)) + len(re.findall(r"\bpage_header\(", text))


def primaries(text: str) -> int:
    n = 0
    for m in re.finditer(r"""<button\b[^>]*>|<a\b[^>]*\bclass="[^"]*\bbutton\b[^"]*"[^>]*>""", text):
        tag = m.group(0)
        cls = re.search(r'class="([^"]*)"', tag)
        if NOT_PRIMARY & set(cls.group(1).split() if cls else ()):
            continue
        if tag.startswith("<button") and 'type="hidden"' in tag:
            continue
        n += 1
    return n


def name_differs(text: str) -> bool:
    """True when the page names itself twice and the two differ (a page using the header names itself once)."""
    if "page_header(page_title" in text:
        return "{% block title %}" in text
    t = re.search(r"\{% block title %\}(.*?)\{% endblock %\}", text, flags=re.S)
    h = re.findall(r"<h1[^>]*>(.*?)</h1>", text, flags=re.S)
    return not t or len(h) != 1 or t.group(1).strip() != h[0].strip()


RULES = {
    "one_h1": lambda text: headings(text) != 1,
    "one_primary": lambda text: primaries(text) > 1,
    "title_is_heading": name_differs,
}


@pytest.mark.parametrize("rule", sorted(RULES))
def test_no_page_joins_the_list_and_none_stays_on_it_by_mistake(rule: str) -> None:
    broken = {name for name, text in _pages().items() if RULES[rule](text)}
    listed = set(BASELINE[rule])
    assert not broken - listed, f"{rule}: new pages break the rule: {sorted(broken - listed)}"
    assert not listed - broken, (
        f"{rule}: pages that keep it now, remove them from the baseline: {sorted(listed - broken)}"
    )


def test_a_page_that_uses_the_header_names_itself_once() -> None:
    users = {n: t for n, t in _pages().items() if "page_header(" in t}
    assert {"about.html", "cmd.html", "notices_received.html"} <= set(users)
    for name, text in users.items():
        assert "{% set page_title = " in text and "page_header(page_title" in text, name
        assert "<h1" not in text and "{% block title %}" not in text, name
        assert primaries(text) <= 1, name


def test_base_puts_the_page_title_in_title() -> None:
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "{% block title %}{{ page_title if page_title is defined else t('brand') }}{% endblock %}" in base


def test_the_header_macro_and_the_title_it_shares_with_the_page() -> None:
    """The mechanism on a small base of the same shape: the macro's markup with and without an act, and a title
    set once at the top of a page reaching both ``<title>`` and the heading."""
    ds = (TEMPLATES / "_ds.html").read_text(encoding="utf-8")
    base = "<title>{% block title %}{{ page_title if page_title is defined else 'brand' }}{% endblock %}</title>{% block content %}{% endblock %}"
    page = (
        '{% extends "base.html" %}{% from "_ds.html" import page_header %}{% set page_title = "Participants" %}'
        '{% block content %}{{ page_header(page_title, "Study GZQO") }}'
        "{% call page_header(page_title) %}<button>Add</button>{% endcall %}{% endblock %}"
    )
    env = jinja2.Environment(
        loader=jinja2.DictLoader({"base.html": base, "_ds.html": ds, "page.html": page}), autoescape=True
    )
    out = env.get_template("page.html").render()
    assert "<title>Participants</title>" in out
    assert '<header class="ph"><p class="ph-ctx">Study GZQO</p><h1>Participants</h1></header>' in out
    assert '<h1>Participants</h1><div class="ph-act"><button>Add</button></div></header>' in out
    assert env.from_string('{% from "_ds.html" import page_header %}{{ page_header("T") }}').render() == (
        '<header class="ph"><h1>T</h1></header>'
    )


def test_the_baseline_names_only_real_pages() -> None:
    pages = set(_pages())
    for rule, names in BASELINE.items():
        assert names == sorted(names) and set(names) <= pages, rule
