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
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
    phone.flag_on()  # read now: a page gets the value last read


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
        n += 1 if 'data-testid="steps"' in bits and 'data-testid="steps-fold"' not in bits else 0  # set-up not done
        text = week[label:].split(">", 1)[1].split("</label>", 1)[0]
        if n:
            assert (
                'class="fold-button attn"' in week
                and html.escape(CATALOGUES[lang]["pf.study.attn"].format(n=n)) in text
            )
        else:
            assert text == html.escape(CATALOGUES[lang]["pf.study"])
    tpl = (TEMPLATES / "week.html").read_text(encoding="utf-8")
    assert "{% set attn = (approvals or [])|length + (1 if team_due else 0) + (1 if step < 2 else 0) %}" in tpl
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
WEEK = "/studies/GZQO/week"


@pytest.mark.parametrize(
    ("asked", "goes"),
    [
        # the pages the box's own mails link to, and the everyday pages: rebuilt, with only their own parameters
        ("/studies/GZQO/week?list=clinic", "/studies/GZQO/week?list=clinic"),
        (f"/studies/GZQO/week?list=all&pid={A}&page=2&code=x", f"/studies/GZQO/week?list=all&pid={A}"),
        ("/studies/GZQO/week?list=evil", WEEK),
        ("/studies/GZQO/week?pid=../../x", WEEK),
        ("/studies/GZQO/subjects", "/studies/GZQO/subjects"),
        ("/studies/GZQO/subjects/GZQO-0001", "/studies/GZQO/subjects/GZQO-0001"),
        ("/studies/GZQO/subjects/GZQO-0001#u=x", "/home"),
        ("/home", "/home"),
        ("/", "/"),
        ("/week", "/week"),
        ("/sae", "/sae"),
        ("/settings/notices", "/settings/notices"),
        ("/account", "/account"),
        ("/help?back=/x", "/help"),
        ("/studies/gzqo/week", "/home"),  # a study id is upper case
        # the review's probes: disguised addresses, encodings, files, actions
        ("/\t/evil.com/x", "/home"),
        ("/\t/3232235777", "/home"),
        ("/\n/evil.com/x", "/home"),
        ("/\r/evil.com/x", "/home"),
        ("/\x00/evil.com/x", "/home"),
        ("/%2F/evil.com/x", "/home"),
        ("/%09/evil.example/x", "/home"),
        ("/%2509/evil.example/x", "/home"),
        ("//evil.example/x", "/home"),
        ("http://evil.example/x", "/home"),
        ("/\\evil.example/x", "/home"),
        ("/home\u202egnp.exe", "/home"),
        ("/home\u200b", "/home"),
        ("/home\u2028", "/home"),
        ("/pilot/jobs/1/%66iles/report%2Ecsv", "/home"),
        ("/pilot/jobs/1/sponsor-pack%2Ezip", "/home"),
        ("/pilot/registry/R1/export%2Exlsx", "/home"),
        ("/audit/patients/p1/report%2Ecsv", "/home"),
        ("/studies/R/screening-log%2Exlsx", "/home"),
        ("/studies/R/enrolment%2Ecsv", "/home"),
        ("/ask?q=list+all+patients", "/home"),
        (f"/ask?q=x&pid={A}", "/home"),
        ("/studies/R/edc/sign/oidc/T?reauth=x", "/home"),
        ("/javascript:alert(1)", "/home"),
        ("/studies/R/export.xlsx/", "/home"),
        ("/feedback/export%2Ecsv", "/home"),
        ("/studies/R/edc/export%2Eodm%2Exml", "/home"),
        ("/about/NOTICE%2Etxt", "/home"),
        ("/site/templates/a%2Exlsx", "/home"),
        ("/pilot/cascade/1/%66iles/a", "/home"),
        ("/pilot/jobs/1/%76iew/a", "/home"),
        ("/studies/R/referrals/1/%70rint", "/home"),
        ("/cmd%3Fq", "/home"),
        ("/%63md?q=x", "/home"),
        ("/cmd?q=GZQO-0001", "/home"),
        ("/API/v1/x", "/home"),
        ("/Api/v1/x", "/home"),
        ("/studies/R/patients/p1", "/home"),
        ("/login", "/home"),
        ("", "/home"),
    ],
)
def test_continue_opens_only_a_listed_page(asked: str, goes: str) -> None:
    assert phone.continue_to(asked) == goes
    assert phone.continue_to(quote(asked, safe="/?&=")) in (goes, "/home")  # encoded once more: never anything else


ALLOWED_ROUTES = {"/", "/home", "/week", "/studies/{rs}/week", "/studies/{rs}/subjects",
                  "/studies/{rs}/subjects/{record}", "/sae", "/settings/notices", "/account", "/help"}  # fmt: skip


