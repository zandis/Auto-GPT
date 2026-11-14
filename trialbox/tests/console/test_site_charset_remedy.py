"""NEW-SITE-1 (D-559): the site set-up's two refusals of a file whose text cannot be read say what to do.

``site.err.CHART-TEXT`` (a chart text in no known character set) and ``site.err.SHEET-READ`` (a sheet that cannot
be read) named the fault and no remedy for the character-set case. Both end with the remedy the data pages' own
refusals give (lane E's sentences, ``dc.err.FORM-ENCODING``): save as UTF-8 with a byte order mark, which Excel
calls "CSV UTF-8", and try again. Three languages, none of the forbidden words."""

from __future__ import annotations

import pytest
from console.i18n import CATALOGUES
from tb_common.wording import check_page

LANGS = ("en", "ja", "zh-TW")
REMEDY = {"en": "UTF-8 with a byte order mark (in Excel: CSV UTF-8)", "ja": "BOM 付き UTF-8（Excel では「CSV UTF-8」）",
          "zh-TW": "含 BOM 的 UTF-8（Excel 的「CSV UTF-8」）"}  # fmt: skip


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("key", ["site.err.CHART-TEXT", "site.err.SHEET-READ"])
def test_a_text_that_cannot_be_read_is_refused_with_its_remedy(lang: str, key: str) -> None:
    text = CATALOGUES[lang][key]
    assert REMEDY[lang] in text, (lang, key)
    assert check_page(f"<p>{text}</p>") == [], (lang, key)


def test_the_sheet_refusal_still_names_the_two_formats() -> None:
    for lang in LANGS:
        text = CATALOGUES[lang]["site.err.SHEET-READ"]
        assert ".xlsx" in text and "CSV" in text, lang
