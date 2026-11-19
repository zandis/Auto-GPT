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
from xml.etree import ElementTree

import pytest
from console import i18n_guides
from console.guides import ROLES, title

from tests.console.test_console_app import VIEWER_PW, box, login  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ROOT / "docs" / "guides"
MATRIX = ROOT / "tests" / "console" / "data" / "role_route_matrix.md"
LANGS = ("en", "ja", "zh-TW")
GUIDE_CATALOGUES = {"en": i18n_guides.EN, "ja": i18n_guides.JA, "zh-TW": i18n_guides.ZH}


@pytest.mark.parametrize("lang", LANGS)
def test_installation_instructions_cover_each_device(lang: str) -> None:
    instructions = {
        "en": (
            "Install in Edge on Windows", "Add to Dock in Safari on macOS", "Share → Add to Home Screen in Safari on iOS",
            "On Android, open the browser menu", "Install or Add to Home screen",
            "device must trust", "certificate authority (CA) provided by hospital IT",
            "FSLogix virtual desktop", "open the console in the browser",
        ),
        "zh-TW": (
            "Windows 的 Edge 選擇「安裝」", "macOS 的 Safari 選擇「加入 Dock」", "iOS 的 Safari 選擇「分享」→「加入主畫面」",
            "Android", "瀏覽器選單選擇「安裝」或「加到主畫面」", "裝置必須信任", "醫院資訊部門提供的憑證授權單位（CA）",
            "FSLogix 虛擬桌面", "在瀏覽器中開啟主控台",
        ),
        "ja": (
            "Windows の Edge では「インストール」", "macOS の Safari では「Dock に追加」", "iOS の Safari では「共有」→「ホーム画面に追加」",
            "Android ではブラウザのメニュー", "「インストール」または「ホーム画面に追加」", "端末", "病院の IT 部門が提供する認証局（CA）を信頼",
            "FSLogix の仮想デスクトップ", "ブラウザでコンソールを開いて",
        ),
    }
    paragraph = GUIDE_CATALOGUES[lang]["guide.install"]
    for instruction in instructions[lang]:
        assert instruction in paragraph


def test_installation_in_every_generated_handout(tmp_path: Path) -> None:
    from tools.role_guides import write

    def snapshot() -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    write(tmp_path)
    first = snapshot()
    write(tmp_path)
    assert snapshot() == first == {p.name: p.read_bytes() for p in GUIDES.glob("*.md")}
    assert len(first) == 21
    for role in ROLES:
        for lang in LANGS:
            blocks = first[f"{role}.{lang}.md"].decode("utf-8").split("\n\n")
            assert [p for p in blocks if "FSLogix" in p] == [GUIDE_CATALOGUES[lang]["guide.install"]]


@pytest.mark.parametrize("role", ROLES)
def test_installation_in_the_signed_in_print_guide(box: dict[str, Any], role: str) -> None:  # noqa: F811
    user = f"guide-{role}"
    box["users"].create(user, role, VIEWER_PW)
    client, csrf = login(box["app"], user, VIEWER_PW)
    for lang in LANGS:
        if lang != "en":
            switched = client.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/help/guide"})
            assert switched.status_code == 200
        help_page = client.get("/help")
        assert 'href="/help/guide"' in help_page.text
        page = client.get("/help/guide")
        assert page.status_code == 200
        article_html = re.search(r"<article\b[^>]*>.*?</article>", page.text, re.S)
        assert article_html
        article = ElementTree.fromstring(article_html.group())
        assert article.get("data-role") == role
        assert article.findtext(".//h1") == title(role, lang)
        paragraphs = [p for p in article.iter("p") if "FSLogix" in "".join(p.itertext())]
        assert len(paragraphs) == 1
        paragraph = paragraphs[0]
        assert paragraph in article.findall("p")  # in the printable article itself
        for node in (article, paragraph):
            assert "hidden" not in node.attrib and "noprint" not in node.get("class", "").split()
        text = "".join(paragraph.itertext())
        assert text == GUIDE_CATALOGUES[lang]["guide.install"]
        assert text in (GUIDES / f"{role}.{lang}.md").read_text(encoding="utf-8").split("\n\n")


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
        prose = [x for x in text.splitlines() if x and not x.startswith(("`", "- `", "|"))]
        assert all(not x.isascii() for x in prose), (role, lang, [x for x in prose if x.isascii()])


