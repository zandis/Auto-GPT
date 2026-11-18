"""10K-1: the box's first-run page asks the site's country first (behind ``TB_FIRSTRUN_COUNTRY``, off by default) and
offers SS-MIX2 as a source with the questions it needs. Driven through the real console app; the layout at 390 px is
measured in Chromium (``tests/console/cjk_layout.js``) where Node Playwright is installed. All data is synthetic."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tb_common import firstrun
from tb_common.retention import OVERRIDABLE

from tests.console.test_cjk_layout import PHONE, SCRIPT, _node_playwright
from tests.console.test_firstrun import _answers, _box, _with_code

ROOT = Path(__file__).resolve().parents[2]


CSRF = re.compile(r'name="fr_csrf" value="([^"]+)"')
# the answers page's fields on master, before 10K-1 (templates/firstrun.html): with the flag off it has these only
MASTER_FIELDS = {"fr_csrf", "lang", "site_name", "tz", "language", "owner_full_name", "owner_username", "owner_email",
                 "password", "password2", "totp", "box_name", "backup_kind", "backup_disk", "backup_share", "source",
                 "chartno_kind", "chartno_width"}  # fmt: skip


def _names(page: str) -> set[str]:
    return set(re.findall(r'<(?:input|select)[^>]* name="([^"]+)"', page))


def _keep(c: Any, page: str, **data: str) -> Any:
    """What a button of the country step, the "change" button or a language button posts: the typed values, kept."""
    csrf = CSRF.search(page)
    assert csrf, page[-400:]
    return c.post("/login/first-run/answers/keep", data={"fr_csrf": csrf.group(1), **data})


def _answered(c: Any, pick: str, **over: str) -> Any:
    """The form as the page shows it once the country is chosen (the first step), then posted as in test_firstrun."""
    real_get = c.get

    def get(url: str, **kw: Any) -> Any:
        r = real_get(url, **kw)
        return _keep(c, r.text, pick_country=pick) if url.endswith("/answers") else r

    c.get = get
    try:
        r, _ = _answers(c, **({"country": pick} | over))
    finally:
        c.get = real_get
    return r


def test_with_the_flag_off_the_page_is_as_on_master(tmp_path: Path) -> None:
    """Review of #1088, item 2: with the flag off nothing of 10K-1 is on the page, SS-MIX2 included."""
    b = _box(tmp_path)
    c = _with_code(b)
    page = c.get("/login/first-run/answers").text
    assert _names(page) == MASTER_FIELDS and "ssmix2" not in page and "country" not in page
    assert c.post("/login/first-run/answers/keep", data={}).status_code == 404  # the flag's route: not there
    r, _ = _answers(c, country="jp", logs_days="1")  # posted all the same: dropped, as the page never asked
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert got["country"] == "" and got["retention_days"] == {}


def test_with_the_flag_off_ssmix2_posted_all_the_same_is_refused_and_said_so(tmp_path: Path) -> None:
    c = _with_code(_box(tmp_path))
    r, _ = _answers(c, source="ssmix2", ssmix2_root="/mnt/ssmix2")
    assert r.status_code == 422 and 'data-testid="err-source"' in r.text and "only for a site in Japan" in r.text


