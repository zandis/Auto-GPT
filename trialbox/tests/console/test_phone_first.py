# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""J-3 (D-1222; the journey review's E-1, E-4, E-M1 to E-M5): the console on a phone.

* the web manifest, the icons and the favicon are served by the box, without a session;
* the flag ``layout.phone_first`` is declared, off by default and described in three languages; with it off the week
  page and the menu are as before (no class, no fold, no group, the mark box before the evidence); with it on the
  week page puts the list first and folds the rest, the rows carry their labels, the sheet shows the evidence before
  the mark fields, and "More" folds in groups that hold exactly the links it held before;
* the sign-in page's same-site hop for a link from another site: one hop (no loop), a live session goes on to the
  kept page, and only to a same-origin path;
* the entry form (an AE's or a visit's) is guarded and kept in the tab, and the script restores and drops it (run
  in Node).

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
from tests.console.test_mark_bar_in_view_and_expiry_keeps_the_note import NEXT

ROOT = Path(__file__).resolve().parents[2]
ICONS = ROOT / "services" / "console" / "static" / "icons"
TEMPLATES = ROOT / "services" / "console" / "templates"
PW = "phone-first-password-0001"
A = "a" * 32
LANGS = ("en", "ja", "zh-TW")


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    fl.clear_cache()
    yield
    fl.clear_cache()


def _flag(b: dict[str, Any], value: str) -> None:
    """The administrator's change on /ops/flags: audited, with a reason."""
    fl.Flags(audit=b["audit"]).set(phone.FLAG, value, actor="console:admin", reason="J-3 test (D-1222)")
    fl.clear_cache()


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
        assert html.escape(CATALOGUES[lang]["pf.study"]) in page.split('data-testid="study-fold"')[1][:200]
        week = page.split('data-testid="phone-first"')[1]
        assert (
            week.index('class="headrow"')
            < week.index('data-testid="study-fold"')
            < week.index('data-testid="workbench"')
        )
        assert re.search(r'class="pf-fold">\s*<p class="hint" data-testid="team-nav">', week)  # the links fold
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


# ------------------------------------------------------------------------------------------- E-M2 the hop
def test_a_link_from_another_site_hops_once_on_the_same_site(box: dict[str, Any]) -> None:
    c = TestClient(box["app"])
    cross = {"sec-fetch-site": "cross-site"}
    page = c.get("/login", headers=cross).text
    assert '<meta http-equiv="refresh" content="0;url=/login?hop=1">' in page
    assert "http-equiv" not in c.get("/login").text  # typed or same-site: no hop
    assert "http-equiv" not in c.get("/login?hop=1", headers=cross).text  # one hop only: never a loop
    assert (
        'http-equiv="refresh" content="0;url=/login?hop=1&amp;lang=ja"' in c.get("/login?lang=ja", headers=cross).text
    )
    r = c.get("/login?hop=1", follow_redirects=False)
    assert r.status_code == 200 and 'action="/login"' in r.text  # no session: the sign-in form


@pytest.mark.parametrize(("kept", "lands"), [("/studies/GZQO/week?list=all", "/studies/GZQO/week?list=all"),
                                             ("//evil.example/x", "/home"), ("http://evil.example/x", "/home"),
                                             ("/login", "/home")])  # fmt: skip
