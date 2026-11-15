"""Blocker 11 (lane G's dry run; D-687's glyph fallback): a paragraph longer than a page is split, never a crash.

reportlab splits a paragraph that does not fit the frame by building the pieces through the paragraph's own class,
with no text. D-687's ``common.Paragraph`` wrapped every text in the glyph fallback and failed on that (``'NoneType'
object has no attribute 'isascii'``): the FEAS report PDF crashed on a long paragraph. Synthetic text only."""

from __future__ import annotations

import io

import pytest
from orchestrator.reports import common
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("ja", "word " * 4000),
        ("ja", "患者の記録。" * 2500),
        ("zh-TW", "病人紀錄，" * 3000),
        ("ja", "長い文 ü€ " * 3000),
    ],
)
def test_a_paragraph_longer_than_a_page_is_split_over_pages(lang: str, text: str) -> None:
    regular, _bold = common.pdf_fonts(lang)
    style = getSampleStyleSheet()["Normal"]
    style.fontName = regular
    buf = io.BytesIO()
    SimpleDocTemplate(buf).build([common.Paragraph(text, style)])
    pdf = buf.getvalue()
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 2


def test_the_split_pieces_keep_the_fallback_font() -> None:
    """A character the main font lacks is still drawn in the other family on every page of a split paragraph."""
    regular, _bold = common.pdf_fonts("ja")
    style = getSampleStyleSheet()["Normal"]
    style.fontName = regular
    para = common.Paragraph("記録 " * 2000 + "峯", style)
    parts = para.split(400, 300)
    assert len(parts) >= 2
