# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""10C-25 (D-1250): a night's "Site profile" section (``/data-ops/batches/<id>``, D-1233) names the country layer
above the profile (its country, version and digest) and, per setting the layer offers or turns on, the value in force
and whether it is "from the Japan profile", "set by the site" or "not set: as before the profile". A site whose
country has no layer sees the section exactly as before: the same bytes with every country layer taken away.

Synthetic data only: the synthetic Japanese hospital's profile stamp and the Cabinet Office's public holiday list."""

from __future__ import annotations

import html
import re
from typing import Any

import pytest
from tb_common import country_layer, derived

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_dataops_site_profile import PROFILE, _night, _section, _steward
from tests.unit.test_japan_profile_layer import _layers

WORDS = {
    "en": ("Country profile", "set by the site", "from the Japan profile", "not set: as before the profile"),
    "ja": ("国別プロファイル", "施設が設定", "日本のプロファイルから", "未設定：プロファイル導入前のとおり"),
    "zh-TW": ("國別設定檔", "本院設定", "取自日本設定檔", "未設定：與設定檔啟用前相同"),
}


@pytest.fixture(autouse=True)
def _orch(box: dict[str, Any]) -> None:
    from tests.console.dataops_orch import attach

    attach(box["backend"], box["audit"])


def _rows(page: str) -> dict[str, tuple[str, str, str]]:
    """``data-testid="layer-<key>"`` rows: (source, value in force, the profile's value)."""
    out = {}
    for key, source, body in re.findall(r'data-testid="layer-([a-z_]+)" data-source="([a-z]+)">(.*?)</tr>', page):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", body)
        out[key] = (source, html.unescape(cells[1]), html.unescape(cells[3]))
    return out


def test_the_site_profile_section_names_the_layer_and_where_each_setting_comes_from(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(derived, "country_of", lambda tz=None, locale=None: "JP")  # a box in Japan
    for k in ("TB_CONSENT_PROXY", "TB_NEW_YEAR_BREAK", "TB_JP_INGREDIENT_ATC"):
        monkeypatch.delenv(k, raising=False)
    bid = _night(box, PROFILE)
    c, csrf = _steward(box)
    sec = _section(c.get(f"/data-ops/batches/{bid}").text)
    rows = _rows(sec)
    lay = country_layer.layer("JP")
    assert f"1.0.0, {lay.digest[:12]}" in sec and lay.digest not in sec and len(rows) == 10
    assert rows["new_year_break"] == ("layer", "12-29/01-03", "12-29/01-03")
    assert rows["printed_dates"] == ("unset", "western", "both")  # the layer is not a run-time default (D-1229)
    assert rows["consent_proxy"] == ("unset", "off", "on")
    assert rows["egfr"] == ("layer", "egfr_jsn", "egfr_jsn") and rows["committees"][0] == "layer"
    # the site sets its own: each says so, and its value is the one in force
    monkeypatch.setenv("TB_CONSENT_PROXY", "off")
    monkeypatch.setenv("TB_NEW_YEAR_BREAK", "12-28/01-04")
    for lang, words in WORDS.items():
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
        sec = _section(c.get(f"/data-ops/batches/{bid}").text)
        rows = _rows(sec)
        assert rows["new_year_break"] == ("site", "12-28/01-04", "12-29/01-03")
        assert rows["consent_proxy"] == ("site", "off", "on")
        assert all(w in html.unescape(sec) for w in words), lang
        assert "style=" not in sec and "nowrap" not in sec


def test_a_site_without_a_country_layer_sees_the_section_as_before(box: dict[str, Any]) -> None:
    """The test box is in Taipei: no layer, no lines, and the page is the same bytes with every layer taken away."""
    bid = _night(box, PROFILE)
    c, csrf = _steward(box)
    for lang in WORDS:
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/home"})
        with_layers = c.get(f"/data-ops/batches/{bid}").text
        with _layers({}):
            without = c.get(f"/data-ops/batches/{bid}").text
        assert 'data-testid="profile-layer' not in with_layers
        assert with_layers.replace(_csrf(with_layers), "") == without.replace(_csrf(without), "")
    assert not country_layer.layer("TW").on


def test_a_night_read_without_a_profile_has_no_layer_lines_either(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(derived, "country_of", lambda tz=None, locale=None: "JP")
    bid = _night(box, None)
    c, _ = _steward(box)
    assert 'data-testid="profile-layer' not in c.get(f"/data-ops/batches/{bid}").text


def _csrf(page: str) -> str:
    """The page's form token (a new one may be drawn per request): left out of the comparison."""
    i = page.find('name="csrf" value="')
    return page[i + 19 : page.index('"', i + 19)] if i >= 0 else "\0"
