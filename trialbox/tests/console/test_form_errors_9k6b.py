"""9k-6b (D-1376, review 09 DS-6, A11Y-4): a failed POST of each form converted in 9k-6b, journey 1 (the study's and the
site's records), in en, ja and zh-TW.

For each case of ``tests/console/form_cases_9k6b.py`` (the IRB record, a consent-form version, the committee record,
the staff directory, a department contact, an opt-out, the lifting of one, the study's state change and the take-back
of a close), drawn by the in-process box, the checks of ``test_form_errors_9k6a.py``:

* the page before any POST has no summary and no "Error:" in its title;
* a POST with wrong values answers 400 (as before) with the summary at the top: ``role="alert"``, focusable and
  focused on load, its heading, one link per failing field in the form's order, each to an existing field id; the
  title begins with "Error:"; each failing field has ``aria-invalid`` and an ``aria-describedby`` whose every id
  exists and names the field's own message, in the same words as its link; nothing is saved (no audit event);
* what was typed comes back (a ticked box stays ticked); a password or a one-time code posted with it never does;
* a POST without the right CSRF token is still refused and saves nothing; a right POST saves as before (303, the
  same audit event).

The keyboard order (focus on the summary when the page loads, Tab to its first link, Enter moves focus to the field)
is measured in Chromium through Node Playwright with the script of 9k-6a, skipped where it is missing. Synthetic only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from console.i18n import CATALOGUES

from tests.console.form_cases_9k6b import CASES, Case
from tests.console.test_cjk_layout import _node_playwright
from tests.console.test_console_app import box, login, name_pi  # noqa: F401 - box is a fixture
from tests.console.test_form_errors_9k6a import (
    SCRIPT,
    SECRETS,
    _error_word,
    _events,
    _message,
    _parse,
    _summary,
    _title,
)
from tests.console.test_role_pages import PW, _csrf, _user

ROOT = Path(__file__).resolve().parents[2]
LANGS = ("en", "ja", "zh-TW")
USERS = {"coordinator": ("crc1", "coordinator"), "pi": ("drsato", "investigator"), "steward": ("stw", "steward")}


@pytest.fixture
def jbox(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The console's test box made at a Japanese site (the committee record is there only then), site SAMPLE-A."""
    monkeypatch.setenv("TB_TZ", "Asia/Tokyo")
    monkeypatch.setenv("TB_SITE_ID", "SAMPLE-A")
    return dict(request.getfixturevalue("box"))


def _client(b: dict[str, Any], role: str, lang: str) -> Any:
    """``role`` signed in, the page language ``lang`` (the PI named once, through the steward's log)."""
    user, kind = USERS[role]
    if b["users"].get(user) is None:
        c = _user(b, user, kind)
        if role == "pi":
            name_pi(b, user)
    else:
        c, _ = login(b["app"], user, PW)
    r = c.post("/lang", data={"csrf": _csrf(c.get("/").text), "lang": lang, "back": "/"}, follow_redirects=False)
    assert r.status_code == 303
    return c


