"""T-506 (the PoC part of T-116; CR-078, FIT-006, REG-017, REG-020): the forbidden-word walk over the investigator's
and the coordinator's pages, and the intended-use statement in the footer in the reader's language.

Every GET page the two roles can open (home, study pages, job pages, team and site pages) is fetched in three
languages with a finished screening run, a "criteria not matched" list, a feasibility run and a case run on the box;
:func:`tb_common.wording.check_page` must find no "excluded", 除外, 排除 and no "likely eligible" label."""

from __future__ import annotations

import html
import re
from typing import Any

import pytest
from fastapi.routing import APIRoute
from tb_common.wording import STATEMENT, check_page

from tests.console.test_console_app import _done_case, _done_feas, box, login, name_pi  # noqa: F401 - fixture by name
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


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("role", ["investigator", "coordinator"])
def test_no_forbidden_word_on_the_pi_and_crc_pages(box: dict[str, Any], role: str, lang: str) -> None:  # noqa: F811
    _with_excluded(box)
    _done_feas(box["backend"])
    _done_case(box["backend"])
    box["users"].create("walker", role, PW, "walker@hospa.test")
    if role == "investigator":
        name_pi(box, "walker")  # D-380 (ROLE-008): the steward names the PI
    seen, bad = _walk(box, "walker", lang)
    # the pages that carried the old words are reached, so a clean walk means something
    for must in ("/studies/GZQO/excluded", "/studies/GZQO/feasibility", "/studies/GZQO/week"):
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