def _table() -> dict[str, dict[str, str]]:
    """ "METHOD route" -> persona column -> the table's answer (Y, n, -)."""
    lines = MATRIX.read_text(encoding="utf-8").splitlines()
    head = next(x for x in lines if x.startswith("| Method |"))
    cols = [c.strip() for c in head.strip("|").split("|")]
    out: dict[str, dict[str, str]] = {}
    for x in lines:
        cells = [c.strip() for c in x.strip("|").split("|")]
        if len(cells) == len(cols) and cells[0] in ("GET", "POST", "PUT", "DELETE"):
            out[f"{cells[0]} {cells[1].strip('`')}"] = dict(zip(cols[2:], cells[2:], strict=True))
    return out


def expected_pages(role: str) -> tuple[tuple[str, bool], ...]:
    """The help pages the role opens (and may act on) in the generated table, marked where only its widest persona
    does."""
    from console import guides

    table = _table()
    narrow, wide = guides.PERSONAS[role]

    def opens(slug: str, col: str) -> bool:
        return all(table[r][col] == "Y" for r in guides.PAGES[slug] if r is not None)

    return tuple((s, not opens(s, narrow)) for s in guides.PAGES if opens(s, wide))


def test_each_roles_pages_are_the_help_pages_it_opens_and_acts_on() -> None:
    from console import guides

    table = _table()
    for slug, routes in guides.PAGES.items():  # each canonical route is a row of the table
        assert all(r in table for r in routes if r is not None), slug
    for role in guides.ROLES:
        assert guides.ROLE_PAGES[role] == expected_pages(role), (role, expected_pages(role))


def test_each_help_page_of_the_guides_is_a_help_page_of_the_panel() -> None:
    from console import guides
    from console.step4 import HELP_SLUGS, help_slug

    for slug, (get, _act) in guides.PAGES.items():
        route = get.split(" ", 1)[1].replace("{rs}", "GZQO").replace("{pid}", "a" * 32).replace("{ruleset}", "GZQO")
        assert slug in HELP_SLUGS and help_slug(route) == slug, (slug, route, help_slug(route))


def test_every_command_to_try_opens_a_page_the_role_opens() -> None:
    """A command the guide offers works for the role: it is understood and its page is one the role opens."""
    import re as _re

    from console import guides
    from console.command import interpret, url_of

    table = _table()
    gets = [(k, _re.compile("^" + _re.sub(r"\\\{[^}]+\\\}", "[^/]+", _re.escape(k.split(" ", 1)[1])) + "$"))
            for k in table if k.startswith("GET ")]  # fmt: skip
    for role in guides.ROLES:
        for lang in LANGS:
            for ex in guides.examples(role, lang):
                act = interpret(ex.replace("STUDY", "GZQO"), ["GZQO"], role)
                assert act.intent not in ("unknown", "forbidden"), (role, lang, ex, act.intent)
                url = url_of(act, role)
                if url is None:
                    continue
                path = url.split("?")[0]
                rows = [k for k, rx in gets if rx.match(path)]
                assert rows and any(table[k][guides.PERSONAS[role][1]] == "Y" for k in rows), (role, lang, ex, path)


def test_every_word_of_a_guide_is_in_its_own_language_catalogue() -> None:
    """No English fallback anywhere: every key a guide uses is in that language's catalogue itself."""
    from console import guides
    from console.i18n import CATALOGUES

    for role in guides.ROLES:
        for lang in ("ja", "zh-TW"):
            missing = [k for k in guides.keys(role) if k not in CATALOGUES[lang]]
            assert not missing, (role, lang, missing)


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
