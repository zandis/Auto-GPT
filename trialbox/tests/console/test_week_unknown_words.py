"""R22-53 (review 22, E-M2): the week page names "unknown" with one word per language and says, once, that an unknown
answer never removes a patient from the list.

The sentence reuses the approved wording of ``conflicts.help`` (the conflicts page), which already says it in the
three languages; the zh-TW week page writes 不明, the catalogue's majority spelling and the word of ``verdict.unknown``
on the same page, not 未知 as well."""

from __future__ import annotations

import html
import re
from typing import Any

import pytest
from console import i18n_conflicts
from console.i18n import CATALOGUES

from tests.console.test_cjk_layout import LANGS, _as, _main, _setup
from tests.console.test_console_app import box

__all__ = ["box"]

CONFLICTS = {"en": i18n_conflicts.EN, "ja": i18n_conflicts.JA, "zh-TW": i18n_conflicts.ZH}
LISTS = ("all", "needs", "ready")


def _week(b: dict[str, Any], lang: str, lst: str) -> str:
    return _main(_as(b, "drsato", lang).get(f"/studies/GZQO/week?list={lst}").text)


@pytest.mark.parametrize("lang", LANGS)
def test_the_week_page_says_once_that_unknown_never_removes_a_patient(box: dict[str, Any], lang: str) -> None:
    _setup(box)
    words = CATALOGUES[lang]["week.unknown_keeps"]
    page = _week(box, lang, "all")
    assert page.count(html.escape(words)) == 1, (lang, words)
    m = re.search(r'data-testid="unknown-keeps">([^<]+)<', page)
    assert m and html.unescape(m.group(1)) == words


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_the_never_removes_sentence_is_the_conflicts_pages_approved_wording(lang: str) -> None:
    words = CATALOGUES[lang]["week.unknown_keeps"].rstrip(".。")
    assert words.lower() in CONFLICTS[lang]["conflicts.help"].lower(), (lang, words)


def test_the_zh_tw_never_removes_sentence_is_the_conflicts_wording_in_the_pages_word() -> None:
    words = CATALOGUES["zh-TW"]["week.unknown_keeps"].rstrip("。")
    assert words.replace("不明", "未知") in CONFLICTS["zh-TW"]["conflicts.help"], words


@pytest.mark.parametrize("lst", LISTS)
def test_the_zh_tw_week_page_spells_unknown_one_way(box: dict[str, Any], lst: str) -> None:
    _setup(box)
    page = _week(box, "zh-TW", lst)
    assert "未知" not in page, [page[max(0, i - 60) : i + 20] for i in (m.start() for m in re.finditer("未知", page))]


@pytest.mark.parametrize("key", ["verdict.unknown", "wb.n_open", "wb.list.needs.help", "wb.list.ready.help"])
def test_the_zh_tw_words_of_the_week_page_for_unknown_are_bu_ming(key: str) -> None:
    text = CATALOGUES["zh-TW"][key]
    assert "未知" not in text and "不明" in text, (key, text)