def test_every_other_route_of_the_console_goes_home(box: dict[str, Any]) -> None:
    """From the app's route table: a route not on the allow-list (a file, an export, an action, any page) opens the
    home page, so a new export route is safe by default; every listed page is a real route."""
    from fastapi.routing import APIRoute

    sample = {"rs": "GZQO", "ruleset": "GZQO", "pid": A, "record": "GZQO-0001"}
    seen = set()
    for r in box["app"].routes:
        if not isinstance(r, APIRoute) or "GET" not in (r.methods or set()):
            continue
        path = re.sub(r"{(\w+)(?::\w+)?}", lambda m: sample.get(m.group(1), "x1"), r.path)
        got = phone.continue_to(path)
        if r.path in ALLOWED_ROUTES:
            seen.add(r.path)
            assert got.split("?")[0] == path, (r.path, got)
        else:
            assert got == "/home", (r.path, got)
    assert seen == ALLOWED_ROUTES - {"/"} or seen == ALLOWED_ROUTES, ALLOWED_ROUTES - seen


def test_a_link_from_another_site_gets_the_consoles_own_page_with_its_headers(box: dict[str, Any]) -> None:
    c, _ = login(box["app"])  # a live session: its cookie is in the jar, as a browser would hold it
    for asked, goes in (("/studies/GZQO/week?list=clinic", "/studies/GZQO/week?list=clinic"),
                        ("/studies/GZQO/screening-log.xlsx", "/home"), ("/feedback/export.csv", "/home"),
                        ("/cmd?q=x", "/home"), ("/pilot/jobs/1/sponsor-pack%2Ezip", "/home")):  # fmt: skip
        r = c.get(asked, headers=CROSS, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/link?to="), (
            asked
        )  # nothing read, nothing sent
        for h in ("content-security-policy", "x-frame-options", "referrer-policy"):
            assert r.headers.get(h), (asked, h)  # the console's own headers on the 303 too
        assert r.headers["cache-control"] == "no-store"
        page = c.get(r.headers["location"], headers=CROSS)
        assert page.status_code == 200 and 'data-testid="link-page"' in page.text
        assert page.headers.get("content-security-policy") and page.headers["cache-control"] == "no-store"
        assert f'href="{html.escape(goes)}" data-testid="link-continue"' in page.text, (asked, page.text[-800:])
        assert ('data-testid="link-other"' in page.text) == (goes == "/home")
    same = c.get("/studies/GZQO/week", headers={**CROSS, "sec-fetch-site": "same-origin"}, follow_redirects=False)
    assert same.status_code != 303  # from this site: the page itself (here refused to the administrator)
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


@pytest.mark.parametrize(
    "to",
    ["/\t/evil.com/x", "/Your account is locked. Call IT on 555-0100 now", "/home\u202e/stnemyap", '/a"><script>',
     "/x?a=1&code=SECRET", "/pilot/jobs/1/sponsor-pack%2Ezip"],
)  # fmt: skip
def test_the_link_page_shows_no_text_from_the_link(box: dict[str, Any], to: str) -> None:
    page = TestClient(box["app"]).get("/link?to=" + quote(to, safe=""), headers={"accept-language": "en"}).text
    assert 'href="/home" data-testid="link-continue"' in page
    assert html.escape(CATALOGUES["en"]["link.other"]) in page and 'data-testid="link-asked"' not in page
    for bit in ("evil", "555-0100", "stnemyap", "<script>", "SECRET", "sponsor"):
        assert bit not in page, bit


def test_the_link_page_names_the_page_in_three_languages(box: dict[str, Any]) -> None:
    c = TestClient(box["app"])
    for lang, accept in (("en", "en"), ("ja", "ja"), ("zh-TW", "zh-TW,zh;q=0.9")):
        page = c.get(
            "/link?to=" + quote("/studies/GZQO/week?list=clinic", safe=""), headers={"accept-language": accept}
        ).text
        assert f'<html lang="{lang}">' in page
        for key in ("link.title", "link.why", "link.continue"):
            assert html.escape(CATALOGUES[lang][key]) in page, (lang, key)
        name = CATALOGUES[lang]["link.page.week"].format(rs="GZQO")
        assert CATALOGUES[lang]["link.lead"].format(page=name) in html.unescape(page)
        assert "/studies/GZQO/week</" not in page and "list=clinic</" not in page  # the name, not the address
    assert set(phone.ALLOWED[i].name for i in range(len(phone.ALLOWED))) <= set(i18n_phone.EN)


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
        time.sleep(0.05)
    for path in ("/static/console.css", "/manifest.webmanifest", "/favicon.ico", "/healthz", "/link"):
        pi.get(path)
    assert len(tries) == 1, tries  # pages only, one read
    now[0] += phone.FLAG_SECONDS + 0.1
    pi.get("/home")
    time.sleep(0.05)
    assert len(tries) == 2


def test_a_hanging_flag_store_delays_no_page(box: dict[str, Any], monkeypatch: Any) -> None:
    """A read that blocks 5 s (a connect that hangs): 20 pages at once all answer at once, one read runs."""
    tries: list[int] = []

    def hangs() -> bool:
        tries.append(1)
        time.sleep(5)
        return True

    monkeypatch.setattr(phone, "_read", hangs)
    phone.clear_cache()
    pi = _pi(box)
    took: list[float] = []

    def one() -> None:
        t0 = time.monotonic()
        assert pi.get("/home").status_code == 200
        took.append(time.monotonic() - t0)

    workers = [threading.Thread(target=one) for _ in range(20)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert len(took) == 20 and max(took) < 3, sorted(took)[-3:]
    assert len(tries) == 1, tries


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
