# ruff: noqa: F811 - the fixtures are imported from other test files and taken by name
"""9k-14 (D-1386): the person card. The weekly list and the cohort list show each person as one card
(``article.pcard``) and not as a table row. The invariant (D-1386): no page shows a patient field it did not show
before, and none of its links, forms or buttons is lost.

The proof is made per person. ``tests/fixtures/console_9k14/person_card_9k14_before_*.json.gz`` (a data file type may
live only under tests/fixtures) hold what the two pages carried on
origin/master before the card, from the seeded synthetic study of the test boxes, for each role of the role matrix,
three languages, the phone-first flag off and on, a selected row, and a study with an Approach mark (the quick
outcomes). For each person (the container of ``row-<id>`` or ``member-<id>``) and for the rest of the page it holds
every visible text (not the content of ``script`` and ``style``: markup, not values), every link, every form (method and action), every button (name, value, text), every hidden input
(csrf masked) and every attribute value, ``id`` and ``data-label`` among them. The test renders the pages now and fails
if a person's card gained a text, an attribute value, a link, a form, a button or a hidden input, or lost a text, a
link, a form, a button or an input; the only words a card may add are the column names (it now writes them out), and
the only attribute values it may lose are ``data-label`` (now the text of the label) and the scroll box's
``tabindex``. A page a role was refused is refused the same way, word for word.

The baseline is captured by this very file on the old tree: ``TB_CAPTURE_9K14=<dir> pytest
tests/console/test_person_card_9k14.py`` run in a copy of origin/master (``git archive``) writes both files; the
session clock of the idle warning (``data-idle-left``, ``data-abs-left``) and the csrf values are masked at capture.
Synthetic data only."""

from __future__ import annotations

import gzip
import importlib
import itertools
import json
import os
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import lxml.html  # type: ignore[import-untyped]
import pytest
from console import phone
from console.i18n import CATALOGUES
from tb_common import flags as fl

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box  # noqa: F401
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name
from tests.console.test_one_person_state import A, B, _mark, _seq
from tests.console.test_role_route_matrix import _clients

RS = "GZQO"
LANGS = ("en", "ja", "zh-TW")
DATA = Path(__file__).parents[1] / "fixtures" / "console_9k14"
CAPTURE = os.environ.get("TB_CAPTURE_9K14")
ROOT = Path(__file__).parents[2]
CSS = (ROOT / "services" / "console" / "static" / "console.css").read_text(encoding="utf-8")
TEMPLATES = ROOT / "services" / "console" / "templates"
PERSON = re.compile(r"^(row|member)-[0-9a-f]{8}$")
#: what changes on every render and says nothing about a person: the idle warning's session clock
CLOCK = ("data-idle-left", "data-abs-left")
#: a date input's lower bound is the day of the render (the recheck date): masked here and in the baselines
TODAY = "<today>"
DATED_MIN = re.compile(r"^min=\d{4}-\d{2}-\d{2}$")
#: attributes that are markup and not values (the styling hook, the inline style)
MARKUP = ("class", "style")
#: elements whose content is markup and not a value a person sees (an inline script, a stylesheet)
UNSEEN = ("script", "style")
#: attribute values a card may lose: the label is now a text, the box that scrolled sideways no longer scrolls
MAY_LOSE = ("data-label", "tabindex")
LABEL_KEYS = ("wb.c.visit", "wb.c.patient", "wb.c.met", "wb.c.needed", "wb.c.status", "cohort.c.dept", "patient.visit")
REST = "(rest of the page)"
Rendered = dict[str, tuple[int, str]]


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    fl.clear_cache()
    phone.clear_cache()
    yield
    fl.clear_cache()
    phone.clear_cache()


def _texts(el: Any) -> Iterator[str]:
    """The text a person sees, as ``itertext`` gives it, without the content of ``script`` and ``style`` (markup, not
    values: a page's inline script text is no patient field); their attributes and the text after them still count."""
    if isinstance(el.tag, str) and el.tag in UNSEEN:
        return
    if isinstance(el.tag, str) and el.text:
        yield el.text
    for child in el:
        yield from _texts(child)
        if child.tail:
            yield child.tail


