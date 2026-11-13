"""Does a NAME finding of the tripwire stand? (NEW-LLM-3/4, D-647; the owner's ruling of 2026-11-13.)

The name recognisers are patterns: a surname character, one or two more characters, and a cue (a label, an
honorific, a sex). In running Chinese or Japanese text that shape is everywhere (曾使用, 高血圧, 林さん's 林 in
林檎), so the tripwire refused ordinary criteria and notes: every sentence of the measured false-positive sets in
zh-TW, 72.7 % in Japanese. This module is the second look. It can only take a NAME finding away; every other
kind of finding, and every name it does not understand, stands.

* **What always keeps a finding**: an honorific inside or after it, a sex after it, a surname of more than one
  character, or a boundary after it (the end, or any character that is not kana or Han).
* **Else, on a line with kana**: it stands if the tokeniser tags a token inside it as a proper noun (SudachiPy,
  split mode C, the pinned dictionary: :data:`DICTIONARY`); it is ordinary Japanese when a longer word of that
  dictionary holds the surname's place; else the next rule decides.
* **Else, on a line without kana**: no tokeniser. It stands unless it reads as words
  (``data/zh_common_words.txt``): it begins a common word, or its surname character is an ordinary
  one-character word followed by a common word (曾｜使用, 曾｜有｜出現); never when the characters after the
  surname are ones given names are made of.

The measured figures, the sets and what the first form of this rule got wrong are in D-647.

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

# kana that says "this line is Japanese": not the middle dot and the double hyphen (punctuation), not the long
# vowel mark alone (it follows kana)
_KANA = re.compile(r"[ぁ-ゟァ-ヺヽ-ヿ]")
# what a name can run into: kana and Han. Anything else after a finding is a boundary; so are ・ and ゠
_CJK = re.compile(r"[ぁ-ゟァ-ヺー-ヿ㐀-鿿]")
_HONORIFIC = re.compile(phi_guard.HONORIFIC)
_FOLLOW = re.compile(rf"^\s?(?:{phi_guard.HONORIFIC}|[，,、\s]*[（(]?(?:男|女)[)）]?)")
_PROPER = "固有名詞"
# a surname of more than one character says "name" by itself: the compound Chinese ones, the Japanese ones
_LONG_SURNAMES = tuple(
    sorted(phi_guard.ROC_COMPOUND | {x for x in phi_guard.JP_SURNAMES if len(x) > 1}, key=len, reverse=True)
)


# ------------------------------------------------------------------------------------------------ the word list
@lru_cache(maxsize=1)
def _words() -> tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[str]]:
    """(common words of 2 to 4 characters, very common one-character words, surname characters that are ordinary
    one-character words, characters given names are made of) from the shipped list."""
    kinds: dict[str, set[str]] = {"word": set(), "one": set(), "plain": set(), "given": set()}
    with WORDS.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            kinds[row["kind"]].add(row["word"])
    if not all(kinds.values()):
        raise ValueError(f"{WORDS.name}: a kind of the word list is empty")
    plain = kinds["plain"] & phi_guard.ROC_SURNAMES
    return frozenset(kinds["word"]), frozenset(kinds["one"]), frozenset(plain), frozenset(kinds["given"])


def _any(words: frozenset[str], text: str, at: int) -> bool:
    return any(text[at : at + n] in words for n in (4, 3, 2))


# ------------------------------------------------------------------------------------------------ the cues
def _cue(text: str, start: int, end: int) -> bool:
    """What says "a name" whatever the words around it: an honorific inside the match or right after it, a sex
    after it, a surname of more than one character."""
    found = text[start:end]
    return bool(_HONORIFIC.search(found) or _FOLLOW.match(text[end:]) or found.startswith(_LONG_SURNAMES))


def _boundary(text: str, end: int) -> bool:
    """The match ends where the writing ends: the text's end, or any character that is not kana or Han (a
    punctuation mark, a space, a line end of any kind, a digit, a Latin letter)."""
    return end >= len(text) or not _CJK.match(text[end])


def _reads_as_words(text: str, start: int, end: int) -> bool:
    """The match is ordinary words, not a name: it begins a common word (高血壓, 許可), or its surname character
    is an ordinary one-character word with a common word after it, with or without one short word between
    (曾｜使用, 曾｜有｜出現). Never when every character after the surname is one that given names are made of
    (高｜建國). 王家豪 and 黃志豪 do read as words (王家, 志豪; 豪 is no listed name character): the stated limit."""
    word, one, plain, given = _words()
    rest = text[start + 1 : end]
    if rest and all(ch in given for ch in rest):
        return False
    if _any(word, text, start):
        return True
    after = _any(word, text, start + 1) or (text[start + 1 : start + 2] in one and _any(word, text, start + 2))
    return text[start] in plain and after


def zh_stands(text: str, start: int, end: int) -> bool:
    """The Chinese rule: a cue or a boundary keeps the finding; else it stands unless it reads as words."""
    return _cue(text, start, end) or _boundary(text, end) or not _reads_as_words(text, start, end)


# ------------------------------------------------------------------------------------------------ Japanese
class _Tagger:
    """SudachiPy with its dictionary, loaded once, on first use. ``error``: why it is not there, or what its last
    failure was (``failed``: it has failed on a text since it was loaded)."""

    def __init__(self) -> None:
        self.error = ""
        self.failed = False
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

    def tokens(self, line: str) -> list[tuple[int, int, str]] | None:
        """The tokens of ``line`` as (start, end, kind): ``proper`` (tagged a proper noun), ``word`` (another word
        of the dictionary) or ``unknown`` (not in the dictionary); None: could not be told."""
        if not self.load():
            return None
        try:
            with self._lock:  # one tokeniser object; the gateway calls from several threads
                return [
                    (
                        m.begin(),
                        m.end(),
                        "proper" if m.part_of_speech()[1] == _PROPER else "unknown" if m.is_oov() else "word",
                    )
                    for m in self._tok.tokenize(line, self._mode)
                ]
        except Exception as exc:
            self.error, self.failed = f"{type(exc).__name__}: {str(exc)[:200]}", True
            return None


_TAGGER = _Tagger()


def _line(text: str, start: int, end: int) -> tuple[str, int, int]:
    a = max(text.rfind("\n", 0, start), text.rfind("\r", 0, start)) + 1
    ends = [x for x in (text.find("\n", end), text.find("\r", end)) if x >= 0]
    b = min(ends) if ends else len(text)
    return text[a:b], start - a, end - a


class Look:
    """The second look of one tripwire call: each line is put to the tokeniser once, and nothing of the text is
    kept after the call."""

    def __init__(self) -> None:
        self._tagged: dict[str, list[tuple[int, int, str]] | None] = {}

    def stands(self, text: str, start: int, end: int) -> bool:
        """Whether the NAME finding ``text[start:end]`` stands. Never raises: whatever goes wrong, it stands."""
        try:
            line, s, e = _line(text, start, end)
            if not _KANA.search(line) or len(line) > MAX_LINE:
                return True  # option B: Chinese, and any line without kana, exactly as before this card
            if line not in self._tagged:
                self._tagged[line] = _TAGGER.tokens(line)
            tokens = self._tagged[line]
            if tokens is None or any(kind == "proper" for b, x, kind in tokens if b < e and x > s):
                return True
            if _cue(text, start, end):
                return True
            # option B: an untagged finding with no cue is taken away only when it is plainly Japanese text: a
            # word of the tokeniser's own dictionary, longer than one character, covers the match from the
            # surname's place to its end (高血圧, 連絡), or the match itself holds kana (何かを). Everything else
            # stands: a name the dictionary does not know, a Chinese name beside kana (丁子｜涵: 丁子 is a word,
            # but it does not cover the name)
            covered = any(b <= s and x >= e for b, x, kind in tokens if kind == "word" and x - b > 1)
            return not (covered or _KANA.search(line[s:e]))
        except Exception:
            return True


def stands(text: str, start: int, end: int) -> bool:
    """:meth:`Look.stands` for one finding."""
    return Look().stands(text, start, end)


def status() -> dict[str, Any]:
    """For ``doctor`` and a service's start: is the Japanese tokeniser there and working, and the Chinese list?"""
    ok = _TAGGER.load() and not _TAGGER.failed
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


__all__ = ["DICTIONARY", "MAX_LINE", "Look", "stands", "status", "zh_stands"]
