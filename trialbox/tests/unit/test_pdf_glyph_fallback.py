"""UX-002: a report PDF chose one font by the report's language, and each Noto family lacks common characters of
the other: a Japanese word in an English or zh-TW report (検 査 験 薬) or a Taiwan record quoted in a Japanese report
(查 值 啟) was printed as empty boxes, with no warning. Now a character the report's font lacks is set in the other
family, character by character."""

from __future__ import annotations

import inspect
import io
import re
from typing import Any

import pytest
from orchestrator.reports import cohort_pdf, common, feasibility_pdf, screen_summary_pdf

JA_ONLY = "験検薬剤経観"  # in Noto Sans JP, not in Noto Sans TC (the review's list)
TC_ONLY = "查值啟"  # in Noto Sans TC, not in Noto Sans JP


def _assigned(markup: str, primary: str) -> list[tuple[str, str]]:
    """(character, font) for every character of the text of ``markup``, as the fallback tags assign them."""
    out: list[tuple[str, str]] = []
    font = primary
    for part in re.split(r"(<font name=\"[^\"]+\">|</font>|<[^>]+>|&[a-z]+;)", markup):
        m = re.fullmatch(r"<font name=\"([^\"]+)\">", part)
        if m:
            font = m.group(1)
        elif part == "</font>":
            font = primary
        elif part and not part.startswith(("<", "&")):
            out += [(ch, font) for ch in part]
    return out


@pytest.mark.parametrize(("locale", "text"), [
    ("en", "Screening for the trial: 治験 検査, 薬剤 and 経過観察"),
    ("zh-TW", "檢查數值 與 治験薬"),
    ("ja", "台湾の記録: 檢查 數值 啟動"),
])  # fmt: skip
def test_every_character_is_set_in_a_font_that_has_it(locale: str, text: str) -> None:
    regular, _ = common.pdf_fonts(locale)
    for ch, font in _assigned(common.with_fallback(text, regular), regular):
        assert ch.isspace() or ord(ch) in common.glyphs(font), (ch, font)


def test_the_premise_each_family_lacks_characters_of_the_other() -> None:
    tc, jp = common.glyphs(common.pdf_fonts("en")[0]), common.glyphs(common.pdf_fonts("ja")[0])
    assert all(ord(c) in jp and ord(c) not in tc for c in JA_ONLY)
    assert all(ord(c) in tc and ord(c) not in jp for c in TC_ONLY)


def test_text_the_font_has_is_left_as_it_is_and_markup_is_kept() -> None:
    regular, bold = common.pdf_fonts("en")
    plain = "Eligible: 12 of 40 &amp; <b>none</b> excluded &lt;18"
    assert common.with_fallback(plain, regular) == plain
    got = common.with_fallback("<b>検査</b> &amp; x", regular)
    assert got.startswith("<b>") and "&amp; x" in got and '<font name="NotoSansJP-Regular">\u691c\u67fb</font>' in got
    assert '<font name="NotoSansJP-Bold">' in common.with_fallback("検", bold)  # a heading stays bold


def test_a_character_neither_family_has_is_left_for_the_primary_font() -> None:
    regular, _ = common.pdf_fonts("en")
    odd = "\U0001f600"  # an emoji: in neither Noto Sans CJK family
    assert common.with_fallback(odd, regular) == odd


def test_a_paragraph_of_a_report_embeds_both_families_and_keeps_the_text() -> None:
    from pypdf import PdfReader
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate

    regular, _ = common.pdf_fonts("en")
    style = ParagraphStyle("b", fontName=regular, fontSize=10)
    buf = io.BytesIO()
    SimpleDocTemplate(buf).build([common.Paragraph("Site: 治験 検査 center", style)])
    page = PdfReader(io.BytesIO(buf.getvalue())).pages[0]
    resources: Any = page["/Resources"]
    fonts = {str(f.get_object()["/BaseFont"]) for f in resources["/Font"].values()}
    assert any("NotoSansTC" in f for f in fonts) and any("NotoSansJP" in f for f in fonts), fonts
    assert "験" in page.extract_text() and "検" in page.extract_text()


@pytest.mark.parametrize("module", [cohort_pdf, feasibility_pdf, screen_summary_pdf])
def test_every_report_builds_its_paragraphs_through_the_fallback(module: object) -> None:
    src = inspect.getsource(module)  # type: ignore[arg-type]
    assert "from reportlab.platypus import" in src and not re.search(r"platypus import[^)\n]*\bParagraph\b", src)
    assert not re.search(r"platypus import \([^)]*\bParagraph\b", src, re.S)
    assert "Paragraph" in src and "common import" in src


def test_a_chart_falls_back_too() -> None:
    import matplotlib.pyplot as plt

    fig = common.figure("en")
    try:
        families = plt.rcParams["font.family"]
        assert len(families) == 2 and len(set(families)) == 2  # the report's family, then the other
    finally:
        plt.close(fig)
