# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""J-3 (D-1222; the journey review's E-1, E-4, E-M1 to E-M5): the console on a phone.

* the web manifest, the icons and the favicon are served by the box, without a session;
* the flag ``layout.phone_first`` is declared, off by default and described in three languages; with it off the week
  page and the menu are as before (no class, no fold, no group, the mark box before the evidence); with it on the
  week page puts the list first and folds the rest, the rows carry their labels, the sheet shows the evidence before
  the mark fields, and "More" folds in groups that hold exactly the links it held before;
* a link from another site gets the console's own page (``/link``), whose Continue goes only to an HTML page of this
  console: never a file, an export, a print, ``/cmd`` or ``/api/``; the sign-in and its steps arrive as before;
* the flag is read for pages only, off the event loop, and a store that is down costs one attempt per 5 seconds;
* the entry form (an AE's or a visit's) is guarded and kept in the tab; the script puts it back once, with a notice,
  after a save met an ended session, and drops it otherwise (run in Chromium on pages of a small local server).

Synthetic data only. The browser walk of the phone tasks is ``tests/e2e/test_phone_walk.py`` (marked e2e)."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from console import i18n_flags, i18n_phone, phone
from console.i18n import CATALOGUES
from fastapi.testclient import TestClient
from PIL import Image
from tb_common import flags as fl

from tests.console.test_console_app import _done_screen, _ulid, box, login, login_crc, name_pi  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
ICONS = ROOT / "services" / "console" / "static" / "icons"
TEMPLATES = ROOT / "services" / "console" / "templates"
PW = "phone-first-password-0001"
A = "a" * 32
LANGS = ("en", "ja", "zh-TW")


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    fl.clear_cache()
    phone.clear_cache()
    yield
    fl.clear_cache()
    phone.clear_cache()


def _flag(b: dict[str, Any], value: str) -> None:
    """The administrator's change on /ops/flags: audited, with a reason."""
    fl.Flags(audit=b["audit"]).set(phone.FLAG, value, actor="console:admin", reason="J-3 test (D-1222)")
    fl.clear_cache()
    phone.clear_cache()


def _pi(b: dict[str, Any]) -> TestClient:
    _done_screen(b["backend"], _ulid(961))
    b["users"].create("drsato", "investigator", PW, "drsato@hospa.test")
    name_pi(b, "drsato")
    c, _ = login(b["app"], "drsato", PW)
    return c


def _lang(c: TestClient, lang: str) -> None:
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/account").text)
    assert csrf
    c.post("/lang", data={"csrf": csrf.group(1), "lang": lang, "back": "/"})


def _more(page: str) -> str:
    return page.split('<div class="more-items">')[1].split("\n    </details>", maxsplit=1)[0]


# ------------------------------------------------------------------------------------------- E-M1 manifest, icons
def test_the_manifest_and_the_icons_are_the_boxs_own_and_need_no_session(box: dict[str, Any]) -> None:
    c = TestClient(box["app"])  # no session: a browser fetches a manifest without its cookies
    r = c.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = json.loads(r.text)
    assert m["name"] == "TrialBox" and m["start_url"] == "/" and m["display"] == "standalone"
    assert m["theme_color"] == "#253a5e" and "serviceworker" not in r.text.lower()  # no offline, no service worker
    sizes = set()
    for icon in m["icons"]:
        assert icon["src"].startswith("/static/icons/"), icon  # served by the box itself, nothing from outside
        got = c.get(icon["src"])
        assert got.status_code == 200, icon
        if icon["type"] == "image/png":
            w, h = (int(x) for x in icon["sizes"].split("x"))
            with Image.open(ICONS / Path(icon["src"]).name) as im:
                assert im.size == (w, h) and im.format == "PNG"
            sizes.add(w)
    assert {192, 512} <= sizes
    fav = c.get("/favicon.ico")
    assert fav.status_code == 200 and fav.headers["content-type"] == "image/x-icon"
    with Image.open(ICONS / "favicon.ico") as im:
        assert im.format == "ICO"
    page = c.get("/login").text
    for link in ('<link rel="manifest" href="/manifest.webmanifest">', '<meta name="theme-color" content="#253a5e">',
                 'href="/static/icons/apple-touch-icon.png"'):  # fmt: skip
        assert link in page, link