def _facts(el: Any) -> dict[str, list[str]]:
    f: dict[str, Counter[str]] = {k: Counter() for k in ("text", "href", "form", "button", "hidden", "attr")}
    for t in _texts(el):
        f["text"].update(w for w in re.split(r"\s+", t) if w and w != "·")
    for e in el.iter():
        if not isinstance(e.tag, str):
            continue
        csrf = e.tag == "input" and e.get("name") in ("csrf", "login_csrf")
        for k, v in e.attrib.items():
            if k in MARKUP:
                continue
            if csrf and k == "value":
                v = "<csrf>"
            if k in CLOCK:
                v = "<clock>"
            if k == "min" and e.tag == "input" and e.get("type") == "date":
                v = TODAY  # the recheck date's lower bound is the day of the render
            f["attr"][f"{k}={v}"] += 1
        if e.tag == "a" and "href" in e.attrib:
            f["href"][e.attrib["href"]] += 1
        if e.tag == "form":
            f["form"][f"{e.get('method', 'get')} {e.get('action', '')}"] += 1
        if e.tag == "button":
            f["button"][f"{e.get('name')}={e.get('value')} [{(e.text_content() or '').strip()}]"] += 1
        if e.tag == "input" and e.get("type") == "hidden":
            f["hidden"][f"{e.get('name')}={'<csrf>' if csrf else e.get('value', '')}"] += 1
    return {k: sorted(c.elements()) for k, c in f.items()}


def facts(page: str) -> dict[str, Any]:
    """The facts of each person's container and of the rest of the page."""
    doc = lxml.html.fromstring(page)
    people = {}
    for e in doc.iter():
        if isinstance(e.tag, str) and PERSON.match(e.get("data-testid", "")):
            people[e.get("data-testid")] = _facts(e)
    for e in list(doc.iter()):
        if isinstance(e.tag, str) and PERSON.match(e.get("data-testid", "")):
            e.drop_tree()
    return {"people": people, "rest": _facts(doc)}


def _labels(lang: str) -> set[str]:
    return {w for k in LABEL_KEYS for w in CATALOGUES[lang][k].split()}


def problems(was: dict[str, Any], now: dict[str, Any], lang: str) -> list[str]:
    """Everything the page now carries that it did not, and everything it lost (see the module's text)."""
    out: list[str] = []
    labels = _labels(lang)
    if set(was["people"]) != set(now["people"]):
        out.append(f"people: {sorted(set(was['people']) ^ set(now['people']))}")
    pairs = [(tid, was["people"][tid], now["people"][tid]) for tid in sorted(set(was["people"]) & set(now["people"]))]
    pairs.append((REST, was["rest"], now["rest"]))
    for tid, a, b in pairs:
        for kind in ("href", "form", "button", "hidden"):
            if a[kind] != b[kind]:
                out.append(f"{tid} {kind}: was {a[kind]}, now {b[kind]}")
        out += [f"{tid} new text {w!r}" for w in Counter(b["text"]) - Counter(a["text"]) if w not in labels]
        lost = set(a["text"]) - set(b["text"])
        out += [f"{tid} lost text {w!r}" for w in lost if tid != REST or w not in labels]
        out += [f"{tid} new attribute {v!r}" for v in set(b["attr"]) - set(a["attr"])]
        out += [
            f"{tid} lost attribute {v!r}" for v in set(a["attr"]) - set(b["attr"]) if v.split("=", 1)[0] not in MAY_LOSE
        ]
    return out


def _flag(b: dict[str, Any], value: str) -> None:
    fl.Flags(audit=b["audit"]).set(phone.FLAG, value, actor="console:admin", reason="9k-14 test")
    fl.clear_cache()
    phone.clear_cache()
    phone.flag_on()


def _pages(pid: str) -> dict[str, str]:
    return {
        "week": f"/studies/{RS}/week?list=all",
        "weeksel": f"/studies/{RS}/week?list=all&pid={pid}",
        "cohort": f"/studies/{RS}/cohort",
    }


