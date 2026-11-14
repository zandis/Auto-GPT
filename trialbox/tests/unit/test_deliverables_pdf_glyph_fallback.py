"""The feasibility pack's PDF (DL-1) draws a character its font lacks in the other family (D-687).

The pack is set in Noto Sans TC. A site name, a table cell or a criterion title written with a character only the
Japanese font has (a Japanese site's 検査科) was a blank box in the heading, the table and the footer: the pack
built its PDF beside the reports and was left out of their fallback (D-681's sibling cards for the reports and the
NAV summary). Synthetic values only."""

from __future__ import annotations

import inspect
import io
import re
from typing import Any

import pytest
from deliverables import render
from deliverables.disclosure import ORDER, sha256

JA_ONLY = "験"  # in Noto Sans JP, not in Noto Sans TC
TC_ONLY = "查"  # in Noto Sans TC, not in Noto Sans JP


def _frozen(site: str = "DEMO-A", cell: str = "plain", title: str = "Cohort", ruleset: str = "GZQO") -> dict[str, Any]:
    obj = {
        "study_id": "S-1",
        "site": {"id": site, "name": site},
        "ruleset": {"id": ruleset, "version": "1.0.0"},
        "snapshot": {"id": "2026-11-01"},
        "profile": {"name": "SPONSOR", "version": "1", "k": 5, "base": 5},
        "headline": {
            "computable_count": 120,
            "adjusted_estimate": {"est": 110, "ci95_low": 90, "ci95_high": 130},
            "projection_12m": {"p10": 2, "p50": 5, "p90": 9},
            "monthly_new_meeting_criteria": 5,
            "top_limiting_criteria": ["I1"],
            "recall_sentence": "measured on synthetic charts",
        },
        "disclaimers": {"disc.ai": "Counts are aggregate."},
        "sections": [{"id": "1", "title": title, "tables": ["F-T1"], "figures": []}],
        "tables": {"F-T1": [{"department": cell, "n": 15}]},
        "figures": {},
        "recall_certificate": {},
        "annex_b_logic_hashes": {},
        "disclosure_trace": {"profile": "SPONSOR", "steps": [{"step": s} for s in ORDER]},
    }
    return {"object": obj, "sha256": sha256(obj), "pngs": {}}


def _page(frozen: dict[str, Any]) -> Any:
    from pypdf import PdfReader

    return PdfReader(io.BytesIO(render.render_pdf(frozen))).pages[0]


def _fonts(page: Any) -> set[str]:
    return {str(f.get_object()["/BaseFont"]) for f in page["/Resources"]["/Font"].values()}


@pytest.mark.parametrize("where", ["heading", "table", "section", "footer"])
def test_a_japanese_only_character_is_drawn_wherever_the_pack_has_text(where: str) -> None:
    text = f"x{JA_ONLY}y"
    frozen = {
        "heading": lambda: _frozen(site=text),  # the first heading names the site (and the footer its id)
        "table": lambda: _frozen(cell=text),
        "section": lambda: _frozen(title=text),
        "footer": lambda: _frozen(ruleset=text),  # the footer names the ruleset
    }[where]()
    page = _page(frozen)
    fonts = _fonts(page)
    assert any("NotoSansTC" in f for f in fonts) and any("NotoSansJP" in f for f in fonts), (where, fonts)
    assert JA_ONLY in page.extract_text(), where


def test_a_japanese_only_and_a_traditional_chinese_only_character_both_draw() -> None:
    page = _page(_frozen(site=f"{JA_ONLY}{TC_ONLY}", cell=f"{TC_ONLY}{JA_ONLY}"))
    got = page.extract_text()
    assert JA_ONLY in got and TC_ONLY in got
    assert {"NotoSansTC", "NotoSansJP"} <= {f.split("+")[-1].split("-")[0] for f in _fonts(page)}


def test_a_pack_in_one_script_embeds_one_family_and_renders_the_same_bytes_twice() -> None:
    frozen = _frozen(site="檢查", cell="風濕免疫科")
    fonts = _fonts(_page(frozen))
    assert any("NotoSansTC" in f for f in fonts) and not any("NotoSansJP" in f for f in fonts), fonts
    assert render.render_pdf(frozen) == render.render_pdf(frozen)  # the pack's bytes stay deterministic
    mixed = _frozen(site=f"{JA_ONLY}{TC_ONLY}")
    assert render.render_pdf(mixed) == render.render_pdf(mixed)


def test_the_pack_is_built_through_the_reports_fallback() -> None:
    src = inspect.getsource(render.render_pdf)
    assert not re.search(r"platypus import[^\n]*\bParagraph\b", src) and "drawString" not in src
    assert "common.Paragraph" in src and "draw_string" in src
