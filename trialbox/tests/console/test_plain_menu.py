# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""J-7 (D-1251; the journey review's R17, R18 and R22, section D): a pruned "More", one name per page, and no job word
or variable name on a clinical page, behind the flag ``layout.plain_menu``.

* the flag is declared, off by default, described in three languages, read with the other layout flags in one read;
* one name per page: for every menu entry of every role, on the opening page and on a study page, in en, ja and
  zh-TW, the menu's label, the page's title and its main heading are the same words (the study code and other data
  segments set aside);
* the pruned menu: each role's top bar and "More" as the checkpoint ruled, the steward's bar at four, nothing twice;
  nothing that leaves "More" becomes unreachable by clicks; each new link is shown exactly where its page answers 200
  and offers the account its action (each role offered each action as on master; the reads a page with a link adds,
  named); the cascade only where the site drop is mounted;
* the clinical pages (R22), decided by an allow-list (``plain_text_walk.py``) in three languages, with the test-site
  banner on each and the hand-fixed keys pinned;
* the flag off: every page byte for byte the page without this card's parts; the flag on: every route answers every
  role as the committed tables say (the role-by-route matrix and the V-2 walk, signed out included); every
  combination with the other three layout flags.

Synthetic data only (the test box's study GZQO)."""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from console import phone
from tb_common import flags as fl

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box  # noqa: F401
from tests.console.test_role_route_matrix import COLUMNS, _clients, _for, _orchestrator_routes

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
    """The administrator's change on /ops/flags: audited, with a reason (none when the flag already has the value)."""
    fl.clear_cache()
    if fl.Flags().row(FLAG) != value:
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
#: catalogue words that stand for a value of the page's context in a heading (the site workspace's own name: the
#: hospital's, or the practice one), read as data like the study code
CONTEXT_KEYS = ("site.ws.main", "site.ws.practice")
#: menu entries that answer 403 with the flag on, as with it off: the investigator in no delegation log reads no
#: patient-level list (master's menu links them the same; the page says why). Listed, never skipped silently
REFUSED_MENU_ENTRIES = frozenset(
    {("pi", "/week"), ("pi", f"/studies/{RS}/candidates"), ("pi", f"/studies/{RS}/conflicts"),
     ("pi", f"/studies/{RS}/entry"), ("pi", f"/studies/{RS}/referrals")}
)  # fmt: skip


def _context_words(lang: str) -> set[str]:
    from console.i18n import CATALOGUES

    from tests.console.plain_text_walk import unmark

    return {unmark(CATALOGUES[lang][k]) for k in CONTEXT_KEYS}


def name_of(text: str, lang: str) -> str:
    """A label's or a heading's name: its " · " parts without the data values (a study code, a year, an id, an
    account name) and the context's own name (:data:`CONTEXT_KEYS`)."""
    from tests.console.plain_text_walk import data_value, unmark

    ctx = _context_words(lang)
    parts = [p.strip() for p in unmark(text).split(" · ") if p.strip()]
    return " · ".join(p for p in parts if p not in ctx and not data_value(p))


def _heading(page_text: str, tag: str = "h1") -> list[str]:
    """The texts of a page's ``tag`` headings, without a hint inside one (a date, "not entered yet")."""
    found = re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", page_text, re.S)
    return [_text(re.sub(r'<span class="hint[^"]*">.*?</span>', "", h, flags=re.S)) for h in found]


def test_every_menu_entry_has_one_name_its_label_title_and_heading_in_three_languages(box: dict[str, Any]) -> None:
    """For every role, every entry of its menu (top bar and "More") on the opening page and on a study page, in each
    language: the page the entry opens has the entry's label as its main heading and as its title's first part (each
    without its data values: the study code, a year, the site's name). A page that refuses the account is listed
    (:data:`REFUSED_MENU_ENTRIES`), never skipped silently."""
    _orchestrator_routes(box)  # the steward's clinical conflicts ask the orchestrator (D-865)
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    _flag(box, "on")
    differ: list[str] = []
    refused: set[tuple[str, str]] = set()
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
                _for(box, href)
                r = page.get(href)
                if r.status_code == 403:
                    refused.add((col, href))
                    continue
                assert r.status_code == 200, (col, lang, href, r.status_code)
                title = re.search(r"<title>(.*?)</title>", r.text, re.S)
                t_first = _text(title.group(1)).split(" · ")[0] if title else ""
                h1 = _heading(r.text)
                name = name_of(label, lang)
                if len(h1) != 1 or name_of(h1[0], lang) != name or name_of(t_first, lang) != name:
                    differ.append(f"{col} [{lang}] {href}: menu {name!r} · title {t_first!r} · heading {h1}")
        _lang(page, csrf, "en")
    assert not differ, "a page's menu label, title and heading differ:\n" + "\n".join(differ)
    assert refused == REFUSED_MENU_ENTRIES, sorted(refused ^ REFUSED_MENU_ENTRIES)
    _flag(box, "off")
    for col, href in REFUSED_MENU_ENTRIES:  # the same entries on master's menu: not a link this card adds
        page, _, _ = clients[col]
        top, under = menu(page.get("/home").text)
        top2, under2 = menu(page.get(MENU_PAGES[1]).text)
        assert href in {h for h, _ in top + under + top2 + under2}, (col, href)


#: pages a link check opens besides the menu's: the pages that carry a link the coordinator's review named
LINK_PAGES = (f"/pilot/registry/{RS}", "/site/start?step=1", "/home?view=studies")
#: a heading that names one thing: a pseudonym, or a run's id (a person's chart, a candidate, a run)
THING = re.compile(r"\b[0-9a-f]{8}\b|\b[0-9a-f]{32}\b|…[0-9A-Z]{8}\b")
#: a link to a section the test box does not show (the study store of S28 is not wired here, so the set-up page has no
#: "Who to screen"): its words must be that section's heading (the key), as the page shows it where the store is
ABSENT_SECTIONS = {f"/studies/{RS}/setup#who": "setup.who.title"}


def test_every_link_says_the_name_of_the_page_or_section_it_opens(box: dict[str, Any], monkeypatch: Any) -> None:
    """The coordinator's review of J-7: a link's words are the name of the page it opens (its main heading, without
    data values), or, for a link to an action or a section, the heading of that section on the page it opens. Read on
    every page each role's menu opens (and :data:`LINK_PAGES`), in each language, inside the page (not the menu: the
    test above). A link that carries a data value (a person, a study code, an id, a count) names that thing, not a
    page, and is not checked; nor is a link to the page itself (a tab already open, a filter)."""
    from tests.console.plain_text_walk import CLOSE, OPEN, mark_catalogues

    _orchestrator_routes(box)
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    _flag(box, "on")
    mark_catalogues(monkeypatch)
    differ: set[str] = set()
    checked = 0
    for col in COLUMNS:
        page, csrf, _ = clients[col]
        for lang in LANGS:
            _lang(page, csrf, lang)
            pages: set[str] = set(LINK_PAGES)
            for p in MENU_PAGES:
                top, under = menu(page.get(p).text)
                pages |= {h for h, _ in top + under if not h.startswith("/help")}
            names: dict[str, set[str] | None] = {}  # a target's names, and (key + "#ids") its element ids
            for src in sorted(pages):
                _for(box, src)
                r = page.get(src)
                if r.status_code != 200:
                    continue
                main = re.search(r"<main.*?</main>", r.text, re.S)
                for href, inner in re.findall(r'<a [^>]*href="(/[^"]*)"[^>]*>(.*?)</a>', main.group(0) if main else "",
                                              re.S):  # fmt: skip
                    href = html.unescape(href)
                    path = href.split("#")[0].split("?")[0]
                    words = _text(inner)
                    if path == src.split("?")[0] or not words or href.startswith(("/help", "/ask", "/lang", "/logout")):
                        continue
                    if not (words.startswith(OPEN) and words.endswith(CLOSE) and words.count(OPEN) == 1):
                        continue  # a data value, or no catalogue text: names a thing, not a page
                    target, _, anchor = href.partition("#")
                    if target not in names:
                        _for(box, path)
                        t = page.get(target)
                        ok = t.status_code == 200 and "text/html" in t.headers.get("content-type", "")
                        h1 = [name_of(h, lang) for h in _heading(t.text)] if ok else []
                        if any(THING.search(h) for h in _heading(t.text)):
                            h1 = []  # a person's or a run's own page
                        own = re.search(r"<main.*?</main>", t.text, re.S) if ok else None
                        tabs = {  # the target's own entry on its tab bar (a tab has no heading of its own)
                            name_of(_text(i), lang)
                            for h, i in re.findall(
                                r'<a [^>]*href="([^"]*)"[^>]*>(.*?)</a>', own.group(0) if own else "", re.S
                            )
                            if html.unescape(h) == target
                        }
                        # no page name: a file, a page the account may not open (the role walks), or a thing's own
                        # page (its heading is a data value: a person's chart, a candidate, a run)
                        names[target] = (
                            {*h1, *(name_of(h, lang) for h in _heading(t.text, "h2")), *tabs}
                            if ok and any(h1)
                            else None
                        )
                        names[target + "#ids"] = set(re.findall(r'\sid="([^"]+)"', t.text)) if ok else set()
                    found = names[target]
                    if found is None:
                        continue
                    if anchor and anchor not in (names[target + "#ids"] or set()):
                        assert href in ABSENT_SECTIONS, f"{col} [{lang}] on {src}: {href} opens no section"
                        from console.i18n import CATALOGUES

                        from tests.console.plain_text_walk import unmark

                        assert name_of(words, lang) == unmark(CATALOGUES[lang][ABSENT_SECTIONS[href]]), (col, href)
                        continue
                    checked += 1
                    if name_of(words, lang) not in found:
                        differ.add(f"{col} [{lang}] on {src}: {name_of(words, lang)!r} -> {href} {sorted(found)}")
        _lang(page, csrf, "en")
    assert checked > 100, checked
    assert not differ, "a link's words are not the name of the page it opens:\n" + "\n".join(sorted(differ))


# ------------------------------------------------------------------------------------------- the pruned menu (R17)
#: per column, with the flag on: (top bar, "More" on the opening page, "More" on a study page), as hrefs. The study
#: group (nine pages of the study) is the same as on master and is written once as STUDY.
STUDY = tuple(f"/studies/{RS}/{p}" for p in ("setup", "sources", "conflicts", "entry", "forms", "candidates",
                                              "referrals", "team", "irb"))  # fmt: skip
_HELP = "/help"
_CLIN_HOSPITAL = ("/account", _HELP, "/site", "/notices/received", "/sae")
WANT: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "admin": (
        ("/home", "/home?view=studies", "/ops/users"),
        ("/account", _HELP, "/site", "/notices/received", "/breakglass", "/jobs", "/pilot/request", "/pilot/protocol",
         "/pilot/consent", "/pilot/cascade", "/pilot/case", "/pilot/registry", "/pilot/mailbox", "/settings/notices", "/admin/redcap",
         "/reports/research-office"),
        (),
    ),
    "crc": (
        ("/home", "/week", "/reports", "/pilot/registry"),
        (*_CLIN_HOSPITAL, "/site/staff", "/jobs", "/settings/notices", "/reports/research-office"),
        (*_CLIN_HOSPITAL, *STUDY, "/site/staff", "/jobs", "/settings/notices", "/reports/research-office"),
    ),
    "pi": (
        ("/week", "/pilot/registry", "/reports"),
        (*_CLIN_HOSPITAL, *STUDY, "/site/staff", "/breakglass", "/jobs", "/settings/notices"),
        (),
    ),
    "lpi": (
        ("/week", "/pilot/registry", "/reports"),
        (*_CLIN_HOSPITAL, *STUDY, "/site/staff", "/breakglass", "/jobs", "/settings/notices"),
        (),
    ),
    "smo": (
        ("/home", "/week", "/reports", "/pilot/registry"),
        (*_CLIN_HOSPITAL, "/site/staff", "/settings/notices", "/reports/research-office"),
        (*_CLIN_HOSPITAL, *STUDY, "/site/staff", "/settings/notices", "/reports/research-office"),
    ),
    "cra": (("/reports",), ("/account", _HELP), ()),
    "viewer": (("/reports",), ("/account", _HELP, "/settings/notices", "/reports/research-office"), ()),
    "steward": (
        ("/breakglass", "/site/opt-outs", "/data-ops", "/audit"),
        ("/account", _HELP, "/site/staff", "/data/items", "/data/conflicts", "/ops/flags", "/jobs", "/pilot/case",
         "/pilot/registry", "/settings/notices"),
        (),
    ),
    "privacy": (
        ("/site/opt-outs", "/site/staff", "/audit"),
        ("/account", _HELP, "/jobs", "/pilot/case", "/pilot/registry", "/settings/notices"),
        (),
    ),
}  # fmt: skip