def test_a_live_session_goes_on_to_the_kept_page_and_only_to_this_console(box: dict[str, Any], kept: str,
                                                                          lands: str) -> None:  # fmt: skip
    c, _ = login(box["app"])
    c.cookies.set(NEXT, kept, domain="testserver.local")
    r = c.get("/login?hop=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == lands
    assert not (c.cookies.get(NEXT) or "").strip('"')  # used once


# ------------------------------------------------------------------------------------------- E-M3 long forms
def test_the_entry_form_is_guarded_and_kept_per_account_and_record() -> None:
    tpl = (TEMPLATES / "data_entry.html").read_text(encoding="utf-8")
    form = tpl.split('<form method="post" action="/studies/{{ rs }}/entry" id="entry"')[1].split(">")[0]
    assert "data-guard" in form
    assert 'data-keep="{{ user.username }}|{{ rs }}|{{ record }}|{{ event }}|{{ form.name }}"' in form


RUN_JS = """
const [src, stored, signIn, typed, noForm, path] = process.argv.slice(1);
const store = JSON.parse(stored);
global.sessionStorage = {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; }, get length() { return Object.keys(store).length; },
  key: (i) => Object.keys(store)[i]};
const on = {};
let replaced = null;
const el = (name, type, value, checked) => ({name, type, value, checked, disabled: false});
const fields = [el("f_ae_term", "text", "", false), el("f_ae_serious", "radio", "1", false),
                el("f_ae_serious", "radio", "0", false), el("csrf", "hidden", "x", false)];
const form = {elements: fields, getAttribute: (a) => (a === "data-keep" ? "crc|GZQO|S-1|ae_1|tb_adverse_event" : null),
  hasAttribute: (a) => a === "data-guard", addEventListener: (ev, fn) => { (on[ev] = on[ev] || []).push(fn); }};
const pages = noForm === "1" ? {} : {"form[data-keep]": [form], "form[data-guard]": [form]};
global.navigator = {};
global.window = {location: {hash: "", pathname: path, search: noForm === "1" ? "" : "?record=S-1",
  replace: (u) => { replaced = u; }}, history: {length: 1}, addEventListener: () => {}};
global.document = {getElementById: () => null,
  querySelector: (q) => (q === "form[action^='/login']" && signIn === "1" ? {} : null),
  querySelectorAll: (q) => pages[q] || []};
eval(src);
if (typed) { fields[0].value = typed; fields[1].checked = true; (on.input || []).forEach((f) => f()); }
if (typed === "send") (on.submit || []).forEach((f) => f());
console.log(JSON.stringify({term: fields[0].value, serious: fields[1].checked, store, replaced}));
"""
FORM_AT = "/studies/GZQO/entry"


def _run(store: dict[str, str], sign_in: bool = False, typed: str = "", path: str = FORM_AT) -> dict[str, Any]:
    from console.app import CONSOLE_JS

    node = shutil.which("node")
    assert node, "node runs the console's script in the tests"
    no_form = "0" if path == FORM_AT else "1"
    out = subprocess.run([node, "-e", RUN_JS, CONSOLE_JS, json.dumps(store), "1" if sign_in else "0", typed, no_form,
                          path], capture_output=True, text=True, timeout=30, check=True)  # fmt: skip
    got: dict[str, Any] = json.loads(out.stdout.strip().splitlines()[-1])
    return got


def test_the_script_keeps_restores_and_drops_a_long_form() -> None:
    key = "tb-form:crc|GZQO|S-1|ae_1|tb_adverse_event"
    kept = json.dumps({"f_ae_term": "gout flare, knee", "f_ae_serious": ["1"]})
    got = _run({}, typed="gout flare")
    assert json.loads(got["store"][key]) == {"f_ae_term": "gout flare", "f_ae_serious": ["1"]}  # kept while typed
    assert "csrf" not in got["store"][key]  # never the hidden fields
    got = _run({key: kept})
    assert got["term"] == "gout flare, knee" and got["serious"] is True  # back on the form after sign-in
    sent = _run({}, typed="send")["store"]  # Save tapped: the form's own address goes with it
    assert sent["tb-form-sent"] == key.removeprefix("tb-form:") and sent["tb-form-sent-at"] == FORM_AT + "?record=S-1"
    # the session had ended: the save met the sign-in page; after sign-in the home page sends the tab back to the form
    met = _run(dict(sent), sign_in=True, path="/login")["store"]
    assert met[key] and met["tb-form-via-sign-in"] == "1"
    got = _run(dict(met), path="/home")
    assert got["replaced"] == FORM_AT + "?record=S-1" and set(got["store"]) == {key}
    assert _run(dict(met), path="/studies/GZQO/week")["replaced"] is None  # a kept page wins; the form stays kept
    # the session was live: the save went through, the next page is another one: dropped, nowhere to go back to
    got = _run(dict(sent), path="/studies/GZQO/history")
    assert got["store"] == {} and got["replaced"] is None
    assert set(_run(dict(sent))["store"]) == {key}  # the same form again (a refusal): kept, no longer "sent"
