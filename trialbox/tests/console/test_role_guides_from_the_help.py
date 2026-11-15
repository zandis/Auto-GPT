"""T-317 (D-774), lane C2's half: the role guides in en, ja and zh-TW, generated from the console's help catalogue.

The guides are the training handout (WS-17.1) and must say what the console says: one source, the help catalogue. For
each role: what the role does, what the matrix lets it do, the pages it opens (each with the page's own help text),
the words it meets, the commands to try and where to ask. ``python -m tools.role_guides`` writes
``docs/guides/<role>.<lang>.md``; Help serves the signed-in account's own guide, printable, at ``/help/guide``.

* the committed guides are exactly what the tool writes from the catalogue (a help text changed without the guides
  fails here);
* the ja and zh-TW guides have no English fallback and no catalogue key;
* each role's pages are the help pages the role opens in the generated role-route table, no more, no fewer;
* ``/help/guide`` gives the account its own role's guide in its language, and Help links it.

Synthetic data only."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.console.test_console_app import VIEWER_PW, box, login  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ROOT / "docs" / "guides"
MATRIX = ROOT / "tests" / "console" / "data" / "role_route_matrix.md"
LANGS = ("en", "ja", "zh-TW")


def test_the_committed_guides_are_what_the_tool_writes() -> None:
    from console import guides

    for role in guides.ROLES:
        for lang in LANGS:
            path = GUIDES / f"{role}.{lang}.md"
            assert path.is_file(), path
            assert path.read_text(encoding="utf-8") == guides.markdown(role, lang), (
                f"{path.name} differs from the help catalogue: run python -m tools.role_guides"
            )


@pytest.mark.parametrize("lang", ["ja", "zh-TW"])
def test_a_guide_in_japanese_or_chinese_has_no_english_fallback(lang: str) -> None:
    from console import guides

    for role in guides.ROLES:
        text = guides.markdown(role, lang)
        assert not re.search(r"\b(help|guide|life|cmd|role)\.[a-z_]+\b", text), (role, lang)  # no catalogue key
        for heading in re.findall(r"^#+ (.+)$", text, re.M):
            assert not heading.isascii(), (role, lang, heading)
        prose = [x for x in text.splitlines() if x and not x.startswith(("`", "-   `", "|"))]
        assert sum(not x.isascii() for x in prose) >= 0.8 * len(prose), (role, lang)


def _table_pages() -> dict[str, set[str]]:
    """persona column -> the help slugs of the pages (GET, not /api) the persona opens in the generated table."""
    from console.step4 import help_slug

    lines = MATRIX.read_text(encoding="utf-8").splitlines()
    head = next(x for x in lines if x.startswith("| Method |"))
    cols = [c.strip() for c in head.strip("|").split("|")]
    out: dict[str, set[str]] = {c: set() for c in cols[2:]}
    for x in lines:
        cells = [c.strip() for c in x.strip("|").split("|")]
        if len(cells) != len(cols) or cells[0] != "GET":
            continue
        route = cells[1].strip("`")
        if route.startswith("/api/") or help_slug(route) == "other":
            continue
        for col, v in zip(cols[2:], cells[2:], strict=True):
            if v == "Y":
                out[col].add(help_slug(route))
    return out


def test_each_roles_pages_are_the_help_pages_it_opens() -> None:
    from console import guides

    table = _table_pages()
    for role in guides.ROLES:
        assert set(guides.ROLE_PAGES[role]) == table[guides.PERSONA[role]], (
            role, set(guides.ROLE_PAGES[role]) ^ table[guides.PERSONA[role]])  # fmt: skip


def test_help_serves_the_accounts_own_guide_in_its_language(box: dict[str, Any]) -> None:  # noqa: F811
    from console import guides

    c, csrf = login(box["app"], "viewer", VIEWER_PW)
    page = c.get("/help").text
    assert 'href="/help/guide"' in page
    r = c.get("/help/guide")
    assert r.status_code == 200 and 'data-testid="role-guide"' in r.text and 'data-role="viewer"' in r.text
    assert guides.title("viewer", "en") in r.text
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/help"})
    assert guides.title("viewer", "ja") in c.get("/help/guide").text
