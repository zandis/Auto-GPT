"""Consent explainer checks that need no model: quote grounding, number rules, languages, release selection, pages."""

from __future__ import annotations

from typing import Any

import pytest
from orchestrator.clients import StepFailed
from orchestrator.reports import consent_html
from orchestrator.scenarios import consent as c

ICF = (
    "Taking part is voluntary. You will come to the hospital for 14 visits. Most visits take about 2 hours. "
    "You will receive NT$1,000 for each completed visit. In earlier studies, nausea happened in about 4 out of 10 people."
)


def test_quote_found_is_verbatim_modulo_spacing_case_and_typography() -> None:
    icf = c.norm(ICF)
    assert c.quote_found("Most visits take about 2 hours.", icf)
    assert c.quote_found("most   visits take ABOUT 2 hours", icf)
    assert c.quote_found("You will come to the hospital ... about 2 hours", icf)  # elided, in order
    assert not c.quote_found("about 2 hours ... You will come to the hospital", icf)  # out of order
    assert not c.quote_found("All visits take about 2 hours.", icf)  # reworded
    assert not c.quote_found("voluntary", icf)  # too short to ground anything
    assert c.quote_found("Taking part is voluntary", c.norm("Taking part is **voluntary**."))  # Markdown emphasis
    assert c.quote_found("“Taking part” – voluntary", c.norm('"Taking part" - voluntary'))


def test_number_rules() -> None:
    assert c.numbers("NT$1,000 for 14 visits, 2.5 mg") == ["1000", "14", "2.5"]
    assert c.numbers_ok("You get NT$1000 per visit.", "You will receive NT$1,000 for each completed visit.")
    assert not c.numbers_ok("You get NT$2,000 per visit.", "You will receive NT$1,000 for each completed visit.")
    src = "Most visits take about 2 hours."
    assert c.translation_numbers_ok(src, "ほとんどの来院は約2時間です。", src)
    assert not c.translation_numbers_ok(src, "ほとんどの来院は約3時間です。", src)  # changed
    assert not c.translation_numbers_ok(src, "ほとんどの来院は長時間です。", src)  # lost
    weekly = "Inject the study medicine every week."
    assert c.translation_numbers_ok(weekly, "研究薬を週1回注射します。", weekly)  # a small count written as a digit
    assert not c.translation_numbers_ok(weekly, "研究薬を週40mg注射します。", weekly)  # a new dose is not


def test_languages_and_ids() -> None:
    assert c.parse_langs(None) == ["en", "ja", "zh-TW"]
    assert c.parse_langs("zh-tw,EN,jp,en") == ["zh-TW", "en", "ja"]
    with pytest.raises(StepFailed, match="supported languages"):
        c.parse_langs("en,fr")
    assert c.ids("i03, q2") == ["I03", "Q2"]
    with pytest.raises(StepFailed, match="unknown item"):
        c.ids("I3")
    assert c.detect_language(ICF) == "en"
    assert c.detect_language("本研究的目的是了解每週一次的藥物是否能降低尿酸。" * 3) == "zh-TW"
    assert c.detect_language("この研究の目的は、尿酸を下げるかどうかを調べることです。" * 3) == "ja"


def test_paragraphs_keep_headings_and_order() -> None:
    paras = c.paragraphs_from_text(
        "# Title\n\n## 1. Why?\n\nFirst line\ncontinues.\n\nSecond.\n\n## 2. Risks\n\nThird."
    )
    assert [(p["id"], p["heading"], p["text"]) for p in paras] == [
        ("P1", "1. Why?", "First line continues."),
        ("P2", "1. Why?", "Second."),
        ("P3", "2. Risks", "Third."),
    ]


