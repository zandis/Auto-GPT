"""10D-17 (D-1242, review 14 M14-16): the feasibility report's "no competing trials" sentence states the box's
ClinicalTrials.gov mode (``TB_CTGOV_MODE``: live, offline or cassette, D-140) in three languages, instead of saying
that TrialBox has no ClinicalTrials.gov connection, which was untrue on a box with CT.gov live or offline.

One text test per mode per language; the other pages, and the rest of this page, do not depend on the mode. All data
is synthetic."""

from __future__ import annotations

import html
import re
from typing import Any

import pytest
from console import home
from console.i18n import CATALOGUES, translate
from criteria_compiler import ctgov

from tests.console.test_console_app import _done_feas, box, login  # noqa: F401 - box: the fixture is used by name

PW = "ctgov-mode-password-01"
LANGS = ("en", "ja", "zh-TW")
MODES = ("live", "offline", "cassette")
HINT = re.compile(r'<p class="hint" data-testid="ct-mode" data-mode="([a-z]+)">(.*?)</p>', re.S)
OLD = {
    "en": "TrialBox has no jRCT or ClinicalTrials.gov connection",
    "ja": "jRCT や ClinicalTrials.gov に接続していない",
    "zh-TW": "沒有連接 jRCT 或 ClinicalTrials.gov",
}


def _crc(b: dict[str, Any], lang: str) -> Any:
    name = "crc-" + lang.lower()
    b["users"].create(name, "coordinator", PW, f"{name}@hospa.test")
    c, csrf = login(b["app"], name, PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    return c


def _hint(page: str) -> tuple[str, str]:
    found = HINT.findall(page)
    assert len(found) == 1, found
    return found[0][0], html.unescape(found[0][1])


def test_the_console_knows_the_compilers_three_modes_and_its_default() -> None:
    assert home.CTGOV_MODES == ctgov.MODES  # the console does not import the compiler; the same names, checked here
    assert home.ctgov_mode({}) == home.ctgov_mode({"TB_CTGOV_MODE": ""}) == "offline"  # the compiler's default too
    for m in MODES:
        assert home.ctgov_mode({"TB_CTGOV_MODE": m.upper()}) == m  # read as the compiler reads it (lower case)
    assert home.ctgov_mode({"TB_CTGOV_MODE": "online"}) == "unknown"  # never guessed into a mode it is not


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("mode", MODES)
def test_the_no_competing_trials_sentence_states_the_mode(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch, mode: str, lang: str
) -> None:
    _done_feas(box["backend"])
    monkeypatch.setenv("TB_CTGOV_MODE", mode)
    c = _crc(box, lang)
    shown, text = _hint(c.get("/studies/GZQO/feasibility").text)
    assert shown == mode and text == translate(lang, f"feas.ct.none.{mode}")
    assert OLD[lang] not in text
    assert "ClinicalTrials.gov" in text and "jRCT" in text  # both registries named, each with what holds for it
    if mode == "live":
        assert "clinicaltrials.gov" in text  # the host it reaches
    else:  # nothing is wrong: no connection is the design of the mode
        assert {"en": "Nothing is wrong", "ja": "異常ではありません", "zh-TW": "並非故障"}[lang] in text
    if mode == "offline":
        assert {"en": "signed update", "ja": "署名付き更新", "zh-TW": "簽署更新"}[lang] in text
    if mode == "cassette":
        assert {"en": "synthetic", "ja": "合成", "zh-TW": "合成"}[lang] in text
    # the list itself is typed by the coordinator in every mode: no registry fills it
    assert {"en": "the coordinator types", "ja": "CRCが", "zh-TW": "研究護理師"}[lang] in text


@pytest.mark.parametrize("lang", LANGS)
def test_an_unknown_setting_is_named_and_sent_to_the_administrator(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch, lang: str
) -> None:
    _done_feas(box["backend"])
    monkeypatch.setenv("TB_CTGOV_MODE", "online")
    shown, text = _hint(_crc(box, lang).get("/studies/GZQO/feasibility").text)
    assert shown == "unknown" and text == translate(lang, "feas.ct.none.unknown") and "TB_CTGOV_MODE" in text


def test_the_four_texts_exist_in_three_languages_and_the_untrue_one_is_gone() -> None:
    for lang in LANGS:
        cat = CATALOGUES[lang]
        assert "feas.ct.none" not in cat
        texts = [cat[f"feas.ct.none.{m}"] for m in (*MODES, "unknown")]
        assert len(set(texts)) == 4 and not any(OLD[lang] in t for t in texts)


def test_only_the_one_sentence_depends_on_the_mode(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Every other page, and the rest of the feasibility page, render the same bytes in every mode."""
    _done_feas(box["backend"])
    c = _crc(box, "en")
    paths = ("/home", "/reports", "/studies/GZQO/feasibility?view=sponsor", "/studies/GZQO/feasibility")
    seen: dict[str, set[str]] = {p: set() for p in paths}
    for mode in (*MODES, "online"):
        monkeypatch.setenv("TB_CTGOV_MODE", mode)
        for p in paths:
            r = c.get(p)
            assert r.status_code == 200, (p, r.status_code)
            seen[p].add(HINT.sub("<p>CT-MODE</p>", r.text))
    for p, pages in seen.items():
        assert len(pages) == 1, p
    monkeypatch.delenv("TB_CTGOV_MODE")
    assert c.get("/home").text in seen["/home"]  # unset reads as the default, offline
