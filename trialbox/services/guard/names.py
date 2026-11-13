"""Does a NAME finding of the tripwire stand? (NEW-LLM-3/4, D-647; the owner's ruling of 2026-11-13.)

The name recognisers are patterns: a surname character, one or two more characters, and a cue (a label, an
honorific, a sex). In running Chinese or Japanese text that shape is everywhere (曾使用, 高血圧, 林さん's 林 in
林檎), so the tripwire refused ordinary criteria and notes: every sentence of the measured false-positive sets in
zh-TW, 72.7 % in Japanese. This module is the second look. It can only take a NAME finding away; every other
kind of finding, and every name it does not understand, stands.

* **Japanese** (the finding's line holds kana): the finding stands only if the tokeniser tags a token inside it as
  a proper noun (SudachiPy, split mode C, the pinned dictionary: :data:`DICTIONARY`). Measured on the labelled
  synthetic sets: 97.6 % of names kept, false refusals 72.7 % to 3.0 %.
* **Chinese** (no kana on the line): no tokeniser. The finding stands when a boundary follows it (the end, a
  punctuation mark, a space, an honorific, a sex). Else it stands unless it begins a common word
  (``data/zh_common_words.txt``), or its surname character is an ordinary one-character word followed by a common
  word, with or without a one-character verb or adverb between (曾｜使用, 曾｜有｜出現). Measured: 97.9 % of
  names kept, false refusals 100 % to 17.9 %.

**It fails closed** (the integrator's condition): when the tokeniser or its dictionary cannot be loaded, raises, or
the line is longer than :data:`MAX_LINE`, the finding stands, as before this card; :func:`status` says which, for
``doctor`` and the gateway's start. A name the tokeniser does not tag (a rare surname, a name in kana) is let
through where it was refused before: that is the trade the owner accepted, and the card's stated limit.
"""

from __future__ import annotations

import csv
import importlib
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from tb_common import phi_guard

#: the dictionary the Japanese figures were measured with; another one is a re-measurement (D-647)
DICTIONARY = "sudachidict-core 20261015"
#: a line longer than this is not put to the tokeniser: the finding stands. A note line or a criterion is a few
#: hundred characters; one this long is not prose, and the tokeniser's time grows with the line
MAX_LINE = 4000
WORDS = Path(__file__).with_name("data") / "zh_common_words.txt"

_KANA = re.compile(r"[぀-ヿ]")
_BOUND = set("，,、。．.：:；;（()） 　\t\n！!？?／/")
_FOLLOW = re.compile(r"^\s?(?:先生|小姐|女士|太太|老先生|老太太|阿嬤|阿公|君|[，,、\s]*[（(]?(?:男|女)[)）]?)")
_PROPER = "固有名詞"


# ------------------------------------------------------------------------------------------------ Chinese
@lru_cache(maxsize=1)
def _words() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(common words of 2 to 4 characters, very common one-character words, surname characters that are ordinary
    one-character words) from the shipped list."""
    word: set[str] = set()
    one: set[str] = set()
    plain: set[str] = set()
    with WORDS.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            {"word": word, "one": one, "plain": plain}[row["kind"]].add(row["word"])
    return frozenset(word), frozenset(one), frozenset(plain & phi_guard.ROC_SURNAMES)


def _any(words: frozenset[str], text: str, at: int) -> bool:
    return any(text[at : at + n] in words for n in (4, 3, 2))


def zh_stands(text: str, start: int, end: int) -> bool:
    """The Chinese rule (V6 of the measurement)."""
    if end >= len(text) or text[end] in _BOUND or _FOLLOW.match(text[end:]):
        return True
    word, one, plain = _words()
    if _any(word, text, start):  # the "name" begins a common word (高血壓, 許可)
        return False
    # 曾, 高, 於 ... as a word of its own, and a common word after it (with or without one short word between)
    after = _any(word, text, start + 1) or (text[start + 1 : start + 2] in one and _any(word, text, start + 2))
    return not (text[start] in plain and after)


# ------------------------------------------------------------------------------------------------ Japanese
class _Tagger:
    """SudachiPy with its dictionary, loaded once, on first use. ``error``: why it is not there."""

    def __init__(self) -> None:
        self.error = ""
        self._tok: Any = None
        self._mode: Any = None
        self._lock = threading.Lock()
        self._tried = False

    def load(self) -> bool:
        with self._lock:
            if not self._tried:
                self._tried = True
                try:
                    dictionary = importlib.import_module("sudachipy.dictionary")
                    tokenizer = importlib.import_module("sudachipy.tokenizer")
                    self._tok = dictionary.Dictionary().create()
                    self._mode = tokenizer.Tokenizer.SplitMode.C
                except Exception as exc:  # not installed, no dictionary, a dictionary of another format
                    self.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        return self._tok is not None

    def proper_noun(self, line: str, start: int, end: int) -> bool | None:
        """Whether a token overlapping ``line[start:end]`` is tagged a proper noun; None: could not be told."""
        if not self.load():
            return None
        try:
            with self._lock:  # one tokeniser object; the gateway calls from several threads
                return any(
                    m.part_of_speech()[1] == _PROPER
                    for m in self._tok.tokenize(line, self._mode)
                    if m.begin() < end and m.end() > start
                )
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {str(exc)[:200]}"
            return None


_TAGGER = _Tagger()


def _line(text: str, start: int, end: int) -> tuple[str, int, int]:
    a = text.rfind("\n", 0, start) + 1
    b = text.find("\n", end)
    b = len(text) if b < 0 else b
    return text[a:b], start - a, end - a


def stands(text: str, start: int, end: int) -> bool:
    """Whether the NAME finding ``text[start:end]`` stands. Never raises: whatever goes wrong, it stands."""
    try:
        line, s, e = _line(text, start, end)
        if not _KANA.search(line):
            return zh_stands(text, start, end)
        if len(line) > MAX_LINE:
            return True
        tagged = _TAGGER.proper_noun(line, s, e)
        return True if tagged is None else tagged
    except Exception:
        return True


def status() -> dict[str, Any]:
    """For ``doctor`` and a service's start: is the Japanese tokeniser there, and the Chinese list?"""
    ok = _TAGGER.load()
    try:
        n_words = len(_words()[0])
        words_error = ""
    except Exception as exc:
        n_words, words_error = 0, f"{type(exc).__name__}: {str(exc)[:200]}"
    return {
        "tokeniser": ok,
        "dictionary": DICTIONARY,
        "error": _TAGGER.error,
        "zh_words": n_words,
        "zh_error": words_error,
        "effect": ""
        if ok and n_words
        else "name findings the second look cannot check stand: more ordinary text is refused, none is let through",
    }


__all__ = ["DICTIONARY", "MAX_LINE", "stands", "status", "zh_stands"]