def _rec() -> dict[str, Any]:
    def item(i: str, sec: str, status: str, removed: str | None = None) -> dict[str, Any]:
        return {
            "id": i,
            "section": sec,
            "quote": "q",
            "para": "P1",
            "removed": removed,
            "texts": {"en": {"text": f"<b>{i}</b>", "status": status}, "ja": {"text": f"ja {i}", "status": "ok"}},
        }

    return {
        "study": "GZQO",
        "job_id": "01JOB",
        "site": "DEMO-A",
        "requested_by": "crc1@hospa.test",
        "created": "2026-10-25T09:00:00+08:00",
        "icf": {"filename": "icf.md", "sha256": "ab" * 32, "language": "en", "paragraphs": 3},
        "source_language": "en",
        "languages": ["en", "ja"],
        "models": {"draft": "j", "verifier": None},
        "items": [
            item("I01", "purpose", "ok"),
            item("I02", "risks", "held"),
            item("I03", "rights", "unverified"),
            item("I04", "risks", "ok", removed="quote not found in the consent form"),
        ],
        "questions": [
            {
                "id": "Q1",
                "quote": "q",
                "para": "P1",
                "removed": None,
                "texts": {"en": {"question": "Can you stop?", "answer": "Yes", "status": "ok"}},
            }
        ],
        "missing_sections": ["contacts"],
        "issues": [],
        "verified": False,
        "release": None,
    }


def test_release_selection_and_counts() -> None:
    rec = _rec()
    shown = c.released_view(rec, "en", [], [])
    assert [x["id"] for x in shown["items"]] == ["I01", "I03"] and [q["id"] for q in shown["questions"]] == ["Q1"]
    assert [x["id"] for x in c.released_view(rec, "en", ["I01"], ["I02"])["items"]] == ["I02", "I03"]
    assert [x["id"] for x in c.released_view(rec, "en", [], ["I04"])["items"]] == ["I01", "I03"]  # removed stays out
    assert c.released_view(rec, "ja", [], [])["questions"] == []  # no ja text for Q1
    assert c.counts(rec) == {"items": 4, "questions": 1, "removed": 1, "held": 1, "unverified": 1, "ok": 5}


def test_pages_label_escape_and_draft_state() -> None:
    rec = _rec()
    draft = consent_html.patient(rec, "en", c.released_view(rec, "en", [], []), release=None).decode()
    assert "DRAFT for the study team" in draft and consent_html.DISCLAIMER["en"] in draft
    assert "&lt;b&gt;I01&lt;/b&gt;" in draft and "<b>I01</b>" not in draft  # model text is escaped
    assert "<script" not in draft and "http" not in draft.replace("http-equiv", "")  # nothing to fetch or run
    rel = {"by": "pi@hospa.test", "at": "2026-10-26T10:00:00+08:00", "job_id": "01REL", "drop": [], "keep": []}
    ja = consent_html.patient(rec, "ja", c.released_view(rec, "ja", [], []), release=rel).decode()
    assert "下書き" not in ja and "pi@hospa.test が確認し" in ja and consent_html.DISCLAIMER["ja"] in ja
    assert '<html lang="ja">' in ja
    sheet = consent_html.review(rec).decode()
    assert "RELEASE 01JOB" in sheet and "not configured" in sheet and "Not covered" in sheet and "removed" in sheet


def test_contact_mask_passes_the_tripwire_and_restores() -> None:
    from guard.guard import Guard

    text = (
        "Call the study coordinator, Ms. Lin, at 02-2312-3456 extension 7701. After hours, call 02-2312-3456 "
        "extension 9. 聯絡人：林小美小姐，電話 (02) 2312-3456。"
    )
    mask = c.ContactMask(r"^\\d{8}$")
    masked = mask.mask(text)
    assert "Lin" not in masked and "2312" not in masked and "林小美" not in masked
    assert masked.startswith("Call the study coordinator, [[CONTACT_A]], at [[CONTACT_B]]")
    assert masked.count("[[CONTACT_B]]") == 2  # the same number twice gets one token
    assert not Guard(r"^\\d{8}$").tripwire(masked).hit
    assert c.numbers(masked) == ["7701", "9"]  # tokens carry no digits for the number checks
    assert mask.unmask(masked) == text
    assert mask.unmask({"items": [{"text": masked}], "n": 1}) == {"items": [{"text": text}], "n": 1}