def _prep_optout_d(b: dict[str, Any]) -> None:
    """An opt-out on the register for the pseudonym of 32 'd': the row the lifting form is on."""
    c = _client(b, "steward", "en")
    r = c.post("/site/opt-outs", data={"csrf": _csrf(c.get("/site/opt-outs").text), "pid": "d" * 32,
                                       "source": "paper"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]


def _prep_closed_today(b: dict[str, Any]) -> None:
    """The study closed today (the site's day): the PI may take the close back."""
    h = b["app"].state.helpers
    h.store.set_study_state("GZQO", "closed", "synthetic close", "console:test", h.clock().isoformat(), keep_years=1)


PREP = {"optout_d": _prep_optout_d, "closed_today": _prep_closed_today}


def _box(request: pytest.FixtureRequest, case: Case) -> dict[str, Any]:
    b = request.getfixturevalue("jbox" if case.japan else "box")
    for step in case.prep:
        PREP[step](b)
    return b  # type: ignore[no-any-return]


def _failed(b: dict[str, Any], case: Case, lang: str) -> tuple[Any, Any]:
    c = _client(b, case.role, lang)
    page = c.get(case.page)
    assert page.status_code == 200 and _summary(page.text) is None
    assert not _title(page.text).startswith(_error_word(lang))
    r = c.post(case.action, data={"csrf": _csrf(page.text), **case.bad, **SECRETS}, follow_redirects=False)
    return c, r


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("name", sorted(CASES))
def test_a_failed_post_shows_the_summary_tied_to_each_field(
    request: pytest.FixtureRequest,
    name: str,
    lang: str,
) -> None:
    case, cat = CASES[name], CATALOGUES[lang]
    b = _box(request, case)
    before = len(_events(b, case.saved_event))
    _c, r = _failed(b, case, lang)
    assert r.status_code == 400, r.text[-500:]
    assert f'data-testid="{case.testid}"' in r.text
    title = _title(r.text)
    assert title.startswith(_error_word(lang)) and cat[case.title] in title
    got = _summary(r.text)
    assert got is not None
    head, links = got
    assert head == cat["fe.summary"]
    assert [h for h, _w in links] == [f"#{case.prefix}-{f}" for f in case.failing]
    els = _parse(r.text)
    summary = next(a for t, a in els.tags if t == "div" and "fm-summary" in a.get("class", ""))
    assert summary["role"] == "alert" and summary["tabindex"] == "-1" and "autofocus" in summary
    assert els.ids[summary["aria-labelledby"]][0] == "h2"
    assert r.text.index('class="fm-summary"') < r.text.index("<h1")  # before the page's h1 (GOV.UK)
    for href, words in links:
        fid = href[1:]
        tag, attrs = els.ids[fid]  # the link targets an existing field
        assert tag in ("input", "select", "textarea") and attrs.get("aria-invalid") == "true", fid
        described = attrs["aria-describedby"].split()
        assert all(d in els.ids for d in described), (fid, described)
        assert f"{fid}-err" in described
        assert _message(r.text, fid) == words  # the same words at the field and in the summary
        assert words in cat.values()
    for _t, a in els.tags:  # the fields that did not fail are not marked
        if a.get("id", "").startswith(case.prefix + "-") and a["id"][len(case.prefix) + 1 :] not in case.failing:
            assert "aria-invalid" not in a, a["id"]
    assert len(_events(b, case.saved_event)) == before  # nothing saved


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("name", sorted(CASES))
def test_typed_values_come_back_and_secrets_never_do(
    request: pytest.FixtureRequest,
    name: str,
    lang: str,
) -> None:
    case = CASES[name]
    b = _box(request, case)
    _c, r = _failed(b, case, lang)
    els = _parse(r.text)
    for f in case.kept:
        tag, attrs = els.ids[f"{case.prefix}-{f}"]
        if tag == "select":
            chosen = [o for o in r.text.split(f'id="{case.prefix}-{f}"', 1)[1].split("</select>", 1)[0].split("<option")
                      if " selected" in o]  # fmt: skip
            assert len(chosen) == 1 and f'value="{case.bad[f]}"' in chosen[0], f
        else:
            assert attrs.get("value", "") == case.bad[f] or tag == "textarea", f
    for f in case.checked:
        assert "checked" in els.ids[f"{case.prefix}-{f}"][1], f
    for secret in SECRETS.values():
        assert secret not in r.text


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("name", sorted(CASES))
def test_csrf_is_still_enforced_and_a_right_post_saves_as_before(
    request: pytest.FixtureRequest,
    name: str,
    lang: str,
) -> None:
    case = CASES[name]
    b = _box(request, case)
    c = _client(b, case.role, lang)
    page = c.get(case.page).text
    before = len(_events(b, case.saved_event))
    for token in ("", "x" * 32):
        r = c.post(case.action, data={"csrf": token, **case.bad}, follow_redirects=False)
        assert r.status_code in (400, 403) and _summary(r.text) is None, (lang, r.status_code)
        r = c.post(case.action, data={"csrf": token, **case.good}, follow_redirects=False)
        assert r.status_code in (400, 403), (lang, r.status_code)
    assert len(_events(b, case.saved_event)) == before  # refused: nothing saved
    r = c.post(case.action, data={"csrf": _csrf(page), **case.good}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(case.want), r.headers.get("location")
    assert len(_events(b, case.saved_event)) == before + 1
    after = c.get(case.page).text
    assert _summary(after) is None and not _title(after).startswith(_error_word(lang))


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")
def test_the_keyboard_reaches_each_field_from_the_summary(jbox: dict[str, Any], tmp_path: Path) -> None:
    """Measured in Chromium: on load the summary has focus; Tab reaches its first link; following each link moves
    focus to its field."""
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    css = ""
    for name in sorted(CASES):  # the state change (a coordinator) comes before the take-back that closes the study
        case = CASES[name]
        for step in case.prep:
            PREP[step](jbox)
        for lang in LANGS:
            c, r = _failed(jbox, case, lang)
            assert r.status_code == 400
            f = f"{name}-{lang}.html"
            (out / f).write_text(r.text.replace('href="/static/console.css"', 'href="console.css"'), encoding="utf-8")
            css = css or c.get("/static/console.css").text
            pages.append({"name": f"{name}-{lang}", "file": f, "fields": [f"{case.prefix}-{x}" for x in case.failing]})
    (out / "console.css").write_text(css, encoding="utf-8")
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(out), "pages": pages})],
        cwd=ROOT, capture_output=True, text=True, timeout=900, check=False,
    )  # fmt: skip
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and res["failed"] == {} and res["checked"] == len(pages), (res, r.stderr[-2000:])
