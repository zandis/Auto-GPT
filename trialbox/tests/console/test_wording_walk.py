"""T-506 and T-116 (CR-078, FIT-006, REG-017, REG-020): the forbidden-word walk over every role's pages, and the
intended-use statement in the footer in the reader's language.

Every GET page each of the five roles can open (home, study pages, job pages, team, site and operations pages) is
fetched in three languages with a finished screening run, a "criteria not matched" list, a feasibility run and a case
run on the box; :func:`tb_common.wording.check_page` must find none of the words of TB-IU-01 §2 ("excluded", 除外,
排除, 診断, 判定, 対象外, "diagnosis" and the rest of ``FORBIDDEN``) and no "likely eligible" label."""

from __future__ import annotations

import html
import re
from typing import Any

import pytest
from console import people_lists
from console.auth import ROLES
from fastapi.routing import APIRoute
from tb_common.wording import FORBIDDEN, STATEMENT, check_page

from tests.console.test_console_app import _done_case, _done_feas, box, login, name_pi  # noqa: F401 - fixture by name
from tests.console.test_excluded_page import _with_excluded

PW = "wording-walk-password-01"
LANGS = ("en", "ja", "zh-TW")
VALUES = {"rs": "GZQO", "ruleset": "GZQO", "pid": "c" * 32, "record": "1", "event": "1", "fmt": "csv", "form": "f",
          "cid": "1", "fid": "1", "name": "codes", "kind": "x"}  # fmt: skip
SKIP = re.compile(r"^/(api/|static/|logout|login|lang|health|metrics|cmd|ask)")


# A cell marked data-wording="source" shows another source's words as written (a catalogue item's name, such as LOINC
# 21854-5 "Date of cancer diagnosis", and its protocol phrasing): data, not the product's wording (D-351 item 5).
# Only such cells are left out; the rest of the page, its headings and its help, is checked.
_SOURCE_CELL = re.compile(r'<td\b[^>]*\bdata-wording="source"[^>]*>.*?</td>', re.S)


def _product_words(page: str) -> str:
    return _SOURCE_CELL.sub("<td></td>", page)


def _pages(app: Any, values: dict[str, str]) -> list[str]:
    out = []
    for r in app.routes:
        if not isinstance(r, APIRoute) or "GET" not in (r.methods or set()):
            continue
        names = re.findall(r"{(\w+)(?::\w+)?}", r.path)
        if not all(n in values for n in names):
            continue
        path = re.sub(r"{(\w+)(?::\w+)?}", lambda m: values[m.group(1)], r.path)
        if not SKIP.match(path):
            out.append(path)
    return out


def _statement_of(page: str) -> str | None:
    """The intended-use statement a page shows in its footer (TB-IU-01 C1), as a reader sees it; None when the page
    has no such footer line."""
    foot = page[page.rfind("<footer") :] if "<footer" in page else ""
    m = re.search(r'data-testid="intended-use">(.*?)</p>', foot, re.S)
    return html.unescape(m.group(1)) if m else None