def test_the_country_is_the_first_question_and_fills_in_its_defaults(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    first = c.get("/login/first-run/answers?lang=ja").text
    assert 'data-testid="firstrun-country"' in first and 'name="site_name"' not in first  # nothing else yet
    for country, word in (("jp", "日本"), ("tw", "台湾"), ("us", "米国"), ("other", "その他の国・地域")):
        assert f'data-testid="country-{country}"' in first and word in first
    jp = _keep(c, first, lang="ja", pick_country="jp").text
    assert 'name="country" value="jp"' in jp and 'id="tz"' in jp and 'value="Asia/Tokyo"' in jp
    assert re.search(r'<option value="ja" selected>', jp)  # the report language
    assert re.search(r'name="source" value="ssmix2" checked', jp)  # SS-MIX2 is Japan's shipped source
    assert 'data-testid="firstrun-retention"' not in jp  # Japan's rules exist (D-138)
    assert 'data-testid="country-change"' in jp and "国・地域を変更する" in jp  # the link says what it does
    tw = _keep(c, first, pick_country="tw").text
    assert 'value="Asia/Taipei"' in tw and re.search(r'<option value="zh-TW" selected>', tw)
    # review item 2: SS-MIX2 is offered only where a shipped mapping reads it
    assert "ssmix2" not in tw
    us = _keep(c, first, pick_country="us").text
    assert 'data-testid="firstrun-retention"' in us and re.search(r'<option value="en" selected>', us)
    assert 'value="Asia/Tokyo"' in us and "ssmix2" not in us  # no zone of its own: the box's clock zone


def test_changing_the_country_or_the_language_keeps_what_was_typed(tmp_path: Path) -> None:
    """Review of #1088, item 4: the country's and the language's buttons post the form; nothing typed is lost."""
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    page = _keep(c, c.get("/login/first-run/answers").text, pick_country="jp").text
    typed = {"site_name": "架空病院K (synthetic)", "owner_full_name": "Dr Owner", "owner_email": "owner@hospk.test",
             "box_name": "box-k", "password": "never-sent-back-0001"}  # fmt: skip
    form = {"lang": "en", "country": "jp", "tz": "Asia/Tokyo", **typed}
    back = _keep(c, page, **form, pick_country="").text  # "change the country": back to the first question
    assert 'data-testid="firstrun-country"' in back and 'id="site_name"' not in back  # carried, hidden
    assert "架空病院K (synthetic)" in back and "owner@hospk.test" in back and "never-sent-back" not in back
    again = _keep(c, back, **{k: v for k, v in form.items() if k != "password"}, pick_country="us").text
    assert (
        'value="架空病院K (synthetic)"' in again and 'value="box-k"' in again and 'name="country" value="us"' in again
    )
    ja = _keep(
        c, again, **{k: v for k, v in form.items() if k != "password"} | {"country": "us"}, switch_lang="ja"
    ).text
    assert '<html lang="ja"' in ja and 'value="架空病院K (synthetic)"' in ja and 'name="country" value="us"' in ja


def test_a_tampered_country_is_named_and_the_typed_values_stay(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    r = _answered(c, "jp", country="fr", site_name="架空病院F (synthetic)")
    assert r.status_code == 422 and 'data-testid="err-country"' in r.text
    assert "Choose a country or region from the list." in r.text and "架空病院F (synthetic)" in r.text
    assert b["users"].count() == 0


def test_a_japanese_box_with_ssmix2_hands_its_answers_to_the_installer(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    r = _answered(c, "jp", source="ssmix2", ssmix2_root="relative")
    assert r.status_code == 422 and 'data-testid="err-ssmix2_root"' in r.text and 'name="country" value="jp"' in r.text
    r = _answered(c, "jp", source="ssmix2", ssmix2_root="/mnt/ssmix2", ssmix2_order_numbers="per_day")
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert (got["country"], got["source"], got["ssmix2_root"], got["ssmix2_order_numbers"]) == (
        "jp", "ssmix2", "/mnt/ssmix2", "per_day"
    )  # fmt: skip


def test_a_country_without_rules_asks_the_days(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    r = _answered(c, "other", tz="Europe/Paris", language="en")
    assert r.status_code == 422
    for k in OVERRIDABLE:
        assert f'data-testid="err-{k}"' in r.text, k
    r = _answered(c, "other", tz="Europe/Paris", language="en", **dict.fromkeys(OVERRIDABLE, "400"))
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert got["retention_days"] == dict.fromkeys(OVERRIDABLE, 400)


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
def test_the_new_steps_fit_a_phone_in_three_languages(tmp_path: Path) -> None:
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    first = c.get("/login/first-run/answers").text
    for lang in ("en", "ja", "zh-TW"):
        for name, data in (("country", {"switch_lang": lang}), ("jp", {"lang": lang, "pick_country": "jp"}),
                           ("us", {"lang": lang, "pick_country": "us"})):  # fmt: skip
            r = _keep(c, first, **data)
            assert r.status_code == 200
            f = f"firstrun-{name}-{lang}.html"
            (out / f).write_text(r.text.replace('href="/static/console.css"', 'href="console.css"'), encoding="utf-8")
            pages.append({"file": f, "lang": lang, "width": PHONE[0], "height": PHONE[1], "checks": []})
    (out / "console.css").write_text(c.get("/static/console.css").text, encoding="utf-8")
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(out), "pages": pages, "shots": ""})],
        cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and res["failed"] == 0, (res.get("results"), r.stderr[-2000:])


def test_only_the_forms_own_fields_are_carried(tmp_path: Path) -> None:
    """Second review, item 2: an unknown posted field is never sent back (an allowlist from the form)."""
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    first = c.get("/login/first-run/answers").text
    back = _keep(c, first, site_name="S (synthetic)", password3="not-a-field-0001", evil="x").text
    assert (
        "S (synthetic)" in back and "password3" not in back and "not-a-field" not in back and 'name="evil"' not in back
    )


def test_jp_to_us_and_back_keeps_the_ssmix2_folder(tmp_path: Path) -> None:
    """Second review, item 6."""
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    jp = _keep(c, c.get("/login/first-run/answers").text, pick_country="jp").text
    us = _keep(c, jp, country="jp", source="ssmix2", ssmix2_root="/mnt/ssmix2", ssmix2_order_numbers="per_day",
               pick_country="us").text  # fmt: skip
    back = _keep(c, us, **dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', us)),
                 pick_country="jp").text  # fmt: skip
    assert 'value="/mnt/ssmix2"' in back and re.search(r'value="per_day" checked', back)


def test_the_page_says_what_is_still_to_do(tmp_path: Path) -> None:
    """Second review, item 3: in three languages, through the catalogue."""
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    first = c.get("/login/first-run/answers").text
    for lang in ("en", "ja", "zh-TW"):
        jp = _keep(c, first, lang=lang, switch_lang=lang, pick_country="jp").text
        assert 'data-testid="firstrun-ssmix2-verify"' in jp, lang
        for country in ("us", "other"):
            page = _keep(c, first, lang=lang, switch_lang=lang, pick_country=country).text
            assert 'data-testid="firstrun-mapped-later"' in page, (lang, country)
        assert 'data-testid="firstrun-mapped-later"' not in jp


def test_with_the_flag_off_the_route_table_is_masters(tmp_path: Path) -> None:
    """Second review: the keep route exists only with the flag on."""
    off = {getattr(r, "path", "") for r in _box(tmp_path / "off")["app"].routes}
    on = {getattr(r, "path", "") for r in _box(tmp_path / "on", TB_FIRSTRUN_COUNTRY="1")["app"].routes}
    assert "/login/first-run/answers/keep" not in off and on - off == {"/login/first-run/answers/keep"}
