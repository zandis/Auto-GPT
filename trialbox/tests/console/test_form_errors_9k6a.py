"""9k-6a (D-1376, review 09 DS-6, A11Y-4): a failed POST of a form converted to the field macro, in en, ja and zh-TW.

For each case of ``tests/console/form_cases_9k6a.py`` (the study's identifiers, the study's IRB record), drawn by the
in-process box:

* the page before any POST has no summary and no "Error:" in its title;
* a POST with wrong values answers 400 (as before) with the summary at the top: ``role="alert"``, focusable and
  focused on load, its heading, one link per failing field in the form's order, each to an existing field id; the
  title begins with "Error:"; each failing field has ``aria-invalid`` and an ``aria-describedby`` whose every id
  exists and names the field's own message, in the same words as its link; nothing is saved (no audit event);
* what was typed comes back; a password or a one-time code posted with it never does;
* a POST without the right CSRF token is still refused and saves nothing; a right POST saves as before (303 to
  the same address, the same audit event).

The keyboard order (focus on the summary when the page loads, Tab to its first link, Enter moves focus to the field)
is measured in Chromium through Node Playwright (``tests/console/form_errors_keys_9k6a.js``), skipped where it is
missing, as ``test_cjk_layout``. Synthetic data only.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from console.i18n import CATALOGUES

from tests.console.form_cases_9k6a import CASES, Case
from tests.console.test_cjk_layout import _node_playwright
from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - box is a fixture
from tests.console.test_role_pages import PW, _csrf, _user

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("form_errors_keys_9k6a.js")
LANGS = ("en", "ja", "zh-TW")
SECRETS = {"password": "pw-synthetic-9k6a-0001", "otp": "918273", "enrol_code": "code-synthetic-9k6a"}


class _Elements(HTMLParser):
    """Every start tag with its attributes, in order; ``ids`` by id."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.ids: dict[str, tuple[str, dict[str, str]]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v if v is not None else "" for k, v in attrs}
        self.tags.append((tag, a))
        if "id" in a:
            assert a["id"] not in self.ids, f"id {a['id']} twice"
            self.ids[a["id"]] = (tag, a)


def _parse(text: str) -> _Elements:
    p = _Elements()
    p.feed(text)
    return p


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def _client(b: dict[str, Any], case: Case, lang: str) -> Any:
    """The case's user signed in, the page language ``lang`` (the PI named once, through the steward's log)."""
    user, role = ("drsato", "investigator") if case.role == "pi" else ("crc1", "coordinator")
    if b["users"].get(user) is None:
        c = _user(b, user, role)
        if case.role == "pi":
            name_pi(b, user)
    else:
        c, _ = login(b["app"], user, PW)
    r = c.post("/lang", data={"csrf": _csrf(c.get("/").text), "lang": lang, "back": "/"}, follow_redirects=False)
    assert r.status_code == 303
    return c


def _summary(text: str) -> tuple[str, list[tuple[str, str]]] | None:
    """The summary's heading and its (href, words) links, or None."""
    m = re.search(r'<div class="fm-summary"[^>]*>(.*?)</div>', text, re.S)
    if not m:
        return None
    head = re.search(r"<h2[^>]*>(.*?)</h2>", m.group(1), re.S)
    links = re.findall(r'<a href="([^"]*)"[^>]*>(.*?)</a>', m.group(1), re.S)
    return html.unescape(head.group(1) if head else ""), [(h, html.unescape(w)) for h, w in links]


def _message(text: str, fid: str) -> str:
    m = re.search(rf'<p class="fm-err" id="{re.escape(fid)}-err"><span class="sr">[^<]*</span> (.*?)</p>', text, re.S)
    assert m, fid
    return html.unescape(m.group(1))


def _title(text: str) -> str:
    m = re.search(r"<title>(.*?)</title>", text, re.S)
    assert m
    return html.unescape(m.group(1))


def _error_word(lang: str) -> str:
    """ "Error: " as the page's title starts with it in ``lang``."""
    return CATALOGUES[lang]["fe.title"].split("{title}")[0]


def _failed(b: dict[str, Any], name: str, lang: str) -> tuple[Any, Any, str]:
    case = CASES[name]
    c = _client(b, case, lang)
    page = c.get(case.page)
    assert page.status_code == 200 and _summary(page.text) is None
    assert not _title(page.text).startswith(_error_word(lang))
    r = c.post(case.action, data={"csrf": _csrf(page.text), **case.bad, **SECRETS}, follow_redirects=False)
    return c, r, _csrf(page.text)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("name", sorted(CASES))