def _render_matrix(b: dict[str, Any]) -> Rendered:
    _done_feas(b["backend"])
    _done_screen(b["backend"], _ulid(990))
    cols = _clients(b)
    out: Rendered = {}
    for flag in ("off", "on"):
        if flag == "on":
            _flag(b, "on")
        for col, (c, csrf, *_rest) in sorted(cols.items()):
            for lang in LANGS:
                c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
                for name, url in _pages(B).items():
                    r = c.get(url, follow_redirects=False)
                    out[f"{flag}|{col}|{name}|{lang}"] = (r.status_code, r.text)
    return out


def _render_marked(b: dict[str, Any]) -> Rendered:
    pi, pcsrf, crc, csrf = _seq(b)
    _mark(b, pi, pcsrf, "approach")  # an Approach mark in force: the quick outcomes are on the card
    out: Rendered = {}
    for flag in ("off", "on"):
        if flag == "on":
            _flag(b, "on")
        for who, c, k in (("pi", pi, pcsrf), ("crc", crc, csrf)):
            for lang in LANGS:
                c.post("/lang", data={"csrf": k, "lang": lang, "back": "/"})
                pages = {**_pages(A), "approached": f"/studies/{RS}/week?list=approached"}
                for name, url in pages.items():
                    r = c.get(url, follow_redirects=False)
                    out[f"{flag}|{who}|{name}|{lang}"] = (r.status_code, r.text)
    return out


def _snapshot(rendered: Rendered) -> dict[str, Any]:
    return {k: {"status": s, **facts(p)} for k, (s, p) in rendered.items() if p} | {
        k: {"status": s, "people": {}, "rest": {}} for k, (s, p) in rendered.items() if not p
    }