def _hrefs(entries: list[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(_HELP if h.startswith("/help?") else h for h, _ in entries)


def _menus(box: dict[str, Any], on: bool) -> dict[str, dict[str, tuple[tuple[str, ...], tuple[str, ...]]]]:
    """Per column and per menu page: (top bar, "More") as hrefs, with the flag on or off."""
    if "orchestrator_study_api" not in box:
        _orchestrator_routes(box)  # the steward's clinical conflicts ask the orchestrator (D-865)
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    _flag(box, "on" if on else "off")
    out: dict[str, dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {}
    for col in COLUMNS:
        page, _, _ = clients[col]
        out[col] = {}
        for p in MENU_PAGES:
            top, under = menu(page.get(p).text)
            out[col][p] = (_hrefs(top), _hrefs(under))
    return out


def test_each_role_s_menu_is_the_ruled_one_and_the_steward_s_bar_has_four(box: dict[str, Any]) -> None:
    """With the flag on, each role's top bar and "More", on the opening page and on a study page, are the ones the
    checkpoint ruled (Q1 to Q5); no top bar has more than four entries; no entry is listed twice."""
    got = _menus(box, on=True)
    problems = []
    for col, (top, more_home, more_study) in WANT.items():
        home, study = got[col]["/home"], got[col][MENU_PAGES[1]]
        want_study = more_study or more_home
        if home[0] != top or study[0] != top:
            problems.append(f"{col} top bar: {home[0]} / {study[0]}, ruled {top}")
        if home[1] != more_home:
            problems.append(f"{col} More on /home: {home[1]}, ruled {more_home}")
        if study[1] != want_study:
            problems.append(f"{col} More on a study page: {study[1]}, ruled {want_study}")
        for t, m in (home, study):
            assert len(t) <= 4, (col, t)
            assert len(set(t + m)) == len(t + m), (col, "listed twice", t, m)
    assert not problems, "\n".join(problems)


#: entries that leave the menu of every role but the administrator and are reached by no click on purpose, as ruled:
#: pages that exist to act (start a request, draft a consent guide, check one patient): linked where the account may
#: act there (``may_act``); an account the page offers nothing (its button disabled) is not sent there
ACTION_PAGES = ("/pilot/request", "/pilot/consent", "/pilot/case")


def _links(html_text: str) -> set[str]:
    return {html.unescape(h) for h in re.findall(r'<a [^>]*href="(/[^"#]*)"', html_text)}


#: what leaves a role's menu and is linked from no page, though the account may still open it by its address (the
#: routing table is unchanged): ruled at the checkpoint, named in D-1251 for the owner, the site drop mounted. An
#: action page (Q4) is listed only where it offers the account nothing to do
STILL_ALLOWED_NOT_LINKED: tuple[tuple[str, str], ...] = (
    ("crc", "/pilot/cascade"),  # the cascade: the administrator's menu only (a demonstration of the site drop)
    ("crc", "/pilot/mailbox"),  # the test mailbox: the administrator's menu only (a test box's page)
    ("lpi", "/pilot/mailbox"),
    ("pi", "/pilot/mailbox"),
    ("steward", "/pilot/mailbox"),
    ("privacy", "/pilot/mailbox"),
    ("pi", "/pilot/request"),  # the investigator in no delegation log: both pages offer it nothing (Q4)
    ("pi", "/pilot/case"),
)


def test_nothing_that_leaves_more_becomes_unreachable(box: dict[str, Any]) -> None:
    """Every entry a role's menu had on master (the flag off) and has no longer (the flag on) is still reached by
    clicks: a link on a page the new menu opens, or one click further (the Admin page's tabs; a study's IRB page from
    the study's menu), with the synthetic site drop mounted (the cascade available). The only exceptions are the
    named pairs of :data:`STILL_ALLOWED_NOT_LINKED`, each still answered as on master."""
    off = _menus(box, on=False)
    on = _menus(box, on=True)
    clients = _clients(box)
    unreached = []
    for col in COLUMNS:
        page, _, _ = clients[col]
        before = {h for p in MENU_PAGES for part in off[col][p] for h in part}
        after = {h for p in MENU_PAGES for part in on[col][p] for h in part}
        gone = before - after
        if not gone:
            continue
        seen: set[str] = set()
        frontier = sorted(after - {_HELP})
        found: set[str] = set()
        for _depth in range(2):
            nxt: list[str] = []
            for href in frontier:
                if href in seen:
                    continue
                seen.add(href)
                _for(box, href)
                r = page.get(href)
                if r.status_code != 200:
                    continue
                links = _links(r.text)
                found |= links
                nxt += sorted(links - seen)
            frontier = [h for h in nxt if not h.startswith(("/help", "/ask", "/cmd", "/logout", "/lang"))][:200]
        for href in sorted(gone):
            if href not in found:
                unreached.append((col, href))
    assert sorted(unreached) == sorted(STILL_ALLOWED_NOT_LINKED), (
        "left the menu and no click reaches it:\n"
        + "\n".join(f"{c}: {h}" for c, h in sorted(set(unreached) ^ set(STILL_ALLOWED_NOT_LINKED)))
    )
    for col, href in STILL_ALLOWED_NOT_LINKED:  # still allowed: the page answers the account as on master
        page, _, _ = clients[col]
        r = page.get(href)
        assert r.status_code == 200, (col, href, r.status_code)
        if href in ACTION_PAGES:  # Q4: an action page is linked only where it offers the account its action
            assert not _acts(href, r.text), (col, href)


def test_the_cascade_is_listed_only_when_the_site_drop_is_mounted(box: dict[str, Any]) -> None:
    """R17 (D-M3): the administrator's menu lists the cascade exactly when the cascade says it works
    (``CascadeRuns.available``: the synthetic site drop is mounted); a menu rule only: the page answers the same."""
    clients = _clients(box)
    _flag(box, "on")
    admin, _, _ = clients["admin"]
    drop = box["dir"] / "site-a" / "patient.csv"  # the test box's mounted site drop
    kept = drop.read_bytes()
    before = admin.get("/pilot/cascade").status_code
    assert "/pilot/cascade" in _hrefs(menu(admin.get("/home").text)[1])  # mounted
    for col in COLUMNS:  # never in a clinical or a register role's menu
        if col != "admin":
            page, _, _ = clients[col]
            assert "/pilot/cascade" not in _hrefs(menu(page.get("/home").text)[1]), col
    drop.unlink()
    try:
        assert "/pilot/cascade" not in _hrefs(menu(admin.get("/home").text)[1])  # not mounted
        assert admin.get("/pilot/cascade").status_code == before
    finally:
        drop.write_bytes(kept)


NEW_LINKS = (
    ("/reports", "link-request", "/pilot/request"),
    (f"/studies/{RS}/irb", "link-consent", "/pilot/consent"),
    (f"/studies/{RS}/week", "link-case", "/pilot/case"),
    ("/pilot/registry", "link-case", "/pilot/case"),
)


def _acts(target: str, page_text: str) -> bool:
    """Whether the page ``target`` offers its action to the account: its form (the request page shows a viewer the
    explanation in place of its forms) or its submit button not disabled."""
    if target == "/pilot/request":
        return 'data-testid="viewer-card"' not in page_text
    button = {"/pilot/consent": "draft-consent", "/pilot/case": "case-submit"}[target]
    m = re.search(rf'<button[^>]*data-testid="{button}"', page_text)
    assert m, target
    return " disabled" not in m.group(0)


def test_each_new_link_is_shown_exactly_when_its_page_opens_for_the_account(box: dict[str, Any]) -> None:
    """Q4 of the checkpoint, for every role of the matrix: on each page that carries one of the new links and opens
    for the account, the link is there exactly when its target answers 200 to that account and offers it its action
    (the page's own rule, ``may_act``, which the link asks too): no link to a refusal or to a page with nothing to do,
    none missing to a page the account can use. With the flag off no page carries one."""
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    _flag(box, "on")
    wrong, shown = [], 0
    for col in COLUMNS:
        page, _, _ = clients[col]
        for where, testid, target in NEW_LINKS:
            r = page.get(where)
            if r.status_code != 200:
                continue
            has = f'data-testid="{testid}"' in r.text
            t = page.get(target)
            usable = t.status_code == 200 and _acts(target, t.text)
            shown += has
            if has != usable:
                wrong.append(f"{col} on {where}: link {'shown' if has else 'missing'}, {target} answers "
                             f"{t.status_code}, its action {'enabled' if usable else 'not offered'}")  # fmt: skip
    assert not wrong, "\n".join(wrong)
    assert shown >= 6  # the links are there for the roles that use them
    _flag(box, "off")
    for col in COLUMNS:
        page, _, _ = clients[col]
        for where, testid, _target in NEW_LINKS:
            assert f'data-testid="{testid}"' not in page.get(where).text, (col, where)


# ------------------------------------------------------------------------------------------- the clinical pages (R22)
#: the clinical roles' columns of the matrix (the coordinator, a study-scoped coordinator, the investigator logged and
#: not, the viewer)
CLINICAL_COLUMNS = ("crc", "smo", "lpi", "pi", "viewer")
#: where a clinical person's walk starts: the opening page, the menu's lists and the study's pages
SEEDS = ("/home", "/week", "/reports", "/pilot/registry", "/jobs", f"/studies/{RS}/week",
         f"/studies/{RS}/feasibility", f"/studies/{RS}/subjects", f"/studies/{RS}/setup", f"/studies/{RS}/team",
         "/sae")  # fmt: skip
#: a run's own page keeps its job id and type code: the record a person reports a problem by (the card's point 4),
#: the administrator's page; a clinical person reaches it from the list of runs and is not walked into it
RUN_RECORD = re.compile(r"^/pilot/jobs/")
#: the keys whose old words were fixed by hand (plain-English jargon the allow-list cannot see, and job words): with
#: the flag on no clinical page shows one of them, so a later card cannot bring the old word back (ruling e)
PINNED_KEYS = ("col.ruleset", "col.job", "reports.run", "week.meta", "feas.meta", "request.feas", "request.screen",
               "request.free.help", "request.version", "request.no_rulesets", "registry.help", "registry.promote",
               "registry.promote.help", "registry.source.screen", "registry.source.case", "case.title", "case.help",
               "consent.help", "protocol.help", "protocol.ruleset", "nav.case", "nav.jobs", "jobs.title",
               "wb.crc.title", "footer", "sae.no_mailbox", "feas.ct.none.unset", "feas.ct.none.unknown",
               "rc.sf_map.help")  # fmt: skip


@pytest.mark.parametrize("lang", LANGS)
def test_a_clinical_page_shows_only_catalogue_text_and_data_values(
    box: dict[str, Any], lang: str, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """R22, decided by an allow-list (``tests/console/plain_text_walk.py``): every page a clinical role reaches by
    links from its opening page, its menu and the study's pages, in each language, with the flag on, shows only
    catalogue text with no identifier-shaped word and data values; none shows a pinned key's old words; each carries
    the test-site banner (ruling a)."""
    from tests.console import plain_text_walk as w

    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    _flag(box, "on")
    w.mark_catalogues(monkeypatch)
    w.pin(monkeypatch, PINNED_KEYS)
    found, pages = [], 0
    for col in CLINICAL_COLUMNS:
        page, csrf, _ = clients[col]
        _lang(page, csrf, lang)
        walked = w.walk(page, SEEDS, depth=2, limit=120, skip=RUN_RECORD, every_page='data-testid="banner"')
        pages += len(walked)
        found += [f"{col} {p}: {x}" for p, xs in walked.items() for x in xs]
    assert pages > 100, pages  # the walk reached the clinical pages
    assert not found, "\n".join(sorted(set(found)))


# ------------------------------------------------------------------------------------------- the flag off
#: the pages compared byte for byte with the flag off (each role's opening page, its lists, the study's pages, the
#: pages whose words or links this card changes)
OFF_PAGES = ("/home", "/week", "/reports", "/pilot/registry", f"/pilot/registry/{RS}", "/jobs", f"/studies/{RS}/week",
             f"/studies/{RS}/feasibility", f"/studies/{RS}/cohort", f"/studies/{RS}/setup", f"/studies/{RS}/team",
             f"/studies/{RS}/irb", "/sae", "/pilot/request", "/pilot/case", "/pilot/consent", "/pilot/protocol",
             "/pilot/cascade", "/account", "/site", "/breakglass", "/site/opt-outs", "/ops/flags")  # fmt: skip
#: (the audit trail is left out: it lists the page views themselves, so no two renders are alike)


def without_j7(text: str) -> str:
    """A template as it was before this card: every J-7 part (between ``{#J7#}`` and ``{#/J7#}``) taken out and each
    ``tp(`` read as ``t(``."""
    return re.sub(r"\{#J7#\}.*?\{#/J7#\}", "", text, flags=re.S).replace("tp(", "t(")


def test_with_the_flag_off_every_page_is_byte_for_byte_the_page_without_this_card(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """Every page is rendered twice with the flag off: from the console's templates, and from the same templates with
    every J-7 part taken out (:func:`without_j7`). The two are the same, byte for byte, for every role of the matrix,
    in three languages."""
    import jinja2

    form = ["with"]
    real = jinja2.FileSystemLoader.get_source

    def source(self: Any, env: Any, name: str) -> Any:
        text, path, _uptodate = real(self, env, name)
        if form[0] == "without":
            text = without_j7(text)
        return text, path, lambda: False  # never kept: each render reads the form asked for

    monkeypatch.setattr(jinja2.FileSystemLoader, "get_source", source)
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    _flag(box, "off")
    compared = 0
    for col in COLUMNS:
        page, csrf, _ = clients[col]
        for lang in LANGS:
            _lang(page, csrf, lang)
            for p in OFF_PAGES:
                if col == "admin" and p == "/home":  # the administrator's home shows live figures
                    continue
                got = {}
                for f in ("with", "without"):  # one after the other: nothing happens between the two
                    form[0] = f
                    got[f] = re.sub(r'name="csrf" value="[^"]+"', "", page.get(p).text)
                assert got["with"] == got["without"], (col, lang, p)
                assert 'data-plain="on"' not in got["with"], (col, lang, p)
                compared += 1
        _lang(page, csrf, "en")
    assert compared == len(COLUMNS) * len(LANGS) * len(OFF_PAGES) - len(LANGS)
    templates = Path(__file__).parents[2] / "services/console/templates"
    assert "{#J7#}" in (templates / "_nav.html").read_text("utf-8")  # the test reads the parts it takes out
    assert "{#J7#}" not in without_j7((templates / "_nav.html").read_text("utf-8"))


# ------------------------------------------------------------------------------------------- no route answers otherwise
def test_with_the_flag_on_every_role_gets_every_route_s_answer_of_the_committed_table(box: dict[str, Any]) -> None:
    """A menu is not a permission. With the flag on, the role-by-route walk (``test_role_route_matrix``: every route,
    every column of the matrix, GET and the changing methods) equals the committed table
    ``tests/console/data/role_route_matrix.md``, which equals the walk on master with the flag off."""
    from tests.console import test_role_route_matrix as rrm

    _flag(box, "on")
    walked = rrm.walk(box)
    assert phone.read_now()[FLAG]  # still on at the end of the walk
    have = rrm.parse(rrm.render(walked))
    want = rrm.parse(rrm.TABLE.read_text(encoding="utf-8"))
    diff = [f"{k}: table {want.get(k)} walk {have.get(k)}" for k in sorted(set(want) | set(have))
            if want.get(k) != have.get(k)]  # fmt: skip
    assert not diff, "\n".join(diff)
    pairs = sum(len(c) for c in have.values())
    assert pairs == len(have) * len(rrm.COLUMNS) and len(have) > 150
    print(f"role-route matrix with {FLAG} on: {len(have)} routes x {len(rrm.COLUMNS)} columns = {pairs} pairs")


def test_with_the_flag_on_the_role_walk_answers_every_route_as_its_declared_row(
    box: dict[str, Any], tmp_path: Path
) -> None:  # fmt: skip
    """The walk of card V-2 (every route as every column: the roles, signed out, in- and out-of-scope accounts, the
    PI, a sub-investigator, a monitor grant) with the flag on: every route answers every column as its declared row,
    and no role without patient rows sees a seeded pseudonym."""
    from tests.console import test_matrix_role_walk as mw
    from tools import role_walk as rw

    _flag(box, "on")
    rows = rw.judge_declared(mw.run_walk(box, tmp_path), rw.load_declared())
    assert phone.read_now()[FLAG]
    mw.test_every_console_route_answers_every_column_as_its_declared_row(rows)
    cells = sum(len(r["cells"]) for r in rows)
    print(f"role walk (V-2) with {FLAG} on: {len(rows)} routes, {cells} (column, route) answers judged")


# ------------------------------------------------------------------------------------------- with the other layout flags
OTHERS = ("layout.phone_first", "layout.people_lists", "layout.home_today")


def _set(b: dict[str, Any], name: str, value: str) -> None:
    from console import people_lists

    fl.clear_cache()
    if fl.Flags().row(name) != value:
        fl.Flags(audit=b["audit"]).set(name, value, actor="console:admin", reason="J-7 test (D-1251)")
    fl.clear_cache()
    phone.clear_cache()
    phone.read_now()
    people_lists.clear_cache()
    people_lists.flag_on()


@pytest.mark.parametrize("plain", ["on", "off"])
def test_the_flag_reads_with_the_other_layout_flags_in_every_combination(
    box: dict[str, Any], plain: str, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The three other layout flags change what a phone shows first (D-1222), the lists of people (D-1223) and the
    opening page (D-1225); this one prunes the menu and plain words. For every combination of the three, with this
    flag on and off, every role's opening page and study page answer as before, the menu lists nothing twice and no
    top bar holds more than four entries. With this flag on: no "Overview" and no Admin tab under More, the lists of
    people's entries where people_lists puts them, and the candidate registry under More where the top bar no longer
    links it. With it off: the menu as each other flag makes it (no plain menu)."""
    from console import people_lists

    monkeypatch.setattr(people_lists, "flag_now", people_lists._flag.now)
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    _set(box, FLAG, plain)
    base = {col: {p: clients[col][0].get(p).status_code for p in MENU_PAGES} for col in COLUMNS}
    for n in range(8):
        values = {name: "on" if n >> i & 1 else "off" for i, name in enumerate(OTHERS)}
        for name, value in values.items():
            _set(box, name, value)
        pl = values["layout.people_lists"] == "on"
        for col in COLUMNS:
            page, _, _ = clients[col]
            for p in MENU_PAGES:
                r = page.get(p)
                assert r.status_code < 500, (values, col, p, r.status_code)
                if p == "/home" and values["layout.home_today"] == "off":
                    assert r.status_code == base[col][p], (values, col, p)
                top, under = menu(r.text)
                hrefs = _hrefs(top) + _hrefs(under)
                assert len(top) <= (4 if plain == "on" or col != "steward" else 8), (values, col, top)
                assert ('data-plain="on"' in r.text) == (plain == "on"), (values, col, p)
                if plain == "off":
                    continue
                assert len(set(hrefs)) == len(hrefs), (values, col, p, hrefs)
                assert "/" not in hrefs and not any(h.startswith("/admin?tab=") for h in hrefs), (values, col, p)
                if col in ("crc", "lpi"):
                    assert ("/people/candidates" in _hrefs(top)) == pl, (values, col, p)
                    assert ("/pilot/registry" in _hrefs(under)) == pl, (values, col, p)
    for name in OTHERS:
        _set(box, name, "off")


def test_every_plain_key_exists_in_three_languages_and_the_swap_follows_the_flag_and_the_role(
    box: dict[str, Any],
) -> None:  # the box: the pages that join their own words (the flags page, the SAE pages) are registered
    from console import i18n_plain, plain_menu
    from console.i18n import CATALOGUES

    assert set(i18n_plain.EN) == set(i18n_plain.JA) == set(i18n_plain.ZH)
    for old, new in (*plain_menu.SAME_FOR_ALL.items(), *plain_menu.CLINICAL_ONLY.items()):
        for lang in LANGS:
            assert CATALOGUES[lang].get(old) and CATALOGUES[lang].get(new), (lang, old, new)
    for k in plain_menu.SAME_FOR_ALL:
        assert plain_menu.key(False, "coordinator", k) == k  # off: the key itself, whoever reads
        assert plain_menu.key(True, "admin", k) == plain_menu.SAME_FOR_ALL[k]
    for k in plain_menu.CLINICAL_ONLY:
        for role in ("admin", "steward", "privacy"):  # the setting's name and the data class, kept
            assert plain_menu.key(True, role, k) == k, role
        for role in ("coordinator", "investigator", "viewer", "cro"):
            assert plain_menu.key(True, role, k) == plain_menu.CLINICAL_ONLY[k], role
        assert plain_menu.key(True, None, k) == k  # signed out: as before


#: per column, what each action page offers the account on master (recorded on origin/master 0de6b1d0): its action
#: enabled (True), shown but not offered (False), or the page's refusal (a status). The factoring of the pages' rules
#: into ``may_act`` keeps it so, with the flag off and on.
MASTER_ACTIONS: dict[str, tuple[bool | int, bool | int, bool | int]] = {  # request, case, consent
    "admin": (True, True, True),
    "crc": (True, True, True),
    "pi": (False, False, False),
    "lpi": (True, True, False),
    "smo": (True, True, True),
    "cra": (403, 403, 403),
    "viewer": (False, False, False),
    "steward": (False, False, False),
    "privacy": (False, False, False),
}
ACTION_TARGETS = ("/pilot/request", "/pilot/case", "/pilot/consent")
#: who master's "More" showed each entry to (``templates/_nav.html`` on master, copied: the oracle for the new links)
OLD_MENU: dict[str, Callable[[Any], bool]] = {
    "request": lambda u: bool(u.can_request) or u.role == "investigator",  # T-512
    "consent": lambda u: bool(u.can_request),
    "case": lambda u: not u.aggregate_only,
}


def test_the_action_pages_offer_each_role_what_they_offered_on_master(box: dict[str, Any]) -> None:
    """The coordinator's condition on Q4: factoring the pages' own rules into ``may_act`` changes no page's
    behaviour; each role is offered each action exactly as on master, with the flag off and on. And no new link is
    shown to an account the old menu did not show the entry to (:data:`OLD_MENU`, master's ``_nav.html``)."""
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    for value in ("off", "on"):
        _flag(box, value)
        for col, want in MASTER_ACTIONS.items():
            page, _, _ = clients[col]
            for target, expected in zip(ACTION_TARGETS, want, strict=True):
                r = page.get(target)
                got = _acts(target, r.text) if r.status_code == 200 else r.status_code
                assert got == expected, (value, col, target, got)
    users = box["users"]
    entry = {"/pilot/request": "request", "/pilot/consent": "consent", "/pilot/case": "case"}
    for col, (name, _role, _aff, _studies) in COLUMNS.items():
        page, _, _ = clients[col]
        for where, testid, target in NEW_LINKS:
            r = page.get(where)
            if r.status_code == 200 and f'data-testid="{testid}"' in r.text:
                assert OLD_MENU[entry[target]](users.get(name)), (col, where, target)


def _recorded(calls: list[str], name: str, fn: Any) -> Any:
    def call(*a: Any, **k: Any) -> Any:
        calls.append(name)
        return fn(*a, **k)

    return call


def _backend_calls(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every call a page makes to the console's backend, and every read of an account's standing in a study's
    delegation log (``Helpers.stand``, the store behind ``Helpers.permit``: ``standing``)."""
    calls: list[str] = []
    bk = box["backend"]
    for name in dir(type(bk)):
        attr = getattr(bk, name, None)
        if not name.startswith("_") and callable(attr):
            monkeypatch.setattr(bk, name, _recorded(calls, name, attr))
    h = box["app"].state.helpers
    if h.stand is not None:
        monkeypatch.setattr(h, "stand", _recorded(calls, "standing", h.stand))
    return calls


#: what a page that carries a new link reads more with the flag on, at most: the list of studies' criteria, once
#: (``backend.rulesets``: each ruleset's id, version, status and kind, no patient data; the same list the target page
#: reads for the account) and the account's standing in the delegation log of each approved study it sees
#: (``Helpers.stand``, read once per study and page view), only for an account whose role may start a run in some
#: study (``tb_common.authz.role_allowed``) and that does not prepare requests: the investigator
ADDED_READS = {"rulesets": 1, "standing": 1}  # standing: per approved study the account sees (the fixture has one)


def test_a_page_with_a_new_link_adds_only_the_named_reads(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    import collections

    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)
    calls = _backend_calls(box, monkeypatch)
    pages = sorted({where for where, _, _ in NEW_LINKS})
    seen: dict[str, dict[str, collections.Counter[str]]] = {}
    for value in ("off", "on"):
        _flag(box, value)
        for col in COLUMNS:
            page, _, _ = clients[col]
            for where in pages:
                calls.clear()
                page.get(where)
                seen.setdefault(f"{col} {where}", {})[value] = collections.Counter(calls)
    for k, by in seen.items():
        added = by["on"] - by["off"]
        assert not by["off"] - by["on"], k  # nothing read less
        assert set(added) <= set(ADDED_READS) and all(added[n] <= ADDED_READS[n] for n in added), (k, dict(added))
        if COLUMNS[k.split()[0]][1] != "investigator":  # prepares requests, or may never start a run: no read
            assert not added, (k, dict(added))
    _flag(box, "on")
    for col in COLUMNS:  # the action pages themselves read the list once (master's request page read it twice)
        page, _, _ = clients[col]
        for target in ACTION_TARGETS:
            calls.clear()
            page.get(target)
            assert calls.count("rulesets") <= 1, (col, target, calls.count("rulesets"))


def test_the_list_of_runs_names_every_run_type_in_words_never_by_its_code(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R22: every job type the orchestrator runs (its own registry, not the fixtures) is named in words on the list of
    runs in each language; a type the console does not know is "Other run", never its code."""
    import datetime as dt

    from console import plain_menu
    from console.i18n import CATALOGUES
    from orchestrator.scenarios import registry
    from tb_contracts import Job

    assert set(plain_menu.JOB_TYPES) == set(registry()), "a run type the list of runs would show as a code"
    types = (*plain_menu.JOB_TYPES, "NEWTYPE")
    when = dt.datetime(2026, 1, 5, 9, 0, tzinfo=dt.UTC)
    fields: dict[str, Any] = dict(ruleset=RS, ruleset_version="1.0.0", requested_by="crc@hospa.test",
                                  received_at=when, updated_at=when, state="done", options={}, inputs=[], outputs=[])  # fmt: skip
    jobs = [Job(job_id=_ulid(800 + i), type=cast(Any, t), **fields) for i, t in enumerate(plain_menu.JOB_TYPES)]
    unknown: Any = "NEWTYPE"  # a type the contract may add later
    jobs.append(Job.model_construct(job_id=_ulid(899), type=unknown, **fields))
    monkeypatch.setattr(box["backend"], "list_jobs", lambda **_: jobs)
    _flag(box, "on")
    page, csrf, _ = _clients(box)["crc"]
    for lang in LANGS:
        _lang(page, csrf, lang)
        r = page.get("/jobs")
        assert r.status_code == 200, lang
        cells = re.findall(r"<tr data-job=[^>]*>\s*<td[^>]*>.*?</td>\s*<td>(.*?)</td>", r.text, re.S)
        assert len(cells) == len(types), lang
        for t, cell in zip(types, cells, strict=True):
            word = CATALOGUES[lang][f"pm.jobtype.{plain_menu.job_type_word(t)}"]
            assert html.unescape(cell).strip() == word, (lang, t, cell)
            assert t not in cell, (lang, t, cell)
        assert html.unescape(cells[-1]).strip() == CATALOGUES[lang]["pm.jobtype.other"], lang
    _lang(page, csrf, "en")
    _flag(box, "off")
    assert ">FEAS<" in page.get("/jobs").text  # the flag off: the code, as on master


@pytest.mark.parametrize("broken", ["delegation log", "criteria list"])
def test_a_link_whose_rule_cannot_be_read_is_not_shown_and_the_page_still_renders(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch, broken: str
) -> None:
    """The coordinator's review of J-7: when the delegation store (``Helpers.permit``) or the criteria list
    (``backend.rulesets``) fails, a page that carries a new link answers as it does with the flag off, without the
    link: the flag adds no way for a page to fail."""
    _done_feas(box["backend"])
    _done_screen(box["backend"], _ulid(990))
    clients = _clients(box)

    def down(*_a: Any, **_k: Any) -> Any:
        raise ConnectionError(f"{broken} is down (test)")

    if broken == "delegation log":
        assert box["app"].state.helpers.stand is not None
        monkeypatch.setattr(box["app"].state.helpers, "stand", down)
    else:
        monkeypatch.setattr(box["backend"], "rulesets", down)

    def outcome(page: Any, where: str) -> tuple[int | str, str]:
        try:
            r = page.get(where)
        except ConnectionError:  # the page itself needs the store: it fails with the flag off as well
            return "raised", ""
        return r.status_code, r.text

    checked = 0
    for col in COLUMNS:
        page, _, _ = clients[col]
        for where, testid, _target in NEW_LINKS:
            _flag(box, "off")
            off, _ = outcome(page, where)
            _flag(box, "on")
            on, text = outcome(page, where)
            assert on == off, (broken, col, where, off, on)
            if col in ("pi", "lpi") and on == 200:  # the accounts whose link needs the read
                assert f'data-testid="{testid}"' not in text, (broken, col, where)
                checked += 1
    assert checked, "no page with a link that needs the read was rendered"
    print(f"{broken} down: {checked} investigator pages rendered without the link")
