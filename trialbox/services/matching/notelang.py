"""The language a patient's notes are written in (NOTE-LANGUAGE-THRESHOLDS, D-983).

The cascade took the site's report locale (``site.locale``) as the language of the notes; the owner confirmed
(2026-11-16) that a Taiwan site's charts are mainly English, so its English notes were read as zh-TW wherever a choice
depended on the language. The language is read from the notes themselves, by script: kana means Japanese; Han
characters without kana mean Chinese; Latin words mean English. A Taiwan chart with English text under Chinese
headings and Chinese drug names reads as English (its words outnumber its characters); a Japanese note with English
drug names reads as Japanese. A text too short to tell gives None, and the caller's fallback decides.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

LANGS = ("en", "zh-TW", "ja")
_KANA = re.compile(r"[぀-ヿㇰ-ㇿ]")
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_WORD = re.compile(r"[A-Za-z]{2,}")
CJK_PER_WORD = 2.0  # Han / kana characters to one English word, roughly, for the comparison
MIN_SIGNS = 6  # fewer words and characters than this: too short to tell


def note_language(text: str) -> str | None:
    """``en``, ``zh-TW`` or ``ja`` for ``text``, or None when it is too short to tell."""
    kana, han, words = len(_KANA.findall(text or "")), len(_HAN.findall(text or "")), len(_WORD.findall(text or ""))
    if kana + han + words < MIN_SIGNS:
        return None
    if (kana + han) / CJK_PER_WORD > words:
        return "ja" if kana >= max(3, 0.1 * han) else "zh-TW"
    return "en"


def main_language(texts: Iterable[str], fallback: str) -> str:
    """The language most of ``texts`` are written in, weighted by length; ``fallback`` when none can tell."""
    weight: dict[str, int] = {}
    for t in texts:
        lang = note_language(t)
        if lang is not None:
            weight[lang] = weight.get(lang, 0) + len(t)
    return max(weight, key=lambda k: (weight[k], k)) if weight else fallback


def notes_language(setting: str | None, texts: Iterable[str], fallback: str) -> str:
    """The language a choice should use for these notes: the site's declared one (``notes_language``, one of
    :data:`LANGS`), else read from the notes (``auto``, the default), else ``fallback`` (the report locale)."""
    if setting in LANGS:
        return str(setting)
    return main_language(texts, fallback)