# ------------------------------------------------------------------------------------------- the flag
def test_the_flag_is_declared_off_and_described_in_three_languages(box: dict[str, Any]) -> None:
    d = fl.DECLARED[phone.FLAG]
    assert d.default == "off" and d.values == ("off", "on") and d.seed_env is None
    assert fl.Flags().row(phone.FLAG) == "off" and not phone.flag_on()  # seeded off at create_app
    for cat in (i18n_flags.EN, i18n_flags.JA, i18n_flags.ZH):
        assert cat[f"flags.desc.{phone.FLAG}"]
    assert set(i18n_phone.EN) == set(i18n_phone.JA) == set(i18n_phone.ZH)
    for lang in LANGS:
        assert all(CATALOGUES[lang][k] for k in i18n_phone.EN)


def test_with_the_flag_off_the_week_page_and_the_menu_are_as_before(box: dict[str, Any]) -> None:
    pi = _pi(box)
    page = pi.get(f"/studies/GZQO/week?pid={A}").text
    assert "<body>" in page and "phone-first" not in page
    for new in ("pfweek", "fold-toggle", "pf-fold", "data-label=", "moregrp", "more-grp-"):
        assert new not in page, new
    chart = page.split('data-testid="chart"')[1]
    assert (
        chart.index('data-testid="ask-doctor"')
        < chart.index('data-testid="actions"')
        < chart.index('data-testid="markbar"')
    )
    crc, _ = login_crc(box)
    more = _more(crc.get("/studies/GZQO/week").text)
    assert "<details" not in more and 'data-testid="more-setup"' in more  # one flat list, the study's links in it


def test_with_the_flag_on_the_phone_sees_the_list_first_and_the_same_links(box: dict[str, Any]) -> None:
    pi = _pi(box)
    crc, _ = login_crc(box)
    before = _more(crc.get("/studies/GZQO/week").text)
    _flag(box, "on")
    for lang in LANGS:
        _lang(pi, lang)
        page = pi.get(f"/studies/GZQO/week?pid={A}").text
        assert '<body class="phone-first">' in page
        week = page.split('data-testid="phone-first"')[1]
        assert (
            week.index('class="headrow"')
            < week.index('data-testid="workbench"')
            < week.index('data-testid="study-fold"')
        )
        assert re.search(r'data-testid="study-bits">.*?<p class="hint" data-testid="team-nav">', week, re.S)  # folded
        assert f'data-label="{html.escape(CATALOGUES[lang]["wb.c.visit"])}"' in week
        chart = page.split('data-testid="chart"')[1]
        assert (
            chart.index('data-testid="actions"')
            < chart.index('data-testid="full-chart"')
            < chart.index('data-testid="markbar"')
        )
    _lang(crc, "en")
    after = _more(crc.get("/studies/GZQO/week").text)
    assert 'data-testid="more-grp-study"' in after and "GZQO · study pages" in after
    hrefs = re.compile(r'<a href="([^"]+)"')
    assert sorted(hrefs.findall(after)) == sorted(hrefs.findall(before))  # folded, nothing added or lost
    _flag(box, "off")
    assert "<body>" in pi.get(f"/studies/GZQO/week?pid={A}").text  # off again: as before, without a restart


def test_with_the_flag_on_the_investigator_reads_the_evidence_before_the_mark_fields() -> None:
    """E-M5: on the week page's sheet and on the full patient page the mark's note and reason come after the criteria
    (the e2e walk checks the rendered order on the seeded data); off, the mark box stays where it was."""
    week = (TEMPLATES / "week.html").read_text(encoding="utf-8")
    off, crits = week.index("{% if not (pf and user.can_mark) %}{{ markpart }}"), week.index('<h3 class="grp">')
    assert off < crits < week.index('{% if pf and user.can_mark %}{{ markpart }}{% endif %}<p class="chartlinks">')
    patient = (TEMPLATES / "patient.html").read_text(encoding="utf-8")
    off, crits = patient.index("{% if not pf %}{{ markpart }}"), patient.index('{% include "_criteria.html" %}')
    assert off < crits < patient.index("{% if pf %}{{ markpart }}")


def test_with_the_flag_on_the_participants_tables_are_cards() -> None:
    """The participant's page: its visits and its step trail are cards under 640 px with the flag on (each cell
    labelled); off, the class and the labels are not written (the e2e walk checks the rendered cards)."""
    tpl = (TEMPLATES / "life_subject.html").read_text(encoding="utf-8")
    assert tpl.count("<table class=\"candidates{{ ' pf-cards' if pf else '' }}\">") == 2
    for col in ("visit", "status", "window", "day", "step", "who", "source", "note"):
        assert f"{{% if pf %}} data-label=\"{{{{ t('life.col.{col}') }}}}\"{{% endif %}}" in tpl, col
    css = (ROOT / "services" / "console" / "static" / "console.css").read_text(encoding="utf-8")
    assert "body.phone-first table.pf-cards thead { display: none; }" in css


