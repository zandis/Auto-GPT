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
# a word: three letters or more with lower case in it; an abbreviation (SOB, CBC, Hb, Na) or a unit is no word
_WORD = re.compile(r"\b(?=[A-Za-z]*[a-z][A-Za-z]*[a-z])[A-Za-z]{3,}\b")
# kanji written only in Japanese (the Chinese forms differ: 歷 藥 發 變 檢 查 實 應 價 圖 壓 濟 樣): a Japanese note in
# kanji with few kana ("既往歴：高血圧、糖尿病") is still Japanese
_JA_KANJI = re.compile(r"[歴薬発変検査実応価図圧済様険読続転帰剤]")
CJK_PER_WORD = 2.0  # Han / kana characters to one English word, roughly, for the comparison
MIN_SIGNS = 6  # fewer words and characters than this: too short to tell


def note_language(text: str) -> str | None:
    """``en``, ``zh-TW`` or ``ja`` for ``text``, or None when it is too short to tell."""
    kana, han, words = len(_KANA.findall(text or "")), len(_HAN.findall(text or "")), len(_WORD.findall(text or ""))
    if kana + han + words < MIN_SIGNS:
        return None
    if (kana + han) / CJK_PER_WORD > words:
        return "ja" if kana >= 2 or _JA_KANJI.search(text) else "zh-TW"
    return "en"


def signs(text: str) -> int:
    """How much language a text holds: its words and its Han / kana characters (digits and symbols are none, so a
    long lab table does not outweigh the narrative)."""
    return len(_KANA.findall(text or "")) + len(_HAN.findall(text or "")) + len(_WORD.findall(text or ""))


def family(locale: str) -> str:
    """The language a locale names (``ja-JP`` -> ``ja``, ``zh-Hant`` -> ``zh-TW``, ``en-US`` -> ``en``)."""
    low = (locale or "").lower()
    return (
        "ja" if low.startswith("ja") else "zh-TW" if low.startswith("zh") else "en" if low.startswith("en") else locale
    )


def main_language(texts: Iterable[str], fallback: str) -> str:
    """The language most of ``texts`` are written in, weighted by length; ``fallback`` when none can tell."""
    weight: dict[str, int] = {}
    for t in texts:
        lang = note_language(t)
        if lang is not None:
            weight[lang] = weight.get(lang, 0) + signs(t)
    return max(weight, key=lambda k: (weight[k], k)) if weight else fallback


def notes_language(setting: str | None, texts: Iterable[str], fallback: str) -> str:
    """The language a choice should use for these notes: the site's declared one (``notes_language``, one of
    :data:`LANGS`), else read from the notes (``auto``, the default), else ``fallback`` (the report locale)."""
    if setting in LANGS:
        return str(setting)
    return main_language(texts, fallback)


def cascade_languages(setting: str, data_locale: str) -> tuple[str, str]:
    """D-987: ``(language, notes_language)`` for a ``CascadeConfig`` built outside SCREEN (the measurement tools).
    ``setting`` is the tool's ``--language`` (``auto``, the default, or one of :data:`LANGS`): a named language is
    the notes' and the fallback's both; ``auto`` reads each patient's notes, with the tool's data's own locale as the
    fallback (never the engine's default, which once set it for every run)."""
    if setting == "auto":
        return data_locale, "auto"
    if setting not in LANGS:
        raise ValueError(f"--language {setting!r}: give auto or one of {', '.join(LANGS)}")
    return setting, setting
