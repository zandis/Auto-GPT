"""10C-25 (D-1250): the page where the site's calendar settings are shown says which come from the Japan profile
and which the site set itself, and that the site's own setting wins; a site of another country sees exactly the page
it saw before (the same bytes with every country layer taken away).

Synthetic data only: the test box's study GZQO and the Cabinet Office's public holiday list."""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from tb_common import country_layer, workdays
from tb_common.workdays import for_country

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name
from tests.unit.test_japan_profile_layer import _layers

WORDS = {
    "en": ("are the country profile's (JP, version 1.0.0)", "a setting the site made is used instead"),
    "ja": (
        "は国別プロファイル（JP、バージョン 1.0.0）のものです",
        "施設の設定が国別プロファイルの値（12-29/01-03）より優先されます",
    ),
    "zh-TW": ("取自國別設定檔（JP，版本 1.0.0）", "採用本院的設定，而非國別設定檔的值（12-29/01-03）"),
}


def test_the_days_off_say_they_come_from_the_japan_profile_and_that_the_sites_break_wins(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lb["clock"]["now"] = datetime(2026, 12, 20, 1, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    c, csrf = login(lb["app"], "crc", PW)
    for lang, (layer, wins) in WORDS.items():
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        monkeypatch.setattr(workdays, "for_zone", lambda _tz, env=None: for_country("JP", {}))
        page = c.get("/studies/GZQO/schedule").text
        line = html.unescape(page[page.index('data-testid="days-off-layer"') :].split("</p>", 1)[0])
        assert layer in line and "12-29/01-03" in line and wins not in line
        assert "2026-12-29" in page  # the layer's break is the one counted
        mine = {"TB_NEW_YEAR_BREAK": "12-28/01-04"}
        monkeypatch.setattr(workdays, "for_zone", lambda _tz, env=None, m=mine: for_country("JP", m))
        page = c.get("/studies/GZQO/schedule").text
        line = html.unescape(page[page.index('data-testid="days-off-layer"') :].split("</p>", 1)[0])
        assert layer in line and wins in line and "12-28/01-04" in line
        assert "2026-12-28" in page  # and the site's is the one counted


def test_a_site_of_another_country_sees_the_same_bytes_with_or_without_any_country_layer(
    lb: dict[str, Any],  # noqa: F811
) -> None:
    """The test box is in Taipei: no layer. Its schedule page is byte for byte the page with every layer taken away
    (no layer at all is what master had for every site but the committees part, which Taipei never read)."""
    lb["clock"]["now"] = datetime(2026, 12, 20, 1, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    c, csrf = login(lb["app"], "crc", PW)
    for lang in WORDS:
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        with_layers = c.get("/studies/GZQO/schedule").text
        with _layers({}):
            without = c.get("/studies/GZQO/schedule").text
        assert with_layers.replace(_csrf(with_layers), "") == without.replace(_csrf(without), "")
        assert 'data-testid="days-off' not in with_layers
    assert not country_layer.layer("TW").on


def _csrf(page: str) -> str:
    """The page's form token (a new one may be drawn per request): left out of the comparison."""
    i = page.find('name="csrf" value="')
    return page[i + 19 : page.index('"', i + 19)] if i >= 0 else "\0"


# ------------------------------------------------------------------------- the site page's country profile card
from tests.console.test_site_setup_pages import PW as SITE_PW  # noqa: E402
from tests.console.test_site_setup_pages import sb  # noqa: E402, F401 - the fixture is used by name

CARD = {
    "en": ("Country profile", "set by the site", "from the Japan profile", "not set: as before the profile"),
    "ja": ("国別プロファイル", "施設が設定", "日本のプロファイルから", "未設定：プロファイル導入前のとおり"),
    "zh-TW": ("國別設定檔", "本院設定", "取自日本設定檔", "未設定：與設定檔啟用前相同"),
}


def _rows(page: str) -> dict[str, tuple[str, str, str]]:
    """``data-testid="layer-<key>"`` rows: (source, value in force, the profile's value)."""
    out = {}
    for key, source, body in re.findall(r'data-testid="layer-([a-z_]+)" data-source="([a-z]+)">(.*?)</tr>', page):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", body)
        out[key] = (source, html.unescape(cells[1]), html.unescape(cells[3]))
    return out


def test_the_site_page_shows_each_setting_from_the_japan_profile_or_set_by_the_site(
    sb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tb_common import derived

    monkeypatch.setattr(derived, "country_of", lambda tz=None, locale=None: "JP")  # a box in Japan
    for k in ("TB_CONSENT_PROXY", "TB_NEW_YEAR_BREAK", "TB_JP_INGREDIENT_ATC"):
        monkeypatch.delenv(k, raising=False)
    c, csrf = login(sb["app"], "crc", SITE_PW)
    page = c.get("/site?study=GZQO").text
    rows = _rows(page)
    lay = country_layer.layer("JP")
    assert f"1.0.0, {lay.digest[:12]}" in page and len(rows) == 10
    assert rows["new_year_break"] == ("layer", "12-29/01-03", "12-29/01-03")
    assert rows["printed_dates"] == ("unset", "western", "both")  # the layer is not a run-time default (D-1229)
    assert rows["consent_proxy"] == ("unset", "off", "on")
    assert rows["egfr"] == ("layer", "egfr_jsn", "egfr_jsn") and rows["committees"][0] == "layer"
    # the site sets its own: each one says so and wins
    monkeypatch.setenv("TB_CONSENT_PROXY", "off")
    monkeypatch.setenv("TB_NEW_YEAR_BREAK", "12-28/01-04")
    for lang, words in CARD.items():
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        page = c.get("/site?study=GZQO").text
        rows = _rows(page)
        assert rows["new_year_break"] == ("site", "12-28/01-04", "12-29/01-03")
        assert rows["consent_proxy"] == ("site", "off", "on")
        sec = html.unescape(page[page.index('data-testid="site-country-layer"') :].split("</section>", 1)[0])
        assert all(w in sec for w in words), lang


def test_a_site_without_a_country_layer_has_no_card_and_the_same_page(sb: dict[str, Any]) -> None:  # noqa: F811
    c, csrf = login(sb["app"], "crc", SITE_PW)  # the test box is in Taipei
    for lang in WORDS:
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        with_layers = c.get("/site?study=GZQO").text
        with _layers({}):
            without = c.get("/site?study=GZQO").text
        assert 'data-testid="site-country-layer"' not in with_layers
        assert with_layers.replace(_csrf(with_layers), "") == without.replace(_csrf(without), "")