def test_with_the_flag_on_the_study_fold_comes_after_the_list_and_counts_what_needs_the_person(
    box: dict[str, Any],
) -> None:
    """The order of the page is the order of the screen: the fold's toggle, label and content are written after the
    workbench; the label says how many of its lines need the person (a waiting approval, the delegation-log check)."""
    pi = _pi(box)
    _flag(box, "on")
    for lang in LANGS:
        _lang(pi, lang)
        week = pi.get(f"/studies/GZQO/week?pid={A}").text.split('data-testid="phone-first"')[1]
        bench, label = week.index('data-testid="workbench"'), week.index('data-testid="study-fold"')
        assert week.index('class="headrow"') < bench < week.index('id="study-fold"') < label
        bits = week[week.index('data-testid="study-bits"') :]
        assert 'data-testid="team-nav"' in bits and label < week.index('data-testid="study-bits"')
        n = bits.count('data-testid="approval-waiting"') + bits.count('data-testid="team-due"')
        text = week[label:].split(">", 1)[1].split("</label>", 1)[0]
        if n:
            assert (
                'class="fold-button attn"' in week
                and html.escape(CATALOGUES[lang]["pf.study.attn"].format(n=n)) in text
            )
        else:
            assert text == html.escape(CATALOGUES[lang]["pf.study"])
    tpl = (TEMPLATES / "week.html").read_text(encoding="utf-8")
    assert "{% set attn = (approvals or [])|length + (1 if team_due else 0) %}" in tpl
    for lang in LANGS:  # a whole sentence with its number, in each language
        assert "{n}" in CATALOGUES[lang]["pf.study.attn"]


def test_the_menu_groups_open_in_every_browser() -> None:
    """E-M4: no summary is made unclickable; showing the groups open on a desktop is only where the browser knows
    ::details-content (an enhancement inside @supports)."""
    css = re.sub(
        r"/\*.*?\*/", "", (ROOT / "services" / "console" / "static" / "console.css").read_text("utf-8"), flags=re.S
    )
    assert "pointer-events: none" not in css.split("J-3 (D-1222)")[-1] and "pointer-events:none" not in css
    before, _, inside = css.partition("@supports selector(::details-content)")
    assert inside and "::details-content" not in before  # the open look only where the browser knows it


# ------------------------------------------------------------------------------------------- E-M2 a link from elsewhere
CROSS = {"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate", "sec-fetch-dest": "document"}


@pytest.mark.parametrize(
    ("asked", "goes"),
    [
        ("/studies/GZQO/week?list=all", "/studies/GZQO/week?list=all"),
        ("/studies/GZQO/subjects/GZQO-0001", "/studies/GZQO/subjects/GZQO-0001"),
        ("/studies/GZQO/screening-log.xlsx", "/home"),
        ("/pilot/registry/GZQO/export.xlsx", "/home"),
        ("/audit/patients/" + A + "/report.csv", "/home"),
        ("/studies/GZQO/export.csv", "/home"),
        ("/pilot/jobs/01J0/files/list.json", "/home"),
        ("/pilot/jobs/01J0/sponsor-pack.zip", "/home"),
        ("/studies/GZQO/referrals/1/print", "/home"),
        ("/cmd?q=GZQO-0001", "/home"),
        ("/api/v1/studies", "/home"),
        ("//evil.example/x", "/home"),
        ("http://evil.example/x", "/home"),
        ("/login", "/home"),
    ],
)
def test_continue_goes_only_to_a_page_of_this_console(asked: str, goes: str) -> None:
    assert phone.continue_to(asked) == goes


def test_a_link_from_another_site_gets_the_consoles_own_page_and_never_a_file(box: dict[str, Any]) -> None:
    c, _ = login(box["app"])  # a live session: its cookie is in the jar, as a browser would hold it
    for asked, goes in (("/studies/GZQO/week", "/studies/GZQO/week"), ("/studies/GZQO/screening-log.xlsx", "/home"),
                        ("/feedback/export.csv", "/home"), ("/cmd?q=x", "/home")):  # fmt: skip
        r = c.get(asked, headers=CROSS, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/link?to="), (
            asked
        )  # nothing read, nothing sent
        page = c.get(r.headers["location"], headers=CROSS)
        assert page.status_code == 200 and 'data-testid="link-page"' in page.text
        assert f'href="{html.escape(goes)}" data-testid="link-continue"' in page.text, (asked, page.text[-800:])
        assert ('data-testid="link-file"' in page.text) == (goes == "/home")
    assert (
        c.get(
            "/studies/GZQO/week", headers={**CROSS, "sec-fetch-site": "same-origin"}, follow_redirects=False
        ).status_code
        != 303
    )
    for arrival in (
        "/login",
        "/enrol",
        "/auth/oidc/callback",
        "/static/console.css",
        "/manifest.webmanifest",
        "/healthz",
    ):
        r = c.get(arrival, headers=CROSS, follow_redirects=False)
        assert not r.headers.get("location", "").startswith("/link"), arrival  # the sign-in and its steps as before
    r = c.post("/lang", data={"csrf": "x"}, headers=CROSS, follow_redirects=False)
    assert not r.headers.get("location", "").startswith("/link")  # a form post is not a link