def test_a_failed_post_shows_the_summary_tied_to_each_field(box: dict[str, Any], name: str, lang: str) -> None:  # noqa: F811
    case, cat = CASES[name], CATALOGUES[lang]
    _c, r, _ = _failed(box, name, lang)
    assert r.status_code == 400, r.text[-500:]
    assert f'data-testid="{case.testid}"' in r.text  # the testid the form's earlier tests read
    assert _title(r.text).startswith(cat["fe.title"].format(title=cat[case.title_key]))
    got = _summary(r.text)
    assert got is not None
    head, links = got
    assert head == cat["fe.summary"]
    assert [h for h, _w in links] == [f"#{case.prefix}-{f}" for f in case.failing]
    els = _parse(r.text)
    summary = next(a for t, a in els.tags if t == "div" and "fm-summary" in a.get("class", ""))
    assert summary["role"] == "alert" and summary["tabindex"] == "-1" and "autofocus" in summary
    assert summary["data-form"] == name
    assert els.ids[summary["aria-labelledby"]][0] == "h2"
    # the summary comes before the page's h1 (GOV.UK)
    assert r.text.index('class="fm-summary"') < r.text.index("<h1")
    for href, words in links:
        fid = href[1:]
        tag, attrs = els.ids[fid]  # the link targets an existing field
        assert tag in ("input", "select", "textarea") and attrs.get("aria-invalid") == "true", fid
        described = attrs["aria-describedby"].split()
        assert all(d in els.ids for d in described), (fid, described)  # aria-describedby resolves
        assert f"{fid}-err" in described
        assert _message(r.text, fid) == words  # the same words at the field and in the summary
        assert words in cat.values()
    # the fields that did not fail are not marked
    for _t, a in els.tags:
        if a.get("id", "").startswith(case.prefix + "-") and a["id"][len(case.prefix) + 1 :] not in case.failing:
            assert "aria-invalid" not in a, a["id"]
    assert not _events(box, case.saved_event)  # nothing saved


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("name", sorted(CASES))
def test_typed_values_come_back_and_secrets_never_do(box: dict[str, Any], name: str, lang: str) -> None:  # noqa: F811
    case = CASES[name]
    _c, r, _ = _failed(box, name, lang)
    els = _parse(r.text)
    for f in case.kept:
        assert els.ids[f"{case.prefix}-{f}"][1].get("value") == case.bad[f], f
    if "covers" in case.bad:
        assert "checked" in els.ids[f"{case.prefix}-covers"][1]
    for secret in SECRETS.values():
        assert secret not in r.text


@pytest.mark.parametrize("name", sorted(CASES))
def test_csrf_is_still_enforced_and_a_right_post_saves_as_before(box: dict[str, Any], name: str) -> None:  # noqa: F811
    case = CASES[name]
    want = case.saved_at
    for lang in LANGS:
        c = _client(box, case, lang)
        page = c.get(case.page).text
        if case.reset:  # a form that audits only a change (10F-1): back to where a save changes something
            r = c.post(case.action, data={"csrf": _csrf(page), **case.reset}, follow_redirects=False)
            assert r.status_code == 303
        before = len(_events(box, case.saved_event))
        for token in ("", "x" * 32):
            r = c.post(case.action, data={"csrf": token, **case.bad}, follow_redirects=False)
            assert r.status_code in (400, 403) and _summary(r.text) is None, (lang, r.status_code)
            r = c.post(case.action, data={"csrf": token, **case.good}, files=case.files or None,
                       follow_redirects=False)  # fmt: skip
            assert r.status_code in (400, 403), (lang, r.status_code)
        assert len(_events(box, case.saved_event)) == before  # refused: nothing saved
        r = c.post(case.action, data={"csrf": _csrf(page), **case.good}, files=case.files or None,
                   follow_redirects=False)  # fmt: skip
        assert r.status_code == 303 and r.headers["location"] == want
        assert len(_events(box, case.saved_event)) == before + 1
        after = c.get(case.page).text
        assert _summary(after) is None and not _title(after).startswith(_error_word(lang))


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")
def test_the_keyboard_reaches_each_field_from_the_summary(box: dict[str, Any], tmp_path: Path) -> None:  # noqa: F811
    """Measured in Chromium: on load the summary has focus; Tab reaches its first link; following each link moves
    focus to its field."""
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    css = ""
    for name in sorted(CASES):
        case = CASES[name]
        for lang in LANGS:
            c, r, _ = _failed(box, name, lang)
            assert r.status_code == 400
            f = f"{name}-{lang}.html"
            (out / f).write_text(r.text.replace('href="/static/console.css"', 'href="console.css"'), encoding="utf-8")
            css = css or c.get("/static/console.css").text
            pages.append({"name": f"{name}-{lang}", "file": f, "fields": [f"{case.prefix}-{x}" for x in case.failing]})
    (out / "console.css").write_text(css, encoding="utf-8")
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(out), "pages": pages})],
        cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and res["failed"] == {} and res["checked"] == len(pages), (res, r.stderr[-2000:])
