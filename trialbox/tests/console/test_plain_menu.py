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
    _orchestrator_routes(box)  # the steward's clinical conflicts ask the orchestrator (D-865)
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
                _for(box, href)
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
         "/pilot/consent", "/pilot/case", "/pilot/registry", "/pilot/mailbox", "/settings/notices", "/admin/redcap",
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
#: the test mailbox (a test box's page) and the cascade (shown only where the synthetic site drop is mounted; it is
#: not on the test box, so the administrator's menu leaves it out too: test_the_cascade_is_listed_only_when_mounted)
ADMIN_ONLY = ("/pilot/mailbox", "/pilot/cascade")
NOT_MOUNTED = ("/pilot/cascade",)
#: pages that exist to act (start a request, draft a consent guide, check one patient): linked where the account may
#: act there (``may_act``); an account the page offers nothing (its button disabled) is not sent there
ACTION_PAGES = ("/pilot/request", "/pilot/consent", "/pilot/case")


def _links(html_text: str) -> set[str]:
    return {html.unescape(h) for h in re.findall(r'<a [^>]*href="(/[^"#]*)"', html_text)}


def test_nothing_that_leaves_more_becomes_unreachable(box: dict[str, Any]) -> None:
    """Every entry a role's menu had on master (the flag off) and has no longer (the flag on) is still reached by
    clicks: a link on a page the new menu opens, or one click further (the Admin page's tabs; a study's IRB page from
    the study's menu). The only exceptions: :data:`ADMIN_ONLY`, still in the administrator's menu, and an
    :data:`ACTION_PAGES` page that offers the account nothing to do."""
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
            if href in found or (href in ADMIN_ONLY and col != "admin") or href in NOT_MOUNTED:
                continue
            if href in ACTION_PAGES:  # a page that offers this account nothing to do is not linked (Q4)
                t = page.get(href)
                if t.status_code == 200 and not _acts(href, t.text):
                    continue
            unreached.append(f"{col}: {href}")
        assert all(h in after for h in ADMIN_ONLY if h in before and col == "admin" and h not in NOT_MOUNTED), col
    assert not unreached, "left the menu and no click reaches it:\n" + "\n".join(unreached)


def test_the_cascade_is_listed_only_when_the_site_drop_is_mounted(box: dict[str, Any], tmp_path: Any) -> None:
    """R17 (D-M3): the administrator's menu lists the cascade only where the synthetic site drop is mounted; a menu
    rule only: the page answers the same either way."""
    clients = _clients(box)
    _flag(box, "on")
    admin, _, _ = clients["admin"]
    settings = box["app"].state.settings
    before = admin.get("/pilot/cascade").status_code
    assert "/pilot/cascade" not in _hrefs(menu(admin.get("/home").text)[1])  # not mounted on the test box
    (tmp_path / "patient.csv").write_text("id\n", encoding="utf-8")
    old = settings.source_dir
    object.__setattr__(settings, "source_dir", tmp_path)
    try:
        assert "/pilot/cascade" in _hrefs(menu(admin.get("/home").text)[1])
        for col in COLUMNS:  # never in a clinical or a register role's menu
            if col != "admin":
                page, _, _ = clients[col]
                assert "/pilot/cascade" not in _hrefs(menu(page.get("/home").text)[1]), col
    finally:
        object.__setattr__(settings, "source_dir", old)
    assert admin.get("/pilot/cascade").status_code == before


#: the links that take the place of an entry that left "More" (Q4): (the page, the link's test id, its target)
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
