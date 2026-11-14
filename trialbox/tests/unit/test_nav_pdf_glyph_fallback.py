"""The NAV summary PDF draws a character its own font lacks in the other family (the review of #477's fallback:
``scenarios/nav.py`` built its PDF beside the reports and was left out).

A zh-TW site's page is set in Noto Sans TC, a Japanese site's in Noto Sans JP; each lacks characters of the other
(a department named 検査科 on a zh-TW box, 檢查科 with 查 on a Japanese one). Without the fallback such a character
is a blank box in the title, the departments line, the table and the footer."""

from __future__ import annotations

import inspect
import io
import re
from types import SimpleNamespace
from typing import Any

import pytest
from orchestrator.reports.common import ReportMeta
from orchestrator.scenarios import nav

JA_ONLY = "験"  # in Noto Sans JP, not in Noto Sans TC
TC_ONLY = "查"  # in Noto Sans TC, not in Noto Sans JP


def _pdf(locale: str, title: str, dept: str, label: str, site: str) -> Any:
    from pypdf import PdfReader

    rs: Any = SimpleNamespace(id="NAVX", manifest=SimpleNamespace(title=title))
    meta = ReportMeta(site, site, "NAVX", "1.0.0", "no model (filters only)", "2026-11-01", "J1", "2026-11-13", locale)
    data = nav._summary_pdf(rs, meta, [dept], {label: 12, "to review": 3}, 14, 5)
    return PdfReader(io.BytesIO(data)).pages[0]


def _fonts(page: Any) -> set[str]:
    return {str(f.get_object()["/BaseFont"]) for f in page["/Resources"]["/Font"].values()}


@pytest.mark.parametrize(
    ("locale", "own", "other", "foreign"),
    [("zh-TW", "NotoSansTC", "NotoSansJP", JA_ONLY), ("ja", "NotoSansJP", "NotoSansTC", TC_ONLY)],
)
@pytest.mark.parametrize("where", ["title", "department", "table", "footer"])
def test_a_character_of_the_other_family_is_drawn_wherever_the_page_has_text(
    locale: str, own: str, other: str, foreign: str, where: str
) -> None:
    text = {k: "plain" for k in ("title", "department", "table", "footer")}
    text[where] = f"x{foreign}y"
    page = _pdf(locale, text["title"], text["department"], text["table"], text["footer"])
    fonts = _fonts(page)
    assert any(own in f for f in fonts) and any(other in f for f in fonts), (where, fonts)
    assert foreign in page.extract_text(), where


def test_a_japanese_only_and_a_traditional_chinese_only_character_both_draw_on_one_page() -> None:
    for locale in ("zh-TW", "ja"):
        page = _pdf(locale, f"{JA_ONLY}{TC_ONLY}", "RHEU", "eligible", "DEMO-A")
        got = page.extract_text()
        assert JA_ONLY in got and TC_ONLY in got, locale
        assert {"NotoSansTC", "NotoSansJP"} <= {f.split("+")[-1].split("-")[0] for f in _fonts(page)}


def test_a_page_in_one_script_embeds_one_family() -> None:
    fonts = _fonts(_pdf("zh-TW", "檢查", "風濕免疫科", "eligible", "DEMO-A"))
    assert any("NotoSansTC" in f for f in fonts) and not any("NotoSansJP" in f for f in fonts), fonts


def test_the_page_is_built_through_the_reports_fallback() -> None:
    src = inspect.getsource(nav._summary_pdf)
    assert not re.search(r"platypus import[^\n]*\bParagraph\b", src) and "drawString" not in src
    assert "common.Paragraph" in src and "draw_string" in src
