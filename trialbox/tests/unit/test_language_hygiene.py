"""TB-PLAN-03 step 4 (D-119): refusals, feasibility notes and reason codes in the page's language; the mail text part
rendered from Markdown. No network."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from console.refusals import REFUSALS, UNTRANSLATED, localize, localize_reason
from mail_gateway.outbound import plain_text
from tb_common.feas_notes import NOTES, notes_for, render
from tb_common.reasons import LABELS, code_of, label

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "services" / "console"


def _static_reasons() -> set[str]:
    out: set[str] = set()
    for p in CONSOLE.glob("*.py"):
        for m in re.finditer(
            r'[pP]roblem\(\s*\d{3},\s*"[a-z_.]+",\s*reason="([^"{}]+)"', p.read_text(encoding="utf-8")
        ):
            out.add(m.group(1))
    return out


def test_every_static_refusal_has_japanese_and_chinese_words() -> None:
    reasons = _static_reasons()
    assert len(reasons) >= 20
    missing = [r for r in reasons if localize_reason(r, "ja") in ("", UNTRANSLATED["ja"])]
    assert not missing, missing
    for en, (ja, zh) in REFUSALS.items():
        assert not ja.isascii() and not zh.isascii(), en
        assert localize_reason(en, "en") == en


def test_an_unknown_refusal_never_shows_english_on_a_japanese_page() -> None:
    text = "HTTP 500 from lake: Traceback ..."
    assert localize_reason(text, "ja") == UNTRANSLATED["ja"]
    assert localize_reason(text, "zh-TW") == UNTRANSLATED["zh-TW"]
    assert localize({"reason": text, "n": 3}, "ja") == {"reason": UNTRANSLATED["ja"], "n": 3}


ARGS = {"n": 5, "first": "2024-01-31", "last": "2026-10-31", "t1": 4, "t": 5, "variant": "unknown_as_pass",
        "lam": "<5", "m": 12, "id": "X-INC-01", "ids": "X-INC-02, X-EXC-03"}  # fmt: skip


@pytest.mark.parametrize("key", sorted(NOTES))
def test_every_feasibility_note_renders_in_three_languages(key: str) -> None:
    en = render(key, ARGS, "en")
    assert en and "{" not in en
    for lang in ("ja", "zh-TW"):
        words = render(key, ARGS, lang)
        assert words and "{" not in words and not words.isascii(), (key, lang)


def test_notes_for_uses_the_keys_and_never_falls_back_to_english_off_en() -> None:
    res = {"notes": ["English line."], "note_keys": [{"key": "feas.note.washout", "args": {"m": 12}}]}
    assert notes_for(res, "ja") == [render("feas.note.washout", {"m": 12}, "ja")]
    old = {"notes": ["English line."]}
    assert notes_for(old, "en") == ["English line."] and notes_for(old, "ja") == []


def test_unknown_kept_is_its_own_code_with_words() -> None:
    assert code_of("unknown_kept", "pass") == "unknown_kept"
    assert set(LABELS["unknown_kept"]) == {"en", "ja", "zh-TW"}
    assert not label("unknown_kept", "zh-TW").isascii()


def test_mail_text_part_has_no_markdown_marks() -> None:
    md = (
        "## This week\n\n**3 patients** for *clinic*.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "- see [the list](https://box.local/week)\n> quoted\n`PUB-ONC`\n"
    )
    text = plain_text(md)
    for mark in ("##", "**", "](", "|---", "`"):
        assert mark not in text, (mark, text)
    assert "3 patients" in text and "the list (https://box.local/week)" in text and "- see" in text