def test_the_link_page_in_three_languages(box: dict[str, Any]) -> None:
    c = TestClient(box["app"])
    for lang, accept in (("en", "en"), ("ja", "ja"), ("zh-TW", "zh-TW,zh;q=0.9")):
        page = c.get("/link?to=%2Fstudies%2FGZQO%2Fweek", headers={"accept-language": accept}).text
        assert f'<html lang="{lang}">' in page
        for key in ("link.title", "link.why", "link.continue"):
            assert html.escape(CATALOGUES[lang][key]) in page, (lang, key)
        assert html.escape(CATALOGUES[lang]["link.lead"].format(page="/studies/GZQO/week")) in page


# ------------------------------------------------------------------------------------------- the flag's read
def test_a_flag_store_that_is_down_costs_one_attempt_per_five_seconds(box: dict[str, Any], monkeypatch: Any) -> None:
    tries: list[float] = []
    now = [1000.0]

    def down() -> bool:
        tries.append(now[0])
        raise ConnectionError("the flag store is down")

    monkeypatch.setattr(phone, "_read", down)
    monkeypatch.setattr(phone, "_clock", lambda: now[0])
    phone.clear_cache()
    pi = _pi(box)
    for _ in range(3):
        r = pi.get("/home")
        assert r.status_code == 200 and "<body>" in r.text  # pages render, the flag reads off
    for path in ("/static/console.css", "/manifest.webmanifest", "/favicon.ico", "/healthz", "/link"):
        pi.get(path)
    assert len(tries) == 1, tries  # pages only, once
    now[0] += phone.FLAG_SECONDS + 0.1
    pi.get("/home")
    assert len(tries) == 2


# ------------------------------------------------------------------------------------------- E-M3 long forms
def test_the_entry_form_is_guarded_and_kept_per_account_and_record() -> None:
    tpl = (TEMPLATES / "data_entry.html").read_text(encoding="utf-8")
    form = tpl.split('<form method="post" action="/studies/{{ rs }}/entry" id="entry"')[1].split(">")[0]
    assert "data-guard" in form
    assert 'data-keep="{{ user.username }}|{{ rs }}|{{ record }}|{{ event }}|{{ form.name }}"' in form
    assert "data-keep-msg=\"{{ t('form.restored', n='{n}') }}\"" in form
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert '{% if user %}<meta name="tb-user" content="{{ user.username }}">{% endif %}' in base


def _node_playwright() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "-e", "require('playwright')"], cwd=ROOT, capture_output=True, timeout=60, check=False)
    return r.returncode == 0


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
def test_a_kept_form_comes_back_once_with_a_notice_and_is_dropped_otherwise() -> None:
    """The console's script in Chromium, on pages a small local server makes (tests/console/form_keep.js)."""
    out = subprocess.run([shutil.which("node") or "node", str(Path(__file__).with_name("form_keep.js"))], cwd=ROOT,
                         capture_output=True, text=True, timeout=300, check=True)  # fmt: skip
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert not [k for k, v in got.items() if "error" in v], got
    once = got["restored_once_with_a_notice"]  # Save met the ended session: after sign-in, back on the form
    assert once["url"].startswith("/studies/GZQO/entry?record=S-1&event=ae1&form=tb_adverse_event")
    assert once["term"] == "gout flare, knee" and once["serious"] is True and once["marked"] == 2
    assert once["notice"].strip() == "Fields restored: 2."
    assert once["later"] == "" and once["laterNotice"] == 0  # never again on a later visit
    assert got["discard"] == {"term": "", "notice": 0, "keys": []}
    assert got["another_account_signs_in"] == {"url": "/home", "keys": []}  # never to account A's form, A's dropped
    assert got["saved_with_a_live_session"]["keys"] == []
    assert got["saved_and_shown_again"] == {"keys": [], "term": "as saved", "notice": 0}
    assert got["left_on_purpose"]["typed"] and got["left_on_purpose"]["after"] == []
    assert got["older_than_12_hours"]["keys"] == []
    assert got["the_address_carries_the_form"]["sent"].startswith(
        "/studies/GZQO/entry?record=S-1&event=ae1&form=tb_adverse_event"
    )
