"""Lane H, PoC item 2: "Your first day" in Help, one page per role (investigator, coordinator, steward, administrator)
and seven one-page procedures, in en, ja and zh-TW.

* each of the four roles opens its own first-day page in every language, and Help links it for those roles only;
* every procedure has the same parts in all three languages, and each button or page it names is the console's own
  label in that language (the words come from the catalogue, none is typed twice);
* every link on these pages is a real route, and opens for the role that is shown it;
* no raw text key reaches a page;
* a role without a first-day page, or a procedure the role does not use, is refused (404), as ``/help/guide`` gives
  an account only its own role's guide.

Synthetic data only."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

import pytest
from console import first_day, guides
from console.i18n import CATALOGUES, lookup

from tests.console import test_console_app as base

VIEWER_PW = base.VIEWER_PW
login = base.login
fd_box = base.box  # the console box fixture, under this module's own name

LANGS = ("en", "ja", "zh-TW")
ROLES = ("investigator", "coordinator", "steward", "admin")
OTHER_ROLES = ("viewer", "cro", "privacy")
SLUGS = ("install-check", "first-night", "approve-study", "review-list", "contact-consent", "backup-restore",
         "when-held")  # fmt: skip
HREF = re.compile(r'href="([^"]+)"')
KEYLIKE = re.compile(r"\b(?:fd|help|guide|mark|s20|ops|dataops|outcome|sstate|consent|nav|flags|datastep|stillneeded"
                     r"|role)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*\b")  # fmt: skip
TAG = re.compile(r"<[^>]+>")


def _client(fd_box: dict[str, Any], role: str, lang: str) -> Any:
    user = f"fd-{role}"
    if fd_box["users"].get(user) is None:
        fd_box["users"].create(user, role, VIEWER_PW)
    client, csrf = login(fd_box["app"], user, VIEWER_PW)
    if lang != "en":
        assert client.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/help"}).status_code == 200
    return client


def _article(html: str) -> str:
    body = re.search(r"<article\b.*?</article>", html, re.S)
    assert body, html[:300]
    return body.group()


def _text(html: str) -> str:
    return unescape(TAG.sub(" ", _article(html)))


def test_the_roles_and_procedures_are_the_ones_named() -> None:
    assert tuple(first_day.ROLE_PROCEDURES) == ROLES
    assert first_day.PROCEDURES == SLUGS
    for role in ROLES:
        assert role in guides.ROLES
        assert set(first_day.ROLE_PROCEDURES[role]) <= set(SLUGS)
    used = {s for procs in first_day.ROLE_PROCEDURES.values() for s in procs}
    assert used == set(SLUGS)  # none is written for nobody


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("role", ROLES)
def test_each_role_opens_its_first_day_page(fd_box: dict[str, Any], role: str, lang: str) -> None:
    client = _client(fd_box, role, lang)
    help_page = client.get("/help")
    assert 'href="/help/first-day"' in help_page.text
    page = client.get("/help/first-day")
    assert page.status_code == 200
    assert f'data-role="{role}"' in page.text
    assert 'data-testid="first-day"' in page.text
    assert first_day.title(lang) in _text(page.text)
    hrefs = HREF.findall(page.text)
    for slug in first_day.ROLE_PROCEDURES[role]:
        assert f"/help/first-day?procedure={slug}" in hrefs
    for slug in set(SLUGS) - set(first_day.ROLE_PROCEDURES[role]):
        assert f"/help/first-day?procedure={slug}" not in hrefs  # only the procedures this role uses
    # the page shows the signed-in role's, in that language, and no other role's page
    assert first_day.today(role, lang) in _text(page.text)
    for other in ROLES:
        if other != role:
            assert first_day.today(other, lang) not in _text(page.text)


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_a_role_without_a_first_day_page_is_sent_to_its_own_guide_and_not_linked(
    fd_box: dict[str, Any], role: str
) -> None:
    client = _client(fd_box, role, "en")
    assert 'href="/help/first-day"' not in client.get("/help").text
    # no first-day page for the role: Help's other pages answer, so the account is sent to its own role guide
    for path in ("/help/first-day", "/help/first-day?procedure=install-check"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/help/guide", path


@pytest.mark.parametrize("role", ROLES)
def test_a_role_cannot_open_a_procedure_it_does_not_use(fd_box: dict[str, Any], role: str) -> None:
    client = _client(fd_box, role, "en")
    for slug in set(SLUGS) - set(first_day.ROLE_PROCEDURES[role]):
        assert client.get(f"/help/first-day?procedure={slug}").status_code == 404
    assert client.get("/help/first-day?procedure=no-such-procedure").status_code == 404


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("role", ROLES)
def test_each_procedure_of_the_role_renders_and_links_resolve(fd_box: dict[str, Any], role: str, lang: str) -> None:
    client = _client(fd_box, role, lang)
    routes = [r for r in fd_box["app"].routes if hasattr(r, "path_regex")]
    pages = ["/help/first-day", *[f"/help/first-day?procedure={s}" for s in first_day.ROLE_PROCEDURES[role]]]
    seen: set[str] = set()
    for path in pages:
        page = client.get(path)
        assert page.status_code == 200, path
        text = _text(page.text)
        assert not KEYLIKE.search(text), (path, KEYLIKE.search(text))  # no raw text key
        for href in HREF.findall(_article(page.text)):
            target = href.split("?")[0].split("#")[0]
            if not target.startswith("/") or target.startswith("/static") or target in seen:
                continue
            seen.add(target)
            assert any(r.path_regex.fullmatch(target) for r in routes), target  # a real route
            assert client.get(target).status_code < 400, (role, target)  # and one this role opens
    for slug in first_day.ROLE_PROCEDURES[role]:
        proc = client.get(f"/help/first-day?procedure={slug}")
        parts = first_day.procedure_of(slug, role, lang)
        assert parts["title"] in proc.text
        assert len(re.findall(r'data-testid="fd-step"', proc.text)) == len(parts["steps"]) >= 4
        assert 'href="/help/first-day"' in proc.text  # back to the first-day page


def test_every_procedure_has_the_same_parts_in_all_languages() -> None:
    for slug in SLUGS:
        shapes = {}
        for lang in LANGS:
            cat = CATALOGUES[lang]
            keys = sorted(k for k in cat if k.startswith(f"fd.proc.{slug}."))
            assert all(cat[k].strip() for k in keys), (slug, lang)
            shapes[lang] = keys
        assert shapes["en"] == shapes["ja"] == shapes["zh-TW"], slug
        parts = {lang: first_day.procedure_of(slug, "admin" if slug in first_day.ROLE_PROCEDURES["admin"] else
                                           first_day.PROCEDURE_ROLES[slug][0], lang) for lang in LANGS}  # fmt: skip
        for lang in LANGS:
            assert set(parts[lang]) == {"title", "use", "steps", "note", "links"}
            assert len(parts[lang]["steps"]) == len(parts["en"]["steps"]) >= 4
        assert "fd.proc" not in str(parts)


def test_a_procedure_names_only_the_consoles_own_labels() -> None:
    labels = first_day.LABELS
    for lang in LANGS:
        for name, key in labels.items():
            words = lookup(lang, key)
            assert words and "{" not in words, (lang, name, key)  # a label, quoted as the console shows it
            assert words != lookup("en", key) or lang == "en" or name in first_day.SAME_IN_ALL, (lang, name)
    for slug in SLUGS:
        for lang in LANGS:
            for key, text in CATALOGUES[lang].items():
                if key.startswith(f"fd.proc.{slug}."):
                    assert set(re.findall(r"\{(\w+)\}", text)) <= set(labels) | {"backup_key"}, key
    # a label that a step quotes is on the page the role reads, word for word
    for slug in SLUGS:
        role = first_day.PROCEDURE_ROLES[slug][0]
        for lang in LANGS:
            body = " ".join(first_day.procedure_of(slug, role, lang)["steps"])
            quoted = {n for n in labels if "{" + n + "}" in CATALOGUES["en"]["fd.proc." + slug + ".step.1"]}
            for n in quoted:
                assert (lookup(lang, labels[n]) or "") in body


def test_the_rules_are_stated_on_every_first_day_page(fd_box: dict[str, Any]) -> None:
    en = CATALOGUES["en"]
    rules = [en[f"fd.rule.{n}"] for n in range(1, 5)]
    assert "two" in rules[0].lower() and "signature" in rules[0] and "real patients" in rules[0]
    assert "never excludes" in rules[1] and "leaves the list" in rules[1]
    assert "cannot open without a backup key" in rules[2]
    assert "Japanese" in rules[3] and "off elsewhere" in rules[3]
    for lang in LANGS:
        client = _client(fd_box, "coordinator", lang)
        text = _text(client.get("/help/first-day").text)
        for n in range(1, 5):
            assert (lookup(lang, f"fd.rule.{n}") or "") in text


def test_the_japanese_and_traditional_chinese_pages_have_no_english_sentences() -> None:
    latin = re.compile(r"[A-Za-z]{4,}(?: [A-Za-z]{3,}){2,}")  # three English words in a row
    for lang in ("ja", "zh-TW"):
        for key, text in CATALOGUES[lang].items():
            if key.startswith("fd."):
                assert not latin.search(text), (lang, key, text)
    ja = CATALOGUES["ja"]
    assert all(re.search(r"[぀-ヿ一-鿿]", ja[k]) for k in ja if k.startswith("fd.") and "{" not in ja[k])
