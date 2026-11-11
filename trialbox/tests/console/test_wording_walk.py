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
from console.auth import ROLES
from fastapi.routing import APIRoute
from tb_common.wording import FORBIDDEN, STATEMENT, check_page

from tests.console.test_console_app import _done_case, _done_feas, box, login  # noqa: F401 - fixture by name
from tests.console.test_excluded_page import _with_excluded

PW = "wording-walk-password-01"
LANGS = ("en", "ja", "zh-TW")
VALUES = {"rs": "GZQO", "ruleset": "GZQO", "pid": "c" * 32, "record": "1", "event": "1", "fmt": "csv", "form": "f",
          "cid": "1", "fid": "1", "name": "codes", "kind": "x"}  # fmt: skip
SKIP = re.compile(r"^/(api/|static/|logout|login|lang|health|metrics|cmd|ask)")


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


def _walk(b: dict[str, Any], user: str, lang: str) -> tuple[list[str], list[str]]:
    c, csrf = login(b["app"], user, PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    paths = _pages(b["app"], VALUES)
    for job in list(b["backend"].jobs):
        paths += _pages(b["app"], {**VALUES, "job_id": job})
    seen, bad = [], []
    for path in sorted(set(paths)):
        r = c.get(path)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            continue
        seen.append(r.url.path)
        bad += [f"{path}: {h.word!r} in …{h.context}…" for h in check_page(r.text)]
    return seen, bad


# the pages that carried the old words, per role: a clean walk that never reached them would mean nothing
MUST_REACH: dict[str, tuple[str, ...]] = {
    "investigator": ("/studies/GZQO/not-matched", "/studies/GZQO/feasibility", "/studies/GZQO/week", "/help"),
    "coordinator": ("/studies/GZQO/not-matched", "/studies/GZQO/feasibility", "/studies/GZQO/week", "/site/codes"),
    "admin": ("/admin", "/site/codes", "/site/start", "/pilot/case"),
    "viewer": ("/reports", "/help"),
    "cro": ("/reports", "/about"),
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
    seen, bad = _walk(box, "walker", lang)
    for must in MUST_REACH[role]:
        assert must in seen, f"the walk did not reach {must}"
    assert bad == []


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
