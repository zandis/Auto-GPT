"""Quote matching for model answers (SPEC §7.3, CAS-16): is a model's quote really in the note?

A quote must be copied from one excerpt. Models copy Japanese and Chinese text with stray spaces: Qwen3.5-9B writes
「2 型糖尿病」 for 「2型糖尿病」 and 「500mg 1 日 2 回」 for 「500mg 1日2回」 (2026-11-08 canary, 7 of 27 Japanese
answers). Those languages do not separate words with spaces, so a space next to a CJK character carries no meaning;
:func:`quote_key` drops it before comparing. Everything else stays strict: NFKC, whitespace runs collapsed, Latin
words still need their spaces, and the quote must still be a contiguous part of one excerpt.
"""

from __future__ import annotations

import re
import unicodedata

# kana, CJK ideographs (+ extension A, compatibility), CJK symbols and punctuation, full-width forms, Hangul
_CJK = "　-〿぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯가-힯"
_SPACE_BY_CJK = re.compile(rf"(?<=[{_CJK}]) | (?=[{_CJK}])")


def quote_key(text: str) -> str:
    t = " ".join(unicodedata.normalize("NFKC", text).split())
    return _SPACE_BY_CJK.sub("", t)


#: what an excerpt shows, on a line of its own, where sentences of its note were left out (NEW-LLM-1, D-641)
CUT = "[…]"


def runs(text: str) -> list[str]:
    """The parts of an excerpt between two :data:`CUT` lines: each is one unbroken piece of the note."""
    out: list[list[str]] = [[]]
    for line in text.split("\n"):
        if line.strip() == CUT:
            out.append([])
        else:
            out[-1].append(line)
    return ["\n".join(r) for r in out if r]


def quote_in(quote: str, text: str) -> bool:
    """Whether ``quote`` is a contiguous part of ``text``. In an excerpt with cuts (D-641) it must lie inside one
    unbroken piece: text on both sides of a cut is not next to each other in the note, and the mark is not in it."""
    q = quote_key(quote)
    return bool(q) and any(q in quote_key(r) for r in runs(text))


__all__ = ["CUT", "quote_in", "quote_key", "runs"]