def _walk(b: dict[str, Any], user: str, lang: str) -> tuple[list[str], list[str], list[str]]:
    c, csrf = login(b["app"], user, PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    paths = _pages(b["app"], VALUES)
    for job in list(b["backend"].jobs):
        paths += _pages(b["app"], {**VALUES, "job_id": job})
    seen, bad, unstated = [], [], []
    for path in sorted(set(paths)):
        r = c.get(path)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            continue
        seen.append(r.url.path)
        bad += [f"{path}: {h.word!r} in …{h.context}…" for h in check_page(_product_words(r.text))]
        if _statement_of(r.text) != STATEMENT[lang]:  # NEW-IU-1 (D-703): on every page, in the reader's language
            unstated.append(path)
    return seen, bad, unstated


# the pages that carried the old words, per role: a clean walk that never reached them would mean nothing
MUST_REACH: dict[str, tuple[str, ...]] = {
    "investigator": ("/studies/GZQO/not-matched", "/studies/GZQO/feasibility", "/studies/GZQO/week", "/help"),
    "coordinator": ("/studies/GZQO/not-matched", "/studies/GZQO/feasibility", "/studies/GZQO/week", "/site/codes"),
    "admin": ("/admin", "/site/codes", "/site/start", "/pilot/case"),
    "viewer": ("/reports", "/help"),
    "cro": ("/reports", "/about"),
    "steward": ("/breakglass", "/about"),
    "privacy": ("/site/opt-outs", "/about"),
}


def test_the_walk_covers_every_role() -> None:
    assert set(MUST_REACH) == set(ROLES)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("role", ROLES)
def test_no_forbidden_word_on_any_role_page(box: dict[str, Any], role: str, lang: str) -> None:  # noqa: F811
    _with_excluded(box)
    _done_feas(box["backend"])
    _done_case(box["backend"])
    box["users"].create("walker", role, PW, "walker@hospa.test")
    if role == "investigator":
        name_pi(box, "walker")  # D-380 (ROLE-008): the steward names the PI
    seen, bad, unstated = _walk(box, "walker", lang)
    for must in MUST_REACH[role]:
        if people_lists.flag_now():  # J-5 (D-1223): with the flag on, the weekly page is a view of Candidates
            must = must.replace("/studies/GZQO/week", "/studies/GZQO/people/candidates/week")
        assert must in seen, f"the walk did not reach {must}"
    assert bad == []
    # NEW-IU-1 (D-703): every page this role can open carries the intended-use statement, in the reader's language
    assert unstated == [], f"{role}/{lang}: pages without the intended-use statement: {unstated}"
    assert len(seen) >= 5


@pytest.mark.parametrize("lang", LANGS)
def test_the_footer_carries_the_statement_in_the_reader_language(box: dict[str, Any], lang: str) -> None:  # noqa: F811
    c, csrf = login(box["app"])
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    page = c.get("/").text
    foot = page[page.index("<footer") :]
    m = re.search(r'data-testid="intended-use">(.*?)</p>', foot, re.S)
    assert m
    assert html.unescape(m.group(1)) == STATEMENT[lang]
    for other in LANGS:
        if other != lang:
            assert STATEMENT[other] not in html.unescape(foot)


def test_only_cells_marked_as_source_text_are_left_out() -> None:
    """The exemption is narrow: a catalogue cell marked as source text is skipped; the same word in any other cell, or
    in a heading of the same page, is still a hit."""
    page = (
        '<table><tr><td data-wording="source">Date of cancer diagnosis</td><td>diagnosis</td></tr></table><h2>判定</h2>'
    )
    assert sorted(h.word for h in check_page(_product_words(page))) == sorted(["diagnosis", "判定"])


def test_a_planted_word_fails_the_walk() -> None:
    """The check is not blind: 除外 planted in a page is found; the statement's own negations are not."""
    page = f"<main><h1>除外された患者</h1></main><footer><p>{STATEMENT['ja']}</p></footer>"
    assert [h.word for h in check_page(page)] == ["除外"]
    assert check_page(f"<footer>{STATEMENT['zh-TW']}</footer>") == []


@pytest.mark.parametrize("word", ["診断", "判定", "対象外", "診斷", "diagnosis", "risk score"])
def test_a_planted_word_of_the_full_list_fails_the_walk(word: str) -> None:
    """T-116: the words T-506 left for later are on the one list the walk uses; the statement's 診断 / 診斷 are not
    hits, because the statement is masked whole."""
    assert word in FORBIDDEN
    lang = "ja" if word in ("診断", "判定", "対象外") else "zh-TW" if word == "診斷" else "en"
    page = f"<main><p>{word}</p></main><footer><p>{STATEMENT[lang]}</p></footer>"
    assert [h.word for h in check_page(page)] == [word]


def test_the_sign_in_page_carries_the_statement_before_anyone_signs_in(box: dict[str, Any]) -> None:  # noqa: F811
    """NEW-IU-1 (D-703): the one page a person sees without an account. The language is the browser's."""
    from fastapi.testclient import TestClient

    for lang, accept in (("en", "en-GB"), ("ja", "ja-JP"), ("zh-TW", "zh-TW")):
        r = TestClient(box["app"]).get("/login", headers={"Accept-Language": accept})
        assert r.status_code == 200 and _statement_of(r.text) == STATEMENT[lang], lang


def test_a_page_without_the_statement_or_with_another_languages_fails_the_walk() -> None:
    assert _statement_of("<main><p>x</p></main>") is None
    assert _statement_of(f"<p>{STATEMENT['en']}</p><footer><p>no statement here</p></footer>") is None
    ja = f'<footer><p class="hint" data-testid="intended-use">{html.escape(STATEMENT["ja"])}</p></footer>'
    assert _statement_of(ja) == STATEMENT["ja"] != STATEMENT["en"]