def _baseline(scn: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(gzip.decompress((DATA / f"person_card_9k14_before_{scn}.json.gz").read_bytes()))
    masked: dict[str, Any] = _mask_dated_min(data)
    return masked


def _mask_dated_min(x: Any) -> Any:
    """The baselines were captured with the capture day's date in the recheck input's ``min``: mask it as _facts does."""
    if isinstance(x, dict):
        return {k: _mask_dated_min(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_mask_dated_min(v) for v in x]
    if isinstance(x, str) and DATED_MIN.match(x):
        return f"min={TODAY}"
    return x


def _check(scn: str, rendered: Rendered) -> None:
    now = _snapshot(rendered)
    if CAPTURE:
        Path(CAPTURE).mkdir(parents=True, exist_ok=True)
        data = json.dumps(now, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        (Path(CAPTURE) / f"person_card_9k14_before_{scn}.json.gz").write_bytes(gzip.compress(data, mtime=0))
        pytest.skip("baseline written")
    before = _baseline(scn)
    assert set(now) == set(before)
    assert any(v["status"] == 200 and v["people"] for v in before.values())
    refused = 0
    for key, was in before.items():
        assert now[key]["status"] == was["status"], key  # the role gets the same answer
        if was["status"] != 200:
            refused += 1
            assert now[key]["rest"] == was["rest"], key  # a refusal is the same refusal
            continue
        got = problems(was, now[key], key.rsplit("|", 1)[1])
        assert not got, (key, got[:12])
    assert refused >= 6 or scn == "marked"


def test_matrix_no_card_gains_or_loses_a_field_a_link_a_form_or_a_button(box: dict[str, Any]) -> None:
    _check("matrix", _render_matrix(box))


def test_marked_study_the_quick_outcomes_and_the_selected_row_are_the_same(lb: dict[str, Any]) -> None:
    _check("marked", _render_marked(lb))


def test_the_proof_goes_red_on_the_mutations_a_review_tried(box: dict[str, Any]) -> None:
    """The comparison is not vacuous: a patient link without its address, a patient id in ``data-label`` or ``id`` and
    a visible patient id each make it fail (the first form of this test, one bag of words for the whole page, passed
    the first two)."""
    if CAPTURE:
        pytest.skip("capturing")
    key = "off|crc|week|en"
    page = _render_matrix(box)[key][1]
    was = _baseline("matrix")[key]
    assert problems(was, facts(page), "en") == []
    no_href = page.replace('class="rowlink" href="', 'class="rowlink" data-x="', 1)
    assert no_href != page and any("href" in p for p in problems(was, facts(no_href), "en"))
    tid = f'data-testid="row-{A[:8]}"'
    in_label = page.replace(tid, f'{tid} data-label="{A}"', 1)
    assert in_label != page and any("new attribute" in p for p in problems(was, facts(in_label), "en"))
    in_id = page.replace(tid, f'{tid} aria-describedby="x-{A}"', 1)
    assert in_id != page and any("new attribute" in p for p in problems(was, facts(in_id), "en"))
    visible = page.replace('<h3 class="pcard-name">', f'<h3 class="pcard-name"><i>{A}</i>', 1)
    assert visible != page and any("new text" in p for p in problems(was, facts(visible), "en"))


def test_every_value_of_a_card_has_its_columns_name_and_the_cohort_has_no_skipped_heading(box: dict[str, Any]) -> None:
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    c, csrf, *_ = _clients(box)["crc"]
    wants = {
        "week": {"met": "wb.c.met", "meta": "wb.c.visit", "state": "wb.c.status", "why": "wb.c.needed"},
        "cohort": {"met": "wb.c.met", "meta": "patient.visit", "why": "cohort.c.dept"},
    }
    for lang in LANGS:
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        for name, url in (("week", f"/studies/{RS}/week?list=all"), ("cohort", f"/studies/{RS}/cohort")):
            doc = lxml.html.fromstring(c.get(url).text)
            cards = doc.xpath('//article[contains(@class, "pcard")]')
            assert len(cards) >= (2 if name == "week" else 1), (lang, name)
            for card in cards:
                for part, key in wants[name].items():
                    els = card.xpath(f'.//*[contains(concat(" ", @class, " "), " pcard-{part} ")]')
                    assert len(els) == 1, (lang, name, part)
                    lab = els[0].xpath('./span[@class="pcard-lab"]')
                    assert lab and lab[0].text_content().strip() == CATALOGUES[lang][key].strip(), (lang, name, part)
                    assert len(els[0].text_content().strip()) > len(lab[0].text_content().strip()), (lang, name, part)
            levels = [int(h.tag[1]) for h in doc.xpath("//h1|//h2|//h3|//h4")]
            if name == "cohort":  # the week page's rail has its own h3 before its h2 (not a card's)
                assert all(b - a <= 1 for a, b in itertools.pairwise(levels)), (lang, name, levels)


def test_the_card_names_no_banned_class_and_has_one_stylesheet_block() -> None:
    classes = " ".join(re.findall(r'class="([^"]*)"', (TEMPLATES / "_pcard.html").read_text(encoding="utf-8")))
    assert "pcard" in classes and not re.search(r"(^|\s)pc-", classes)  # the badge guard bans the pc- family (D-1380)
    assert CSS.count("/* 9k-14 (D-1386): the person card") == 1
    assert "table.worklist" not in CSS


def test_the_flag_text_says_what_off_and_on_now_do() -> None:
    """The phone-first flag no longer decides whether the lists are cards (D-1386): its three descriptions and its
    declared help must not say so, and say that the lists are person cards with the flag on or off."""
    said = {"en": "person cards", "ja": "人物カード", "zh-TW": "人員卡片"}
    importlib.import_module("console.admin_flags")  # its import joins the flags texts into CATALOGUES (alone too)
    for lang, word in said.items():
        text = CATALOGUES[lang]["flags.desc.layout.phone_first"]
        assert not re.search(r"rows are cards|行はカード|每一列成為卡片|as before\.$|これまでどおりの表示。$", text), (
            lang
        )
        assert word in text, lang
    help_text = fl.DECLARED[phone.FLAG].help
    assert "rows are cards" not in help_text and "person cards (D-1386)" in help_text
